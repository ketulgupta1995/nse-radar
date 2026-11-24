import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { api } from "../api/client";
import type { Position } from "../api/types";
import { toast } from "../components/ui/toaster";
import Alerts from "../pages/Alerts";
import Journal from "../pages/Journal";
import Portfolio from "../pages/Portfolio";

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const wrap = (ui: React.ReactNode) => render(<MemoryRouter>{ui}</MemoryRouter>);

const pos = (over: Partial<Position> = {}): Position =>
  ({
    id: 1, symbol: "AAA", qty: 10, entry_price: 100, last_close: 110, stop: 90, target: 130, pnl_inr: 100, pnl_pct: 10,
    r_multiple: 1, days_held: 5, days_to_time_stop: 20, ...over,
  }) as Position;

test("Portfolio shows the empty state with no open positions", async () => {
  vi.spyOn(api, "get").mockResolvedValue([] as never);
  wrap(<Portfolio />);
  expect(await screen.findByText("No open positions.")).toBeTruthy();
});

test("Portfolio lists positions, and saving a stop/target shows a toast", async () => {
  vi.spyOn(api, "get").mockResolvedValue([pos()] as never);
  vi.spyOn(api, "put").mockResolvedValue(pos({ stop: 95 }) as never);
  const ok = vi.spyOn(toast, "success").mockReturnValue(1);
  wrap(<Portfolio />);
  expect(await screen.findByText("AAA")).toBeTruthy();
  expect(screen.getByText("Capital invested")).toBeTruthy();
  fireEvent.click(screen.getByText("Edit stop/target"));
  fireEvent.change(screen.getByLabelText("Stop"), { target: { value: "95" } });
  fireEvent.click(screen.getByText("Save"));
  await waitFor(() => expect(ok).toHaveBeenCalledWith("Updated stop and target for AAA."));
});

test("Journal shows the empty state with no closed trades", async () => {
  vi.spyOn(api, "get").mockImplementation(async (p: string) =>
    (p.startsWith("/journal/stats") ? { closed: 0, by_exit_reason: {}, by_emotion: {} } : []) as never,
  );
  wrap(<Journal />);
  expect(await screen.findByText("No closed trades yet.")).toBeTruthy();
});

test("Alerts: marking all seen shows a toast", async () => {
  vi.spyOn(api, "get").mockImplementation(async (p: string) => (p.startsWith("/alerts/kinds") ? [] : []) as never);
  vi.spyOn(api, "post").mockResolvedValue({} as never);
  const ok = vi.spyOn(toast, "success").mockReturnValue(1);
  wrap(<Alerts />);
  expect(await screen.findByText(/No unseen alerts/)).toBeTruthy();
  fireEvent.click(screen.getByText("Mark all seen"));
  await waitFor(() => expect(ok).toHaveBeenCalledWith("All alerts marked as seen."));
});
