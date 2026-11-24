import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { ApiError, api } from "../api/client";
import type { ChecklistQuestions, Idea, IdeasPage, JournalStats, Position, SignalsSummary, Suggest } from "../api/types";
import EntryChecklist from "../components/checklist/EntryChecklist";
import Journal from "../pages/Journal";
import Portfolio from "../pages/Portfolio";
import TrackRecord from "../pages/TrackRecord";
import { setPhone } from "./phone";

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  act(() => setPhone(true));
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const wrap = (ui: React.ReactNode) => render(<MemoryRouter>{ui}</MemoryRouter>);

const pos = (over: Partial<Position> = {}): Position =>
  ({
    id: 1, symbol: "AAA", qty: 10, entry_date: "2025-01-01", entry_price: 100, last_close: 110, stop: 90, target: 130,
    pnl_inr: 100, pnl_pct: 10, r_multiple: 1, days_held: 5, days_to_time_stop: 20, status: "open",
    exit_date: null, exit_price: null, exit_reason: null, ...over,
  }) as Position;

test("Portfolio phone: summary card sits above the position cards", async () => {
  vi.spyOn(api, "get").mockResolvedValue([pos()] as never);
  wrap(<Portfolio />);
  const card = await screen.findByTestId("phone-card");
  const summary = screen.getByLabelText("Portfolio summary");
  expect(summary.compareDocumentPosition(card) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.getByText("Current value")).toBeTruthy();
  expect(screen.getByText("Unrealised profit / loss")).toBeTruthy();
  expect(card.textContent).toContain("AAA");
  expect(card.textContent).toContain("10 ×");
});

test("add-position sheet is full screen with numeric input and posts the right body", async () => {
  const questions = {
    entry: [
      { id: "thesis", label: "Why will this go up?", type: "text", required: true },
      { id: "wrong_if", label: "What would prove me wrong?", type: "text", required: true },
      { id: "entry_price", label: "Entry price", type: "number", required: true },
      { id: "stop", label: "Stop-loss price", type: "number", required: true },
      { id: "target", label: "Target price", type: "number", required: true },
      { id: "time_stop_weeks", label: "Weeks", type: "number", required: true },
      { id: "emotion", label: "How am I feeling?", type: "choice", required: true, choices: ["calm", "FOMO"] },
    ],
    exit: [],
  } as unknown as ChecklistQuestions;
  const suggest: Suggest = {
    last_close: 100, atr14: 4, suggested_stop: 92, suggested_target: 116, risk_per_share: 8, qty: 625,
    capital: 500000, risk_pct: 1, rr: 2,
  };
  vi.spyOn(api, "get").mockImplementation((path: string) => {
    if (path.startsWith("/positions/checklist")) return Promise.resolve(questions);
    if (path.startsWith("/positions/suggest")) return Promise.resolve(suggest);
    return Promise.reject(new ApiError(404, "no"));
  });
  const post = vi.spyOn(api, "post").mockResolvedValue(pos() as never);
  const { container } = render(<EntryChecklist symbol="AAA" onClose={() => undefined} onSaved={() => undefined} />);
  await waitFor(() => expect(screen.getByText(/Why will this go up/)).toBeTruthy());
  expect(screen.getByRole("dialog").getAttribute("data-sheet")).toBe("full");
  const boxes = screen.getAllByRole("textbox");
  fireEvent.change(boxes[0], { target: { value: "growth" } });
  fireEvent.change(boxes[1], { target: { value: "below 90" } });
  fireEvent.click(screen.getByText("Next"));
  await waitFor(() => expect(screen.getByText(/Quantity 625 shares/)).toBeTruthy());
  const numeric = container.ownerDocument.querySelectorAll('input[type="number"]');
  expect(numeric.length).toBeGreaterThan(0);
  numeric.forEach((n) => expect(n.getAttribute("inputmode")).toBeTruthy());
  fireEvent.click(screen.getByText("Next"));
  await waitFor(() => expect(screen.getByText("How am I feeling?")).toBeTruthy());
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "calm" } });
  fireEvent.click(screen.getByText("Next"));
  await waitFor(() => expect(screen.getByText("Save position")).toBeTruthy());
  fireEvent.change(container.ownerDocument.querySelector('input[type="date"]') as HTMLInputElement, {
    target: { value: "2026-11-11" },
  });
  fireEvent.click(screen.getByText("Save position"));
  await waitFor(() => expect(post).toHaveBeenCalled());
  const [path, body] = post.mock.calls[0] as [string, Record<string, unknown>];
  expect(path).toBe("/positions");
  expect(body).toMatchObject({ symbol: "AAA", qty: 625, entry_date: "2026-11-11" });
});

test("Journal phone: closed trades render as cards, newest first", async () => {
  const stats: JournalStats = {
    closed: 2, win_rate: 50, avg_r: 0.5, avg_win_pct: 10, avg_loss_pct: -5, thesis_right_pct: 50,
    by_exit_reason: { target: { n: 1, win_rate: 100, avg_r: 2 } }, by_emotion: {},
  };
  const t = (id: number, exit: string) => pos({ id, symbol: `S${id}`, status: "closed", exit_date: exit, exit_reason: "target" });
  vi.spyOn(api, "get").mockImplementation((p: string) =>
    Promise.resolve(p === "/journal/stats" ? stats : [t(1, "2025-03-01"), t(2, "2026-02-01")]),
  );
  wrap(<Journal />);
  await waitFor(() => expect(screen.getByText("S2")).toBeTruthy());
  expect(screen.getAllByText(/^S\d$/).map((e) => e.textContent)).toEqual(["S2", "S1"]);
  expect(screen.getAllByTestId("phone-card").length).toBeGreaterThan(0);
});

test("Track record phone: metrics are cards, ideas are cards, timeline opens on tap", async () => {
  const summary: SignalsSummary = {
    groups: [
      { key: "screen:1", label: "Momentum", kind: "screen", n_closed: 5, n_open: 2, n_pending: 0, hit_rate_pct: 60,
        avg_return_pct: 3.2, avg_r: 1.4, avg_excess_pct: 1.1, avg_days: 12, enough: true },
    ],
    coverage: { first_day: "2026-01-01", last_day: "2026-02-01", days_logged: 20, trading_days: 22 },
    min_closed: 30, n_signals: 9, n_ideas: 1,
  };
  const idea = {
    id: 1, symbol: "TCS", name: "Tata", first_as_of: "2026-01-05", last_as_of: "2026-01-07", score: 74, reasons: [],
    planned_entry: 100, planned_stop: 95, planned_target: 110, current_price: 102,
    seen: [{ signal_id: 1, as_of: "2026-01-05", source: "shortlist", screen_id: 0, screen_name: null, rank: 2, score: 74 }],
    outcome: { status: "open", entry_date: "2026-01-06", entry_fill: 100, gap_pct: 0, exit_date: null, exit_fill: null,
      exit_reason: null, days_held: 3, return_pct: 2.5, r_multiple: 0.6, mfe_r: 1.2, mae_r: -0.3, excess_pct: null },
  } as Idea;
  vi.spyOn(api, "get").mockImplementation((path: string) => {
    if (path === "/signals/summary") return Promise.resolve(summary);
    const page: IdeasPage = { total: 1, counts: { open: 1, pending: 0, closed: 0, no_data: 0 }, rows: [idea] };
    return Promise.resolve(page);
  });
  wrap(<TrackRecord />);
  await waitFor(() => expect(screen.getByTestId("group-block")).toBeTruthy());
  expect(screen.getByText("Win rate")).toBeTruthy();
  expect(screen.getByText("+1.4R")).toBeTruthy();
  const card = await screen.findByTestId("phone-card");
  expect(card.textContent).toContain("Return");
  expect(card.textContent).toContain("+2.5%");
  expect(screen.queryByText(/Picked 1 time/)).toBeNull();
  fireEvent.click(card);
  await waitFor(() => expect(screen.getByText(/Picked 1 time/)).toBeTruthy());
});
