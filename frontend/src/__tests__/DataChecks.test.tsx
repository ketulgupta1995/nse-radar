import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";

import { api } from "../api/client";

import type { DataHealth as Health, PriceCheck } from "../api/types";
import DataHealth from "../components/jobs/DataHealth";
import DataChecks, { explain } from "../components/jobs/DataChecks";
import { shortDay, weekdaysBehind } from "../lib/dates";

afterEach(cleanup);

const labels = { nse_bhav: "NSE bhavcopy", yfinance: "Yahoo" };
const base: PriceCheck = {
  id: 1, symbol: "TCS", date: "2026-01-02", kind: "mismatch", primary_source: "nse_bhav", other_source: "yfinance",
  detail: { suggested_factor: 0.5 }, status: "open",
};

test("explanations in plain words", () => {
  expect(explain(base, labels)).toBe(
    "NSE bhavcopy and Yahoo disagree by ×0.50 from this date: probably a split or bonus that wasn't listed.",
  );
  expect(explain({ ...base, kind: "unexplained_gap", detail: { change_pct: -42.3 } }, labels)).toBe(
    "Price jumped 42% in a day with no corporate action.",
  );
});

test("adjustment jump: label, explanation and Apply button", async () => {
  const jump: PriceCheck = {
    id: 5, symbol: "CGCL", date: "2010-12-24", kind: "adjustment_jump", primary_source: "nse_bhav", other_source: null,
    detail: { applied_factor: 0.5, open_move_pct: 90, close_move_pct: 88, suggested_factor: 0.95 }, status: "open",
  };
  expect(explain(jump, labels)).toBe(
    "Adjusted price moved +90% at the open on a split/bonus/demerger date: the factor ×0.50 looks wrong; ×0.95 would remove the jump.",
  );
  vi.spyOn(api, "get").mockImplementation(
    (p: string) => Promise.resolve(p.startsWith("/data/checks") ? [jump] : []) as never,
  );
  render(<MemoryRouter><DataChecks labels={labels} onChanged={() => {}} /></MemoryRouter>);
  expect(await screen.findByText("Odd jump on an adjustment date")).toBeTruthy();
  expect(screen.getByText(/the factor ×0.50 looks wrong/)).toBeTruthy();
  expect(screen.getByRole("button", { name: "Apply suggested factor" })).toBeTruthy();
});

test("date helpers", () => {
  expect(shortDay("2026-11-06")).toBe("6 Nov");
  expect(weekdaysBehind("2026-11-06", "2026-11-09")).toBe(1); // Fri -> Mon
  expect(weekdaysBehind("2026-11-04", "2026-11-09")).toBe(3);
  expect(weekdaysBehind("2026-11-09", "2026-11-09")).toBe(0);
});

const health: Health = {
  last_trading_date: "2026-11-06", symbols: 2700, universe: 501, checks_open: 2, unparsed_actions: 0,
  bars: { nse_bhav: { symbols: 1987, last_date: "2026-11-06" } },
  fundamentals: { merged: 0 }, quarters: {}, news: { announcements_7d: 3, news_7d: 9 },
};

test("health strip: amber only when more than 2 weekdays old", () => {
  const { rerender } = render(<MemoryRouter><DataHealth health={health} labels={labels} today="2026-11-09" /></MemoryRouter>);
  expect(screen.getByText("Prices up to 6 Nov").className).toBe("");
  expect(screen.getByText("NSE bhavcopy: 1,987 stocks, to 6 Nov")).toBeTruthy();
  expect(screen.getByText("Open data issues: 2").className).toBe("warn");
  rerender(<MemoryRouter><DataHealth health={health} labels={labels} today="2026-11-12" /></MemoryRouter>);
  expect(screen.getByText("Prices up to 6 Nov").className).toBe("warn");
});
