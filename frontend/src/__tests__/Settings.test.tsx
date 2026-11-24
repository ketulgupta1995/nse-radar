import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";

import { ApiError, api } from "../api/client";
import type { Settings as S } from "../api/types";
import Settings from "../pages/Settings";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const settings: S = {
  capital_inr: 500000, risk_per_trade_pct: 1, default_time_stop_weeks: 8, atr_stop_multiple: 2, signal_target_atr_multiple: 4,
  position_exit_sma: 100, trail_atr_multiple: 5,
  source_priority: {}, fundamentals_field_priority: {}, ai_provider: "claude_cli", ai_model: "sonnet",
  ai_timeout_s: 240, score_weights: { rs: 30, trend: 25, fundamentals: 30, backtest: 15 }, rss_feeds: [],
  jobs_paused: false, last_visit_at: null, holdout_start: "2022-01-01",
  cost_model: { brokerage_pct: 0.03, brokerage_cap_inr: 20, stt_pct: 0.1, exchange_pct: 0.003, sebi_pct: 0.0001,
    stamp_buy_pct: 0.015, gst_pct: 18, dp_charge_inr: 15.93, slippage_pct: 0.1 },
};

test("shows normalised weights and the server's validation message", async () => {
  vi.spyOn(api, "get").mockImplementation((path: string) =>
    path === "/settings" ? Promise.resolve(settings) : Promise.reject(new ApiError(404, "nope")),
  );
  const put = vi.spyOn(api, "put").mockRejectedValue(new ApiError(400, "risk_per_trade_pct: too big"));
  render(<MemoryRouter><Settings /></MemoryRouter>);
  await waitFor(() => expect(screen.getByText("Money & risk")).toBeTruthy());
  expect(screen.getByText("25%")).toBeTruthy(); // 25 of 100
  await waitFor(() => expect(screen.getByText("AI is not set up yet.")).toBeTruthy());
  fireEvent.click(screen.getAllByText("Save")[0]);
  await waitFor(() => expect(screen.getByText("risk_per_trade_pct: too big")).toBeTruthy());
  expect(put.mock.calls[0][1]).toHaveProperty("capital_inr", 500000);
});

test("test period start renders and saves", async () => {
  vi.spyOn(api, "get").mockImplementation((path: string) =>
    path === "/settings" ? Promise.resolve(settings) : Promise.reject(new ApiError(404, "nope")),
  );
  const put = vi.spyOn(api, "put").mockResolvedValue(settings);
  render(<MemoryRouter><Settings /></MemoryRouter>);
  await waitFor(() => expect(screen.getByText("Backtest periods")).toBeTruthy());
  const input = screen.getByText("Test period starts").closest("label")?.querySelector("input") as HTMLInputElement;
  expect(input.value).toBe("2022-01-01");
  fireEvent.change(input, { target: { value: "2021-06-01" } });
  const card = input.closest(".settings-section") as HTMLElement;
  fireEvent.click(Array.from(card.querySelectorAll("button")).find((b) => b.textContent === "Save") as HTMLButtonElement);
  await waitFor(() => expect(put).toHaveBeenCalled());
  expect(put.mock.calls[0][1]).toEqual({ holdout_start: "2021-06-01" });
});

test("trend-exit inputs render and save", async () => {
  vi.spyOn(api, "get").mockImplementation((path: string) =>
    path === "/settings" ? Promise.resolve(settings) : Promise.reject(new ApiError(404, "nope")),
  );
  const put = vi.spyOn(api, "put").mockResolvedValue(settings);
  render(<MemoryRouter><Settings /></MemoryRouter>);
  await waitFor(() => expect(screen.getByText("Money & risk")).toBeTruthy());
  // the Explain button is the label's first labelable child, so go to the input directly
  const inputIn = (text: RegExp) =>
    screen.getByText(text).closest("label")?.querySelector("input") as HTMLInputElement;
  const sma = inputIn(/Trend-exit average/);
  const atr = inputIn(/Trailing stop \(ATRs\)/);
  expect(sma.value).toBe("100");
  expect(atr.value).toBe("5");
  fireEvent.change(sma, { target: { value: "50" } });
  fireEvent.change(atr, { target: { value: "0" } });
  fireEvent.click(screen.getAllByText("Save")[0]);
  await waitFor(() => expect(put).toHaveBeenCalled());
  expect(put.mock.calls[0][1]).toMatchObject({ position_exit_sma: 50, trail_atr_multiple: 0 });
});

test("log out button shows only when the password gate is on", async () => {
  const me = { auth_required: false, logged_in: true };
  vi.spyOn(api, "get").mockImplementation((path: string) =>
    path === "/settings" ? Promise.resolve(settings) : path === "/me" ? Promise.resolve(me) : Promise.reject(new ApiError(404, "nope")),
  );
  render(<MemoryRouter><Settings /></MemoryRouter>);
  await waitFor(() => expect(screen.getByText("Money & risk")).toBeTruthy());
  expect(screen.queryByText("Log out")).toBeNull();
  cleanup();
  me.auth_required = true;
  render(<MemoryRouter><Settings /></MemoryRouter>);
  await waitFor(() => expect(screen.getByText("Log out")).toBeTruthy());
});

test("on Vercel 'Back up now' says backups run in the cloud worker (409)", async () => {
  vi.spyOn(api, "get").mockImplementation((path: string) =>
    path === "/settings" ? Promise.resolve(settings) : Promise.reject(new ApiError(404, "nope")),
  );
  vi.spyOn(api, "post").mockRejectedValue(new ApiError(409, "Backups run weekly in the cloud worker"));
  render(<MemoryRouter><Settings /></MemoryRouter>);
  fireEvent.click(await screen.findByText("Back up now"));
  expect((await screen.findByRole("status")).textContent).toBe("Backups run weekly in the cloud worker");
});
