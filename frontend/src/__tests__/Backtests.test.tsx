import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";

import { api } from "../api/client";
import type { Backtest, BacktestConfig, ExitDefInfo, MetricSet, Screen } from "../api/types";
import BacktestForm from "../components/backtests/BacktestForm";
import { oosMarkerTime } from "../components/backtests/EquityChart";
import MetricCards from "../components/backtests/MetricCards";
import WarningsBox from "../components/backtests/WarningsBox";
import { DEFAULT_EXITS, POSITION_EXITS, SHORT_EXITS, TREND_EXITS, defaultConfig, sortTrades } from "../lib/backtests";
import Backtests from "../pages/Backtests";

vi.mock("../components/backtests/EquityChart", () => ({
  default: () => <div data-testid="chart" />,
  oosMarkerTime: (pts: { t: string }[], s: string | null) => pts.find((p) => p.t >= (s ?? "~"))?.t ?? null,
}));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const exits: ExitDefInfo[] = [
  { type: "stop_atr", label: "Stop-loss (ATR)", explain: "e", when: "intraday",
    params: [{ name: "k", kind: "float", default: 2, min: 0.1, max: 20, label: "ATRs below entry" }] },
  { type: "time_stop", label: "Time stop", explain: "e", when: "close",
    params: [{ name: "days", kind: "int", default: 40, min: 1, max: 500, label: "Trading days" }] },
];
const rule = { all: [{ left: { ind: "close" }, op: ">", right: { value: 1 } }] } as Screen["rule"];
const screens = [{ id: 3, name: "Leaders", rule }] as unknown as Screen[];
const ms = (over: Partial<MetricSet>): MetricSet => ({
  cagr: 12, bench_cagr: 10, excess: 2, max_drawdown: -20, volatility: 15, trades: 40, win_rate: 55, avg_win: 8,
  avg_loss: -4, profit_factor: 1.8, avg_days: 20, exposure: 60, best: null, worst: null, ...over,
});

const fromBt = {
  id: 4, name: "Leaders", status: "done", kind: "explore", parent_id: null, run_id: 1, explore_runs: 1, attempt: null,
  created_at: "2026-11-09T10:00:00", finished_at: "x", warnings: [], equity: null, trades: null, metrics: null,
  config: {
    entry_rule: { all: [{ right: { value: 1 }, op: ">", left: { ind: "close" } }] },
    exits: [{ type: "time_stop", params: { days: 15 } }], max_positions: 7, sizing: "equal", risk_pct: 0.5,
    start: "2014-01-01", oos_start: "2020-01-01", end: "2024-01-01", universe: "liquid500",
  },
} as unknown as Backtest;

test("defaults are stop 2xATR, target 4xATR, time stop 40", () => {
  expect(defaultConfig("2022-01-01").exits.map((e) => e.type)).toEqual(["stop_atr", "target_atr", "time_stop"]);
});

test("sortTrades sorts by key and direction", () => {
  const t = (symbol: string, pnl: number) => ({ symbol, pnl }) as never;
  expect(sortTrades([t("A", 1), t("B", 3), t("C", 2)], "pnl", -1).map((x) => x.symbol)).toEqual(["B", "C", "A"]);
});

test("oos marker lands on the first bar on/after the start", () => {
  const pts = [{ t: "2020-01-01", v: 1 }, { t: "2020-01-03", v: 1 }];
  expect(oosMarkerTime(pts, "2020-01-02")).toBe("2020-01-03");
  expect(oosMarkerTime(pts, null)).toBeNull();
});

test("metric cards show three columns with the out-of-sample one emphasised", () => {
  const { container } = render(<MetricCards metrics={{ all: ms({}), is: ms({}), oos: ms({ cagr: 3 }), oos_start: "x" }} />);
  expect(screen.getByText("Out-of-sample")).toBeTruthy();
  expect(container.querySelectorAll("[data-metric-col]")).toHaveLength(3);
  expect(container.querySelectorAll("[data-emphasis=\"true\"]")).toHaveLength(1);
  expect(screen.getAllByText("Profit factor")).toHaveLength(3);
});

test("warnings box lists every warning", () => {
  render(<WarningsBox warnings={["one", "two"]} />);
  expect(screen.getByText("one")).toBeTruthy();
  expect(screen.getByText("two")).toBeTruthy();
});

function installGets() {
  vi.spyOn(api, "get").mockImplementation((path: string) => {
    if (path === "/screens") return Promise.resolve(screens);
    if (path === "/settings") return Promise.resolve({ holdout_start: "2022-01-01", capital_inr: 500000 });
    if (path === "/backtests/4") return Promise.resolve(fromBt);
    if (path === "/backtests/exits") return Promise.resolve(exits);
    if (path === "/indicators" || path === "/fundamentals/fields") return Promise.resolve([]);
    if (path === "/rules/ops") return Promise.resolve([]);
    return Promise.reject(new Error(`unexpected ${path}`));
  });
}

test("form builds exits from the exits endpoint and runs a screen backtest", async () => {
  installGets();
  const post = vi.spyOn(api, "post").mockResolvedValue({ id: 8, run_id: 1 });
  const started = vi.fn();
  render(<MemoryRouter><BacktestForm onStarted={started} onCancel={() => undefined} /></MemoryRouter>);
  await screen.findByText("Leaders");
  fireEvent.change(screen.getByLabelText("Exit type to add"), { target: { value: "time_stop" } });
  fireEvent.click(screen.getByText("Add exit"));
  expect(screen.getAllByText("Time stop").length).toBeGreaterThan(0);
  expect((screen.getByDisplayValue("Most-traded 500 at the time (fairer)") as HTMLSelectElement).value).toBe("liquid500");
  fireEvent.click(screen.getByText("Run on training period"));
  await waitFor(() => expect(started).toHaveBeenCalledWith(8));
  const [path, body] = post.mock.calls[0] as [
    string,
    { config: { exits: unknown[]; max_positions: number; universe: string } },
  ];
  expect(body.config.universe).toBe("liquid500");
  expect(path).toBe("/screens/3/backtest");
  expect(body.config.exits).toHaveLength(4);
  expect(body.config.max_positions).toBe(10);
});

test("ranking, industry cap and weak-market controls go into the config", async () => {
  installGets();
  const post = vi.spyOn(api, "post").mockResolvedValue({ id: 8, run_id: 1 });
  render(<MemoryRouter><BacktestForm onStarted={() => undefined} onCancel={() => undefined} /></MemoryRouter>);
  await screen.findByText("Leaders");
  fireEvent.change(screen.getByDisplayValue("Relative strength (126)"), { target: { value: "mom_smooth" } });
  fireEvent.change(screen.getByPlaceholderText("No cap"), { target: { value: "2" } });
  fireEvent.click(screen.getByLabelText("Use fewer slots in weak markets"));
  fireEvent.change(screen.getByLabelText(/Slots to use/), { target: { value: "25" } });
  fireEvent.click(screen.getByText("Run on training period"));
  await waitFor(() => expect(post).toHaveBeenCalled());
  const cfg = (post.mock.calls[0][1] as { config: BacktestConfig }).config;
  expect(cfg.rank_by).toEqual({ ind: "mom_smooth", params: { n: 126 } });
  expect(cfg.max_per_industry).toBe(2);
  expect(cfg.regime_scale).toEqual({ breadth_below: 50, slots_pct: 25 });
});

test("choosing monthly rotation sends mode and hold_buffer", async () => {
  installGets();
  const post = vi.spyOn(api, "post").mockResolvedValue({ id: 8, run_id: 1 });
  render(<MemoryRouter><BacktestForm onStarted={() => undefined} onCancel={() => undefined} /></MemoryRouter>);
  await screen.findByText("Leaders");
  fireEvent.change(screen.getByDisplayValue("When the rule fires (daily)"), { target: { value: "rotate_monthly" } });
  fireEvent.change(screen.getByDisplayValue("1.5"), { target: { value: "2" } });
  fireEvent.click(screen.getByText("Run on training period"));
  await waitFor(() => expect(post).toHaveBeenCalled());
  const cfg = (post.mock.calls[0][1] as { config: BacktestConfig }).config;
  expect(cfg.mode).toBe("rotate_monthly");
  expect(cfg.hold_buffer).toBe(2);
});

test("batch: try several values sends one config per value, with names", async () => {
  installGets();
  const post = vi.spyOn(api, "post").mockResolvedValue({ ids: [1, 2], run_id: 3 });
  const batch = vi.fn();
  render(<MemoryRouter><BacktestForm onStarted={() => undefined} onBatchStarted={batch} onCancel={() => undefined} /></MemoryRouter>);
  await screen.findByText("Leaders");
  fireEvent.click(screen.getByText(/Run several at once/));
  fireEvent.change(screen.getByLabelText(/Setting to vary/), { target: { value: "max_positions" } });
  const input = screen.getByLabelText(/Values, separated by commas/);
  fireEvent.change(input, { target: { value: "5, x" } });
  expect((screen.getByText(/Run 0 backtests/) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(input, { target: { value: "5, 8" } });
  fireEvent.click(screen.getByText("Run 2 backtests on training period"));
  await waitFor(() => expect(batch).toHaveBeenCalledWith([1, 2]));
  const [path, body] = post.mock.calls[0] as [string, { configs: BacktestConfig[]; names: string[]; name: null }];
  expect(path).toBe("/backtests/batch");
  expect(body.configs.map((c) => c.max_positions)).toEqual([5, 8]);
  expect(body.names).toEqual(["Backtest · Max positions 5", "Backtest · Max positions 8"]);
});

test("batch: compare screens sends each ticked screen's rule", async () => {
  const two = [
    { id: 3, name: "Leaders", rule },
    { id: 4, name: "Dips", rule: { all: [{ left: { ind: "close" }, op: "<", right: { value: 2 } }] } },
  ] as unknown as Screen[];
  vi.spyOn(api, "get").mockImplementation((path: string) => {
    if (path === "/screens") return Promise.resolve(two);
    if (path === "/settings") return Promise.resolve({ holdout_start: "2022-01-01" });
    if (path === "/backtests/exits") return Promise.resolve(exits);
    return Promise.resolve([]);
  });
  const post = vi.spyOn(api, "post").mockResolvedValue({ ids: [1, 2], run_id: 3 });
  render(<MemoryRouter><BacktestForm onStarted={() => undefined} onCancel={() => undefined} /></MemoryRouter>);
  await screen.findAllByText("Leaders");
  fireEvent.click(screen.getByText(/Run several at once/));
  fireEvent.click(screen.getByLabelText("Compare screens"));
  fireEvent.click(screen.getByRole("checkbox", { name: "Leaders" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "Dips" }));
  fireEvent.click(screen.getByText("Run 2 backtests on training period"));
  await waitFor(() => expect(post).toHaveBeenCalled());
  const body = post.mock.calls[0][1] as { configs: BacktestConfig[]; names: string[] };
  expect(body.configs.map((c) => c.entry_rule)).toEqual(two.map((s) => s.rule));
  expect(body.names).toEqual(["Leaders · Swing (fixed target)", "Dips · Swing (fixed target)"]);
});

async function submittedExits(clicks: string[], edit?: () => void): Promise<unknown[]> {
  installGets();
  const post = vi.spyOn(api, "post").mockResolvedValue({ id: 8, run_id: 1 });
  render(<MemoryRouter><BacktestForm onStarted={() => undefined} onCancel={() => undefined} /></MemoryRouter>);
  await screen.findByText("Leaders");
  for (const c of clicks) fireEvent.click(screen.getByText(c));
  edit?.();
  fireEvent.click(screen.getByText("Run on training period"));
  await waitFor(() => expect(post).toHaveBeenCalled());
  return (post.mock.calls[0][1] as { config: { exits: unknown[] } }).config.exits;
}

test("Trend exit set puts exactly the three trend exits in the config", async () => {
  expect(await submittedExits(["Trend (trailing 50-day)"])).toEqual(TREND_EXITS);
});

test("Position exit set puts the three slow exits in the config", async () => {
  expect(await submittedExits(["Position (trailing 100-day)"])).toEqual(POSITION_EXITS);
  expect(POSITION_EXITS[2].params.days).toBe(120);
});

test("Short dip exit set puts exactly SHORT_EXITS in the config", async () => {
  expect(await submittedExits(["Short dip (about a week)"])).toEqual(SHORT_EXITS);
});

test("Swing exit set restores the defaults, and editing never mutates the shared sets", async () => {
  expect(await submittedExits(["Trend (trailing 50-day)", "Swing (fixed target)"])).toEqual(DEFAULT_EXITS);
  cleanup();
  vi.restoreAllMocks();
  await submittedExits(["Trend (trailing 50-day)"], () =>
    fireEvent.change(screen.getByDisplayValue("3"), { target: { value: "5" } }));
  expect(TREND_EXITS[0].params.k).toBe(3);
});

test("result page shows warnings, metrics and trades, and a Stop button while running", async () => {
  const done = {
    id: 5, name: "Leaders", status: "done", kind: "legacy", run_id: 2, created_at: "2026-11-09T10:00:00", finished_at: "x",
    config: {}, warnings: ["Past results do not guarantee future returns."],
    metrics: { all: ms({}), is: ms({}), oos: ms({}), oos_start: "2020-01-02" },
    equity: [{ t: "2020-01-01", v: 1 }],
    trades: [{ symbol: "ABC", entry_date: "a", entry: 1, exit_date: "b", exit: 2, qty: 1, pnl: 1, pnl_pct: 1, reason: "target", days: 1 }],
  } as unknown as Backtest;
  vi.spyOn(api, "get").mockResolvedValue(done);
  render(
    <MemoryRouter initialEntries={["/backtests/5"]}>
      <Routes><Route path="/backtests/:id" element={<Backtests />} /></Routes>
    </MemoryRouter>,
  );
  expect(await screen.findByText("Past results do not guarantee future returns.")).toBeTruthy();
  expect(screen.getByTestId("chart")).toBeTruthy();
  expect(screen.getByText("ABC")).toBeTruthy();
  expect(screen.queryByText("Stop")).toBeNull();
  cleanup();

  const running = { ...done, status: "running", metrics: null, equity: null, trades: null, warnings: [] };
  vi.spyOn(api, "get").mockImplementation((p: string) =>
    Promise.resolve(p.startsWith("/jobs/runs") ? { total: 100, done: 40 } : running),
  );
  const post = vi.spyOn(api, "post").mockResolvedValue({});
  render(
    <MemoryRouter initialEntries={["/backtests/5"]}>
      <Routes><Route path="/backtests/:id" element={<Backtests />} /></Routes>
    </MemoryRouter>,
  );
  fireEvent.click(await screen.findByText("Stop"));
  await waitFor(() => expect(post).toHaveBeenCalledWith("/jobs/runs/2/stop"));
  expect(await screen.findByText(/day 40 of 100/)).toBeTruthy();
});

function LocationProbe() {
  const l = useLocation();
  return <div data-testid="loc">{l.pathname + l.search}</div>;
}

function formAt(url: string) {
  render(
    <MemoryRouter initialEntries={[url]}>
      <Routes><Route path="/backtests/new" element={<Backtests />} /></Routes>
    </MemoryRouter>,
  );
}

test("?screen= preselects the screen and Test from defaults to the holdout setting", async () => {
  installGets();
  formAt("/backtests/new?screen=3");
  await screen.findByText("Leaders");
  expect((screen.getByDisplayValue("Leaders") as HTMLSelectElement).value).toBe("3");
  expect((screen.getByLabelText("Test from") as HTMLInputElement).value).toBe("2022-01-01");
  expect((screen.getByLabelText("Train from") as HTMLInputElement).value).toBe("2012-01-01");
  expect(screen.getByText(/^Train 2012-01-01 → 2021-12-31/)).toBeTruthy();
});

test("?from= fills the form from an earlier backtest and bumps the name", async () => {
  installGets();
  formAt("/backtests/new?from=4");
  await screen.findByDisplayValue("Leaders v2");
  expect((screen.getByLabelText("Train from") as HTMLInputElement).value).toBe("2014-01-01");
  expect((screen.getByLabelText("Test from") as HTMLInputElement).value).toBe("2020-01-01");
  expect((screen.getByLabelText(/Test until/) as HTMLInputElement).value).toBe("2024-01-01");
  expect(screen.getByDisplayValue("7")).toBeTruthy(); // max positions
  expect(screen.getByDisplayValue("15")).toBeTruthy(); // time stop days
  expect((screen.getByDisplayValue("Leaders") as HTMLSelectElement).value).toBe("3"); // rule matched the saved screen
});

test("Train from on or after Test from shows a message and disables submit", async () => {
  installGets();
  formAt("/backtests/new?screen=3");
  await screen.findByText("Leaders");
  fireEvent.change(screen.getByLabelText("Train from"), { target: { value: "2023-01-01" } });
  expect(screen.getByRole("alert").textContent).toMatch(/Train from must be earlier/);
  expect((screen.getByText("Run on training period") as HTMLButtonElement).disabled).toBe(true);
});

function resultAt(bt: Backtest) {
  vi.spyOn(api, "get").mockResolvedValue(bt);
  render(
    <MemoryRouter initialEntries={[`/backtests/${bt.id}`]}>
      <Routes>
        <Route path="/backtests/:id" element={<Backtests />} />
        <Route path="/backtests/new" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

const exploreBt = {
  ...fromBt, id: 6, explore_runs: 27, warnings: [],
  metrics: { all: null, is: ms({}), oos: null, oos_start: "2020-01-01" },
  equity: [{ t: "2020-01-01", v: 1 }],
} as unknown as Backtest;

test("explore result: one column, locked card, final test needs a confirm then POSTs", async () => {
  const post = vi.spyOn(api, "post").mockResolvedValue({ id: 9, run_id: 3, attempt: 1 });
  resultAt(exploreBt);
  expect(await screen.findByText(/is still hidden/)).toBeTruthy();
  expect(document.querySelectorAll("[data-metric-col]")).toHaveLength(1);
  expect(screen.getByText("Training period")).toBeTruthy();
  expect(screen.getByText(/27 backtests have been run/)).toBeTruthy();
  fireEvent.click(screen.getByText("Run final test"));
  expect(post).not.toHaveBeenCalled();
  expect(screen.getByText(/Run this once/)).toBeTruthy();
  fireEvent.click(screen.getByText("Run final test"));
  await waitFor(() => expect(post).toHaveBeenCalledWith("/backtests/6/final"));
});

test("Tweak and rerun goes to the form with ?from=", async () => {
  resultAt(exploreBt);
  fireEvent.click(await screen.findByText("Tweak and rerun"));
  expect((await screen.findByTestId("loc")).textContent).toBe("/backtests/new?from=6");
});

test("final result shows three columns and the attempt badge", async () => {
  const fin = {
    ...exploreBt, id: 7, kind: "final", parent_id: 6, attempt: 2,
    metrics: { all: ms({}), is: ms({}), oos: ms({}), oos_start: "2020-01-01" },
  } as unknown as Backtest;
  resultAt(fin);
  expect(await screen.findByText(/Final test · attempt 2/)).toBeTruthy();
  expect(document.querySelectorAll("[data-metric-col]")).toHaveLength(3);
  expect(screen.getByText("Test period (trust this most)")).toBeTruthy();
  expect(screen.queryByText("Run final test")).toBeNull();
  expect(await screen.findByText("← training run #6")).toBeTruthy();
});

test("the list marks explore rows as training", async () => {
  vi.spyOn(api, "get").mockResolvedValue([
    { id: 1, name: "A", status: "done", kind: "explore", parent_id: null, created_at: "2026-11-09T10:00:00", finished_at: null,
      metrics: { is: { cagr: 12, excess: 2 }, oos: null } },
    { id: 2, name: "B", status: "done", kind: "final", parent_id: 1, created_at: "2026-11-09T10:00:00", finished_at: null,
      metrics: { is: { cagr: 12, excess: 2 }, oos: { cagr: 5, excess: 1 } } },
  ]);
  render(<MemoryRouter initialEntries={["/backtests"]}><Routes><Route path="/backtests" element={<Backtests />} /></Routes></MemoryRouter>);
  await screen.findByText("A");
  expect(screen.getAllByText("(training)")).toHaveLength(2);
  expect(screen.getByText("Training")).toBeTruthy();
  expect(screen.getByText("Final")).toBeTruthy();
});

test("starting money defaults to the Settings capital and can be changed", async () => {
  installGets();
  const post = vi.spyOn(api, "post").mockResolvedValue({ id: 8, run_id: 1 });
  render(<MemoryRouter><BacktestForm onStarted={() => undefined} onCancel={() => undefined} /></MemoryRouter>);
  await screen.findByText("Leaders");
  const input = screen.getByLabelText("Starting money") as HTMLInputElement;
  expect(input.value).toBe("500000");
  fireEvent.change(input, { target: { value: "200000" } });
  fireEvent.click(screen.getByText("Run on training period"));
  await waitFor(() => expect(post).toHaveBeenCalled());
  expect((post.mock.calls[0][1] as { config: BacktestConfig }).config.initial_capital).toBe(200000);
});
