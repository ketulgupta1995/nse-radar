import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { api } from "../api/client";
import type { Backtest, ExitDefInfo, MetricSet, Screen } from "../api/types";
import BacktestForm from "../components/backtests/BacktestForm";
import Backtests from "../pages/Backtests";
import { setPhone } from "./phone";

vi.mock("../components/backtests/EquityChart", () => ({
  default: () => <div data-testid="chart" />,
  oosMarkerTime: () => null,
}));

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  act(() => setPhone(true));
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  act(() => setPhone(false));
});

const ms = (over: Partial<MetricSet> = {}): MetricSet => ({
  cagr: 12, bench_cagr: 10, excess: 2, max_drawdown: -20, volatility: 15, trades: 40, win_rate: 55, avg_win: 8,
  avg_loss: -4, profit_factor: 1.8, avg_days: 20, exposure: 60, best: null, worst: null, ...over,
});
const exits: ExitDefInfo[] = [];
const rule = { all: [{ left: { ind: "close" }, op: ">", right: { value: 1 } }] } as Screen["rule"];
const screens = [{ id: 3, name: "Leaders", rule }] as unknown as Screen[];

function formGets(runtime: string | null) {
  vi.spyOn(api, "get").mockImplementation((path: string) => {
    if (path === "/cloud/status") return runtime ? Promise.resolve({ runtime }) : Promise.reject(new Error("down"));
    if (path === "/screens") return Promise.resolve(screens);
    if (path === "/settings") return Promise.resolve({ holdout_start: "2022-01-01", capital_inr: 500000 });
    if (path === "/backtests/exits") return Promise.resolve(exits);
    if (path === "/indicators" || path === "/fundamentals/fields" || path === "/rules/ops") return Promise.resolve([]);
    return Promise.reject(new Error(`unexpected ${path}`));
  });
}

const CLOUD_LINE = /Backtests run in the cloud worker/;

test("phone form shows the cloud line when the runtime is vercel", async () => {
  formGets("vercel");
  render(<MemoryRouter><BacktestForm onStarted={() => undefined} onCancel={() => undefined} /></MemoryRouter>);
  expect(await screen.findByText(CLOUD_LINE)).toBeTruthy();
});

test("phone form hides the cloud line in local mode and when the status call fails", async () => {
  formGets("local");
  const { unmount } = render(<MemoryRouter><BacktestForm onStarted={() => undefined} onCancel={() => undefined} /></MemoryRouter>);
  await screen.findByText("Leaders");
  expect(screen.queryByText(CLOUD_LINE)).toBeNull();
  unmount();
  formGets(null);
  render(<MemoryRouter><BacktestForm onStarted={() => undefined} onCancel={() => undefined} /></MemoryRouter>);
  await screen.findByText("Leaders");
  expect(screen.queryByText(CLOUD_LINE)).toBeNull();
});

test("phone list shows cards, with the cloud wait text on a queued run", async () => {
  vi.spyOn(api, "get").mockImplementation((path: string) => {
    if (path === "/cloud/status") return Promise.resolve({ runtime: "vercel" });
    return Promise.resolve([
      { id: 1, name: "Leaders", status: "done", kind: "explore", parent_id: null, created_at: "2026-11-09T10:00:00", finished_at: null,
        metrics: { is: { cagr: 12, excess: 2, max_drawdown: -20, trades: 40 }, oos: null } },
      { id: 2, name: "Queued one", status: "queued", kind: "final", parent_id: 1, created_at: "2026-11-09T10:00:00", finished_at: null,
        metrics: null },
    ]);
  });
  render(<MemoryRouter initialEntries={["/backtests"]}><Routes><Route path="/backtests" element={<Backtests />} /></Routes></MemoryRouter>);
  await screen.findByText("Leaders");
  expect(screen.getAllByTestId("phone-card")).toHaveLength(2);
  expect(screen.getAllByText("Worst fall").length).toBeGreaterThan(0);
  expect(await screen.findByText("Waiting for the cloud worker (usually 1–2 min)")).toBeTruthy();
});

test("phone detail puts the metrics in a 2-column grid and keeps the warnings box", async () => {
  const bt = {
    id: 6, name: "Leaders", status: "done", kind: "explore", parent_id: null, run_id: 1, explore_runs: 1, attempt: null,
    created_at: "2026-11-09T10:00:00", finished_at: "x", warnings: [], equity: [{ t: "2020-01-01", v: 1 }], trades: [],
    metrics: { is: ms(), oos_start: "2020-01-01" }, config: { universe: "liquid500", oos_start: "2020-01-01", end: null },
  } as unknown as Backtest;
  vi.spyOn(api, "get").mockImplementation((path: string) =>
    path === "/backtests/6" ? Promise.resolve(bt) : Promise.reject(new Error(path)));
  render(
    <MemoryRouter initialEntries={["/backtests/6"]}>
      <Routes><Route path="/backtests/:id" element={<Backtests />} /></Routes>
    </MemoryRouter>,
  );
  const grid = await screen.findByTestId("metric-grid");
  expect(grid.className).toContain("grid-cols-2");
  expect(screen.getByRole("region", { name: "Warnings" })).toBeTruthy();
  await waitFor(() => expect(screen.getByText("Run final test")).toBeTruthy());
});
