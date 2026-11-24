import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";

import { api } from "../api/client";
import type { Idea, IdeasPage, SignalsSummary } from "../api/types";
import TrackRecord from "./TrackRecord";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

const summary: SignalsSummary = {
  groups: [
    { key: "screen:1", label: "Momentum", kind: "screen", n_closed: 5, n_open: 2, n_pending: 0, hit_rate_pct: 60,
      avg_return_pct: 3.2, avg_r: 1.4, avg_excess_pct: 1.1, avg_days: 12, enough: false },
  ],
  coverage: { first_day: "2026-01-01", last_day: "2026-02-01", days_logged: 20, trading_days: 22 },
  min_closed: 30,
  n_signals: 904,
  n_ideas: 169,
};

const outcome = {
  status: "open", entry_date: "2026-01-06", entry_fill: 100, gap_pct: 0, exit_date: null, exit_fill: null,
  exit_reason: null, days_held: 3, return_pct: 2.5, r_multiple: 0.6, mfe_r: 1.2, mae_r: -0.3, excess_pct: null,
};

const idea: Idea = {
  id: 1, symbol: "TCS", name: "Tata Consultancy", first_as_of: "2026-01-05", last_as_of: "2026-01-07", score: 74,
  reasons: ["Strong trend"], planned_entry: 100, planned_stop: 95, planned_target: 110, current_price: 102.5,
  seen: [
    { signal_id: 1, as_of: "2026-01-05", source: "screen", screen_id: 1, screen_name: "Momentum", rank: null, score: 70 },
    { signal_id: 2, as_of: "2026-01-06", source: "screen", screen_id: 2, screen_name: "Value", rank: null, score: 74 },
    { signal_id: 3, as_of: "2026-01-07", source: "shortlist", screen_id: 0, screen_name: null, rank: 2, score: 74 },
  ],
  outcome,
};

const closedIdea: Idea = {
  ...idea, id: 9, symbol: "INFY", name: "Infosys", seen: [idea.seen[0]],
  outcome: { ...outcome, status: "closed", exit_date: "2026-01-20", exit_reason: "Hit target", return_pct: 8 },
};

function mock(rows: Idea[], sum: SignalsSummary = summary) {
  return vi.spyOn(api, "get").mockImplementation((path: string) => {
    if (path === "/signals/summary") return Promise.resolve(sum);
    const page: IdeasPage = { total: rows.length, counts: { open: 4, pending: 2, closed: 7, no_data: 0 }, rows };
    if (path.includes("status=closed")) return Promise.resolve({ ...page, rows: [closedIdea] });
    return Promise.resolve(page);
  });
}

const view = () => render(<MemoryRouter><TrackRecord /></MemoryRouter>);
const ideaCalls = (spy: ReturnType<typeof mock>) =>
  spy.mock.calls.map((c) => String(c[0])).filter((p) => p.startsWith("/signals/ideas"));

test("summary rows, too-early badge and grouping line", async () => {
  mock([idea]);
  view();
  await waitFor(() => expect(screen.getByText("too early")).toBeTruthy());
  expect(screen.getByText("+1.4R")).toBeTruthy();
  expect(screen.getByText(/20 of 22 trading days/)).toBeTruthy();
  expect(screen.getByText(/904 loggings grouped into 169 ideas/)).toBeTruthy();
});

test("empty state", async () => {
  mock([], { ...summary, n_signals: 0, n_ideas: 0 });
  view();
  await waitFor(() => expect(screen.getByText(/Nothing logged yet/)).toBeTruthy());
});

test("default load asks for open ideas in the last 90 days and shows tab counts", async () => {
  const spy = mock([idea]);
  view();
  await waitFor(() => expect(screen.getAllByText("TCS").length).toBeGreaterThan(0));
  const first = ideaCalls(spy)[0];
  expect(first).toMatch(/^\/signals\/ideas\?status=open&since=\d{4}-\d{2}-\d{2}&limit=50&offset=0$/);
  const tabs = screen.getAllByRole("tab");
  expect(tabs.map((t) => t.textContent)).toEqual(["Open4", "Pending entry2", "Closed7", "All13"]);
  expect(screen.getByText("+2 more days")).toBeTruthy();
});

test("closed tab shows the Ended column and refetches", async () => {
  const spy = mock([idea]);
  view();
  await waitFor(() => expect(screen.getAllByText("TCS").length).toBeGreaterThan(0));
  fireEvent.click(screen.getByRole("tab", { name: /Closed/ }));
  await waitFor(() => expect(screen.getByText("Ended")).toBeTruthy());
  expect(ideaCalls(spy).some((p) => p.includes("status=closed"))).toBe(true);
  expect(screen.getAllByText(/Hit target/).length).toBeGreaterThan(0);
});

test("search box refetches with q after the debounce", async () => {
  const spy = mock([idea]);
  view();
  await waitFor(() => expect(screen.getAllByText("TCS").length).toBeGreaterThan(0));
  vi.useFakeTimers();
  fireEvent.change(screen.getByLabelText("Find a stock"), { target: { value: "tcs" } });
  await act(async () => {
    vi.advanceTimersByTime(300);
  });
  vi.useRealTimers();
  await waitFor(() => expect(ideaCalls(spy).some((p) => p.includes("q=tcs"))).toBe(true));
});

test("selected idea shows its timeline and best/worst points", async () => {
  mock([idea]);
  view();
  await waitFor(() => expect(screen.getByText(/Picked 3 times/)).toBeTruthy());
  expect(screen.getByText("graded from here")).toBeTruthy();
  expect(screen.getByText("Best point")).toBeTruthy();
  expect(screen.getByText("+1.2R")).toBeTruthy();
  expect(screen.getByText("-0.3R")).toBeTruthy();
  fireEvent.keyDown(document, { key: "Escape" });
  await waitFor(() => expect(screen.getByText(/Select an idea/)).toBeTruthy());
});
