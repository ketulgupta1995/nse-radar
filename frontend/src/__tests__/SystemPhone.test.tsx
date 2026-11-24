import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { api } from "../api/client";
import type { Settings as S } from "../api/types";
import Jobs from "../pages/Jobs";
import Settings from "../pages/Settings";
import Sources from "../pages/Sources";
import { setPhone } from "./phone";

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  act(() => setPhone(true));
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  act(() => setPhone(false));
});

const sched = { kind: "interval", interval_min: 60, enabled: true, next_run_at: null, at_time: null, weekday: null, weekdays_only: false };
const job = { name: "prices", title: "Fetch prices", description: "d", group: "app", source_enabled: null, schedule: sched, last_run: null, running: null };
const settings = {
  capital_inr: 1, risk_per_trade_pct: 1, default_time_stop_weeks: 8, atr_stop_multiple: 2, signal_target_atr_multiple: 4,
  position_exit_sma: 100, trail_atr_multiple: 5, source_priority: {}, fundamentals_field_priority: {}, ai_provider: "x",
  ai_model: "m", ai_timeout_s: 1, score_weights: { rs: 30, trend: 25, fundamentals: 30, backtest: 15 }, rss_feeds: [],
  jobs_paused: false, last_visit_at: null, holdout_start: "2022-01-01",
  cost_model: { brokerage_pct: 0, brokerage_cap_inr: 0, stt_pct: 0, exchange_pct: 0, sebi_pct: 0, stamp_buy_pct: 0, gst_pct: 0, dp_charge_inr: 0, slippage_pct: 0 },
} as unknown as S;
const source = {
  name: "nse", label: "NSE Official", description: "d", homepage: "https://x", enabled: true, paused_reason: null,
  last_ok_at: null, last_error_at: null, last_error: null, capabilities: [], secrets: { API_KEY: false },
  stats: { ok_7d: 1, failed_7d: 0, not_found_7d: 0 },
};

function gets(cloud: object | null, extra: Record<string, unknown> = {}) {
  vi.spyOn(api, "get").mockImplementation((path: string) => {
    if (path === "/cloud/status") return cloud ? Promise.resolve(cloud) : Promise.reject(new Error("down"));
    if (path in extra) return Promise.resolve(extra[path]);
    if (path === "/settings") return Promise.resolve(settings);
    if (path === "/jobs") return Promise.resolve({ paused: false, jobs: [job] });
    if (path === "/sources") return Promise.resolve([source]);
    if (path === "/sources/priority") return Promise.resolve({ bars: ["nse"], capabilities: { bars: ["nse"] } });
    if (path === "/ai/status") return Promise.resolve({ available: true, detail: "ok", providers: [] });
    if (path === "/me") return Promise.resolve({ auth_required: true, logged_in: true });
    if (path === "/data/health") return Promise.resolve({
      last_trading_date: null, symbols: 0, universe: 0, checks_open: 0, unparsed_actions: 0, bars: {}, fundamentals: {}, quarters: {},
      news: { announcements_7d: 0, news_7d: 0 },
    });
    return Promise.resolve([]);
  });
}

const CLOUD_LINE = /Jobs run in the cloud worker/;

test("phone jobs show a card with Run now, and the cloud line only on vercel", async () => {
  gets({ runtime: "vercel" });
  render(<MemoryRouter><Jobs /></MemoryRouter>);
  expect(await screen.findByTestId("job-card")).toBeTruthy();
  expect(screen.getByText("Run now")).toBeTruthy();
  expect(screen.getByLabelText("Enable Fetch prices")).toBeTruthy();
  expect(await screen.findByText(CLOUD_LINE)).toBeTruthy();
  cleanup();
  gets({ runtime: "local" });
  render(<MemoryRouter><Jobs /></MemoryRouter>);
  await screen.findByTestId("job-card");
  expect(screen.queryByText(CLOUD_LINE)).toBeNull();
});

test("phone sources show a card with up/down buttons", async () => {
  gets({ runtime: "local" });
  render(<MemoryRouter><Sources /></MemoryRouter>);
  expect(await screen.findByText("NSE Official", { selector: "h3" })).toBeTruthy();
  expect(await screen.findByLabelText("Move NSE Official up in bars")).toBeTruthy();
});

test("Cloud section shows only on vercel, with counts and the missing-token warning", async () => {
  const ago = new Date(Date.now() - 3 * 60000).toISOString();
  gets({ runtime: "vercel", dispatch_configured: false, last_dispatch_at: null, queued: 2, running: 1, oldest_queued_at: ago });
  render(<MemoryRouter><Settings /></MemoryRouter>);
  expect(await screen.findByText("Cloud", { selector: "h3, h2, div" })).toBeTruthy();
  expect(screen.getByText("(waiting 3 min)")).toBeTruthy();
  expect(screen.getByText(/dispatch token is missing/)).toBeTruthy();
  expect(screen.getAllByText("Log out")).toHaveLength(1);
  cleanup();
  gets({ runtime: "vercel", dispatch_configured: true, queued: 0, running: 0 });
  render(<MemoryRouter><Settings /></MemoryRouter>);
  await screen.findByText("Cloud", { selector: "h3, h2, div" });
  expect(screen.queryByText(/dispatch token is missing/)).toBeNull();
  cleanup();
  gets({ runtime: "local" });
  render(<MemoryRouter><Settings /></MemoryRouter>);
  await waitFor(() => expect(screen.getByText("Money & risk")).toBeTruthy());
  expect(screen.queryByText("Cloud")).toBeNull();
});
