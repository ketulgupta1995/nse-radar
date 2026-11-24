import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";

import { api } from "../api/client";
import type { JournalStats, Position } from "../api/types";
import Journal, { insights } from "../pages/Journal";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const pos = (id: number, exit: string): Position =>
  ({ id, symbol: `S${id}`, qty: 1, entry_date: "2025-01-01", entry_price: 100, stop: 95, target: 110, time_stop_date: null,
     status: "closed", exit_date: exit, exit_price: 110, exit_reason: "target", last_close: 110, pnl_inr: 10, pnl_pct: 10,
     r_multiple: 2, to_stop_pct: null, to_target_pct: null, days_held: 5, days_to_time_stop: null }) as Position;

const stats: JournalStats = {
  closed: 3, win_rate: 33.3, avg_r: 0.5, avg_win_pct: 10, avg_loss_pct: -5, thesis_right_pct: 50,
  by_exit_reason: { target: { n: 1, win_rate: 100, avg_r: 2 } },
  by_emotion: { calm: { n: 1, win_rate: 100, avg_r: 2 }, FOMO: { n: 2, win_rate: 0, avg_r: -1 } },
};

test("insight lines skip calm", () => {
  expect(insights(stats.by_emotion)).toEqual(["Trades entered with FOMO: 2, win rate 0%"]);
});

test("newest first, and the year filter", async () => {
  vi.spyOn(api, "get").mockImplementation((path: string) =>
    Promise.resolve(path === "/journal/stats" ? stats : [pos(1, "2025-03-01"), pos(2, "2026-02-01"), pos(3, "2026-05-01")]),
  );
  render(<MemoryRouter><Journal /></MemoryRouter>);
  await waitFor(() => expect(screen.getByText("S3")).toBeTruthy());
  const order = screen.getAllByText(/^S\d$/).map((e) => e.textContent);
  expect(order).toEqual(["S3", "S2", "S1"]);
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "2025" } });
  expect(screen.queryByText("S3")).toBeNull();
  expect(screen.getByText("S1")).toBeTruthy();
});
