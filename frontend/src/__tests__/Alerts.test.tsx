import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import type { Alert } from "../api/types";
import AlertBadge, { notifyAlertsChanged } from "../components/AlertBadge";
import { relativeAgo } from "../lib/dates";
import Alerts from "../pages/Alerts";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const mk = (id: number, over: Partial<Alert> = {}): Alert => ({
  id, kind: "stop_hit", symbol: "TCS", message: `Alert ${id}`, link: "/positions", severity: "critical",
  dedupe_key: `k${id}`, created_at: new Date(Date.now() - 5 * 60_000).toISOString(), seen_at: null, ...over,
});

interface State {
  alerts: Alert[];
  calls: { method: string; url: string; body?: unknown }[];
}
let st: State;
function install() {
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    st.calls.push({ method, url, body });
    const ok = (b: unknown) => new Response(JSON.stringify(b), { status: 200 });
    if (url === "/api/alerts/kinds") {
      return ok([{ kind: "stop_hit", label: "Stop price reached" }, { kind: "time_stop", label: "Time stop reached" }]);
    }
    if (url === "/api/alerts/count") return ok({ unseen: st.alerts.filter((a) => !a.seen_at).length });
    if (url === "/api/alerts/seen") {
      const ids: number[] | undefined = body?.ids;
      let n = 0;
      st.alerts = st.alerts.map((a) => (!a.seen_at && (!ids || ids.includes(a.id)) ? (n++, { ...a, seen_at: "now" }) : a));
      return ok({ marked: n });
    }
    if (url.startsWith("/api/alerts?")) {
      const q = new URL(url, "http://x").searchParams;
      return ok(st.alerts.filter((a) => (!q.get("unseen") || !a.seen_at) && (!q.get("kind") || a.kind === q.get("kind"))));
    }
    return new Response("{}", { status: 404 });
  }));
}
beforeEach(() => {
  st = {
    alerts: [mk(1), mk(2, { kind: "time_stop", severity: "warn", link: "/stock/AAA" }), mk(3, { severity: "info", seen_at: "x", link: null })],
    calls: [],
  };
  install();
});

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>;
}
const page = () =>
  render(
    <MemoryRouter initialEntries={["/alerts"]}>
      <AlertBadge />
      <Routes>
        <Route path="/alerts" element={<Alerts />} />
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>,
  );

test("relative time", () => {
  const now = new Date("2026-11-09T12:00:00Z");
  expect(relativeAgo("2026-11-09T11:55:00Z", now)).toBe("5 min ago");
  expect(relativeAgo("2026-11-09T09:00:00Z", now)).toBe("3 hours ago");
  expect(relativeAgo("2026-11-06T12:00:00Z", now)).toBe("3 days ago");
  expect(relativeAgo("2026-11-09T12:00:00Z", now)).toBe("just now");
});

test("shows unseen alerts with severity icons, message, kind and time; hides seen ones", async () => {
  page();
  expect(await screen.findByText("Alert 1")).toBeTruthy();
  expect(screen.getByText("Alert 2")).toBeTruthy();
  expect(screen.queryByText("Alert 3")).toBeNull();
  expect(screen.getByRole("img", { name: "Act now" })).toBeTruthy();
  expect(screen.getByRole("img", { name: "Needs a look" })).toBeTruthy();
  expect(screen.getByText(/Stop price reached · 5 min ago/)).toBeTruthy();
});

test("All shows seen alerts too, and the type filter narrows the list", async () => {
  page();
  await screen.findByText("Alert 1");
  fireEvent.click(screen.getByText("All"));
  expect(await screen.findByText("Alert 3")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Type"), { target: { value: "time_stop" } });
  await waitFor(() => expect(screen.queryByText("Alert 1")).toBeNull());
  expect(screen.getByText("Alert 2")).toBeTruthy();
  expect(st.calls.some((c) => c.url.includes("kind=time_stop"))).toBe(true);
});

test("clicking an alert marks it seen and goes to its link", async () => {
  page();
  fireEvent.click(await screen.findByText("Alert 2"));
  await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/stock/AAA"));
  expect(st.calls.find((c) => c.url === "/api/alerts/seen")?.body).toEqual({ ids: [2] });
  expect(st.alerts.find((a) => a.id === 2)?.seen_at).toBeTruthy();
});

test("Mark all seen empties the unseen list and refreshes the badge", async () => {
  page();
  await screen.findByText("Alert 1");
  await waitFor(() => expect(screen.getByLabelText("2 new alerts")).toBeTruthy());
  fireEvent.click(screen.getByText("Mark all seen"));
  expect(await screen.findByText(/No unseen alerts/)).toBeTruthy();
  await waitFor(() => expect(screen.getByLabelText("No new alerts")).toBeTruthy());
});

test("the badge polls every 60 seconds and updates on demand", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  render(<MemoryRouter><AlertBadge /></MemoryRouter>);
  await waitFor(() => expect(screen.getByLabelText("2 new alerts")).toBeTruthy());
  const counts = () => st.calls.filter((c) => c.url === "/api/alerts/count").length;
  expect(counts()).toBe(1);
  st.alerts.push(mk(9));
  await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
  await waitFor(() => expect(screen.getByLabelText("3 new alerts")).toBeTruthy());
  expect(counts()).toBe(2);
  st.alerts.push(mk(10));
  act(() => notifyAlertsChanged());
  await waitFor(() => expect(screen.getByLabelText("4 new alerts")).toBeTruthy());
});

test("badge says there is nothing new when the count is zero", async () => {
  st.alerts = [];
  render(<MemoryRouter><AlertBadge /></MemoryRouter>);
  expect(await screen.findByLabelText("No new alerts")).toBeTruthy();
});
