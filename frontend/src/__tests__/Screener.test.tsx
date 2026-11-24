import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import type { Screen, ScreenResult } from "../api/types";
import ScreenList, { ranText } from "../components/screens/ScreenList";
import ScreenResults, { newSymbols, sortResults } from "../components/screens/ScreenResults";
import Screener from "../pages/Screener";
import { RUN_POLL_MS } from "../lib/runs";
import { resetRuntime } from "../lib/useRuntime";
import { setPhone } from "./phone";

afterEach(() => {
  cleanup();
  setPhone(false);
  resetRuntime();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const rule = { all: [{ left: { ind: "close" }, op: ">", right: { value: 1 } }] } as Screen["rule"];
const scr = (over: Partial<Screen>): Screen => ({
  id: 1, name: "Uptrend leaders", description: "d", rule, describe: "Close is above 1", is_preset: true,
  created_by: "preset", last_run_as_of: null, count: 0, ...over,
});
const res = (symbol: string, first_seen: string, v: number | null, score: number | null = null): ScreenResult => ({
  symbol, name: `${symbol} Ltd`, values: { Close: v, RSI: 50 }, first_seen, score, reasons: null,
});

test("ranText", () => {
  expect(ranText(null, "2026-11-09")).toBe("not run yet");
  expect(ranText("2026-11-09", "2026-11-09")).toBe("ran today");
  expect(ranText("2026-11-08", "2026-11-09")).toBe("ran yesterday");
  expect(ranText("2026-11-04", "2026-11-09")).toBe("ran 5 days ago");
});

test("list shows badge, count, ran text; duplicate only on presets", () => {
  const onDup = vi.fn();
  const onNew = vi.fn();
  render(
    <ScreenList
      screens={[scr({ count: 3, last_run_as_of: null }), scr({ id: 2, name: "Mine", is_preset: false, count: 1 })]}
      selectedId={1} onSelect={() => undefined} onNew={onNew} onDuplicate={onDup}
    />,
  );
  expect(screen.getByText("preset")).toBeTruthy();
  expect(screen.getByText(/3 matches · not run yet/)).toBeTruthy();
  expect(screen.getByText(/1 match ·/)).toBeTruthy();
  expect(screen.getAllByText("Duplicate")).toHaveLength(1);
  fireEvent.click(screen.getByText("Duplicate"));
  expect(onDup).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }));
  fireEvent.click(screen.getByText("+ New screen"));
  expect(onNew).toHaveBeenCalled();
});

test("NEW only for the latest run, and only when older rows exist", () => {
  expect([...newSymbols([res("A", "2026-11-01", 1), res("B", "2026-11-09", 2)])]).toEqual(["B"]);
  expect(newSymbols([res("A", "2026-11-09", 1), res("B", "2026-11-09", 2)]).size).toBe(0);
  expect(newSymbols([]).size).toBe(0);
});

test("sorting puts blanks last in both directions", () => {
  const rows = [res("A", "x", 3), res("B", "x", null), res("C", "x", 1)];
  expect(sortResults(rows, "v:Close", 1).map((r) => r.symbol)).toEqual(["C", "A", "B"]);
  expect(sortResults(rows, "v:Close", -1).map((r) => r.symbol)).toEqual(["A", "C", "B"]);
  expect(sortResults(rows, "symbol", -1).map((r) => r.symbol)).toEqual(["C", "B", "A"]);
});

test("results table: columns from values, links, NEW badge, score hidden while null, sortable, copy", async () => {
  const writeText = vi.fn(async () => undefined);
  vi.stubGlobal("navigator", { clipboard: { writeText } });
  render(
    <MemoryRouter>
      <ScreenResults results={[res("AAA", "2026-11-01", 5), res("BBB", "2026-11-09", 9)]} />
    </MemoryRouter>,
  );
  expect(screen.getByText("AAA").getAttribute("href")).toBe("/stock/AAA");
  expect(screen.getByRole("columnheader", { name: /Close/ })).toBeTruthy();
  expect(screen.getByText("NEW")).toBeTruthy();
  expect(screen.queryByRole("columnheader", { name: /Score/ })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: /Close/ }));
  fireEvent.click(screen.getByRole("button", { name: /Close/ })); // descending
  expect(within(screen.getAllByRole("row")[1]).getByText("BBB")).toBeTruthy();
  fireEvent.click(screen.getByText("Copy symbols"));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith("BBB\nAAA"));
  fireEvent.click(screen.getByText("Copy table"));
  await waitFor(() => expect(writeText).toHaveBeenCalledTimes(2));
  expect((writeText.mock.calls[1] as unknown as string[])[0]).toContain("Symbol\tName\tClose\tRSI\tFirst seen");
  cleanup();
  render(<MemoryRouter><ScreenResults results={[res("AAA", "x", 1, 77)]} /></MemoryRouter>);
  expect(screen.getByRole("columnheader", { name: /Score/ })).toBeTruthy();
});

// ---- the page ----

interface Api {
  screens: Screen[];
  results: Record<number, ScreenResult[]>;
  runStates: string[];
  calls: string[];
}
function installApi(a: Api) {
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    a.calls.push(`${method} ${url}`);
    const ok = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
    if (url === "/api/health") return ok({ ok: true, time: "x", version: "x", runtime: "vercel" });
    if (url === "/api/screens" && method === "GET") return ok(a.screens);
    if (url === "/api/screens" && method === "POST") {
      const b = JSON.parse(String(init?.body));
      const s = scr({ id: 9, name: b.name, is_preset: false, created_by: "user", rule: b.rule });
      a.screens = [...a.screens, s];
      a.results[9] = [];
      return ok(s);
    }
    const m = url.match(/^\/api\/screens\/(\d+)(\/\w+)?$/);
    if (m && m[2] === "/results") return ok(a.results[Number(m[1])] ?? []);
    if (m && m[2] === "/run") return ok({ run_id: 5 });
    if (m && method === "DELETE") {
      a.screens = a.screens.filter((s) => s.id !== Number(m[1]));
      return ok({ ok: true });
    }
    if (url === "/api/jobs/runs/5") {
      const status = a.runStates.shift() ?? "done";
      if (status === "done") a.results[1] = [res("NEWBIE", "2026-11-09", 1)];
      return ok({ id: 5, status, message: null });
    }
    if (url === "/api/indicators") return ok([]);
    if (url === "/api/fundamentals/fields") return ok([]);
    if (url === "/api/rules/ops") return ok([{ name: ">", words: "is above" }]);
    if (url === "/api/rules/describe") return ok({ text: "x" });
    return new Response("{}", { status: 404 });
  }));
}
let a: Api;
beforeEach(() => {
  a = {
    screens: [scr({}), scr({ id: 2, name: "Mine", is_preset: false, created_by: "user", count: 1 })],
    results: { 1: [res("OLD", "2026-11-01", 1)], 2: [res("MINE", "2026-11-01", 2)] },
    runStates: ["queued", "running", "done"],
    calls: [],
  };
  installApi(a);
});

function LocationProbe() {
  const l = useLocation();
  return <div data-testid="loc">{l.pathname + l.search}</div>;
}

const page = () => render(<MemoryRouter><Screener /></MemoryRouter>);

test("page loads the first screen with its description and results", async () => {
  page();
  expect(await screen.findByText("Close is above 1")).toBeTruthy();
  expect(await screen.findByText("OLD")).toBeTruthy();
  expect(screen.queryByText("Edit")).toBeNull(); // presets are duplicated, not edited
  expect(screen.queryByText("Delete")).toBeNull();
  expect(screen.getByText("Backtest this")).toBeTruthy();
});

test("Backtest this opens the backtest form for that screen without posting", async () => {
  render(
    <MemoryRouter initialEntries={["/screener"]}>
      <Routes>
        <Route path="/screener" element={<Screener />} />
        <Route path="/backtests/new" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
  await screen.findByText("OLD");
  fireEvent.click(screen.getByText("Backtest this"));
  expect((await screen.findByTestId("loc")).textContent).toBe("/backtests/new?screen=1");
  expect(a.calls.some((c) => c.startsWith("POST"))).toBe(false);
});

test("Run now shows the job status, then refreshes the results", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  page();
  await screen.findByText("OLD");
  fireEvent.click(screen.getByText("Run now"));
  expect(await screen.findByText("Waiting in the queue…")).toBeTruthy();
  await act(async () => { await vi.advanceTimersByTimeAsync(1600); });
  expect(await screen.findByText("Running…")).toBeTruthy();
  await act(async () => { await vi.advanceTimersByTimeAsync(1600); });
  expect(await screen.findByText("Finished.")).toBeTruthy();
  expect(await screen.findByText("NEWBIE")).toBeTruthy();
});

test("delete asks inline first, and only user screens can be deleted", async () => {
  page();
  fireEvent.click(await screen.findByRole("button", { name: /Mine/ }));
  await screen.findByText("MINE");
  fireEvent.click(screen.getByText("Delete"));
  expect(screen.getByText(/Delete "Mine"\?/)).toBeTruthy();
  expect(a.calls.some((c) => c.startsWith("DELETE"))).toBe(false);
  fireEvent.click(screen.getByText("Keep it"));
  expect(a.calls.some((c) => c.startsWith("DELETE"))).toBe(false);
  fireEvent.click(screen.getByText("Delete"));
  fireEvent.click(screen.getByText("Yes, delete"));
  await waitFor(() => expect(a.calls).toContain("DELETE /api/screens/2"));
  await waitFor(() => expect(screen.queryByRole("button", { name: /Mine/ })).toBeNull());
});

test("duplicating a preset opens the editor with a copy and saves it as a new screen", async () => {
  page();
  fireEvent.click(await screen.findByLabelText("Duplicate Uptrend leaders"));
  const name = (await screen.findByLabelText(/^Name/)) as HTMLInputElement;
  expect(name.value).toBe("Uptrend leaders (copy)");
  fireEvent.change(name, { target: { value: "My copy" } });
  fireEvent.click(screen.getByText("Save"));
  await waitFor(() => expect(a.calls).toContain("POST /api/screens"));
  expect(await screen.findByRole("heading", { name: "My copy" })).toBeTruthy();
});

test("saving without a name is refused in the editor", async () => {
  page();
  fireEvent.click(await screen.findByText("+ New screen"));
  fireEvent.click(await screen.findByText("Save"));
  expect(screen.getByRole("alert").textContent).toContain("name");
  expect(a.calls).not.toContain("POST /api/screens");
});

const previewRun = (status: string, ok = 0, message: string | null = null) => ({
  id: 9, job: "screen_preview", trigger: "manual", status, queued_at: "x", started_at: null, finished_at: null,
  duration_s: null, total: ok, done: ok, ok, skipped: 0, failed: 0, message, retry_of: null,
});

test("editor preview runs as a job, then shows the count and at most the first 50 rows", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const items = Array.from({ length: 60 }, (_, i) => ({
    key: `S${String(i).padStart(2, "0")}`, status: "ok", detail: JSON.stringify({ Close: i }), at: "x",
  }));
  const polls = [previewRun("queued"), previewRun("running"), previewRun("done", 60, "60 stocks match")];
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push(`${init?.method ?? "GET"} ${url}`);
    if (url === "/api/health") return new Response(JSON.stringify({ ok: true, runtime: "vercel" }), { status: 200 });
    if (url === "/api/screens/preview") return new Response(JSON.stringify({ run_id: 9 }), { status: 200 });
    if (url === "/api/jobs/runs/9") return new Response(JSON.stringify(polls.shift()), { status: 200 });
    if (url.startsWith("/api/jobs/runs/9/items")) return new Response(JSON.stringify(items), { status: 200 });
    if (url === "/api/rules/describe") return new Response(JSON.stringify({ text: "x" }), { status: 200 });
    return new Response("[]", { status: 200 });
  }));
  const { default: ScreenEditor } = await import("../components/screens/ScreenEditor");
  render(
    <ScreenEditor
      initial={{ name: "n", description: "", rule }}
      onSave={async () => undefined}
      onCancel={() => undefined}
      meta={{ catalogue: [], fields: [], ops: [{ name: ">", words: "is above" }] }}
      aboveBuilder={<p>slot</p>}
    />,
  );
  expect(screen.getByText("slot")).toBeTruthy();
  fireEvent.click(screen.getByText("Preview"));
  expect(await screen.findByText(/Waiting for the cloud worker/)).toBeTruthy();
  await act(() => vi.advanceTimersByTimeAsync(RUN_POLL_MS));
  expect(await screen.findByText(/Running in the cloud worker/)).toBeTruthy();
  await act(() => vi.advanceTimersByTimeAsync(RUN_POLL_MS));
  expect(await screen.findByText(/showing the first 50/)).toBeTruthy();
  expect(screen.getByText("60")).toBeTruthy();
  expect(screen.getAllByRole("row")).toHaveLength(51); // header + 50 rows
  expect(calls).toContain("GET /api/jobs/runs/9/items?status=ok&limit=1000");
  expect(screen.queryByText(/cloud worker/)).toBeNull();
});

test("editor preview shows why a failed preview job failed", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url === "/api/screens/preview") return new Response(JSON.stringify({ run_id: 9 }), { status: 200 });
    if (url === "/api/jobs/runs/9") {
      return new Response(JSON.stringify(previewRun("failed", 0, "RuleError: all[0]: no data")), { status: 200 });
    }
    return new Response("[]", { status: 200 });
  }));
  const { default: ScreenEditor } = await import("../components/screens/ScreenEditor");
  render(
    <ScreenEditor
      initial={{ name: "n", description: "", rule }}
      onSave={async () => undefined}
      onCancel={() => undefined}
      meta={{ catalogue: [], fields: [], ops: [{ name: ">", words: "is above" }] }}
    />,
  );
  fireEvent.click(screen.getByText("Preview"));
  expect((await screen.findByRole("alert")).textContent).toContain("RuleError: all[0]: no data");
});

// ---- Phone (N016) ----

test("phone: pick a screen from the select, run it, and see results as cards", async () => {
  setPhone(true);
  page();
  const pick = (await screen.findByLabelText("Screen")) as HTMLSelectElement;
  expect(screen.getByText("+ New screen")).toBeTruthy();
  fireEvent.change(pick, { target: { value: "2" } });
  await screen.findByText("MINE");
  const card = screen.getByText("MINE").closest("[data-testid=phone-card]") as HTMLElement;
  expect(card).toBeTruthy();
  expect(within(card).getByText("MINE Ltd")).toBeTruthy();
  fireEvent.click(screen.getByText("Run now"));
  await waitFor(() => expect(a.calls).toContain("POST /api/screens/2/run"));
});

test("phone: the editor is a full-screen sheet; add a condition and save sends the rule", async () => {
  setPhone(true);
  page();
  fireEvent.click(await screen.findByText("+ New screen"));
  const sheet = await screen.findByTestId("screen-sheet");
  fireEvent.change(within(sheet).getByLabelText(/^Name/), { target: { value: "Phone screen" } });
  await within(sheet).findByText("Add group");
  expect(within(sheet).getAllByTestId("condition-card")).toHaveLength(1);
  fireEvent.click(within(sheet).getByText("Add condition"));
  expect(within(sheet).getAllByTestId("condition-card")).toHaveLength(2);
  expect(within(sheet).getByText("Preview")).toBeTruthy();
  expect(within(sheet).queryByText("Backtest this")).toBeNull(); // not saved yet
  fireEvent.click(within(sheet).getByText("Save"));
  await waitFor(() => expect(a.calls).toContain("POST /api/screens"));
  const post = (fetch as unknown as { mock: { calls: [string, RequestInit?][] } }).mock.calls.find(
    (c) => c[0] === "/api/screens" && c[1]?.method === "POST",
  );
  const body = JSON.parse(String(post?.[1]?.body));
  expect(body.name).toBe("Phone screen");
  expect(body.rule.all).toHaveLength(2);
});
