import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";

import type { FundField, Fundamentals, QuarterRow } from "../api/types";
import FundamentalsPanel, { hint, relativeTime, sourceTag } from "../components/stock/FundamentalsPanel";
import QuarterlyTable, { buildQuarterRows, fromTable } from "../components/stock/QuarterlyTable";
import ShareholdingMini from "../components/stock/ShareholdingMini";

afterEach(cleanup);

const FIELDS: FundField[] = [
  { field: "roce_pct", label: "ROCE %", explain: "Profit on capital.", unit: "%", numeric: true },
  { field: "debt_to_equity", label: "Debt to equity", explain: "Borrowings.", unit: "x", numeric: true },
  { field: "profit_positive_4q", label: "Profit in last 4 quarters", explain: "1 if profit.", unit: "flag", numeric: true },
  { field: "market_cap_cr", label: "Market cap (₹ cr)", explain: "Size.", unit: "₹ cr", numeric: true },
];
const LABELS = { screener: "Screener.in", nse_api: "NSE website data" };

function fund(over: Partial<Fundamentals> = {}): Fundamentals {
  return {
    data: { roce_pct: 20, debt_to_equity: 1.5, profit_positive_4q: 0, market_cap_cr: 894066 },
    sources: { roce_pct: "screener", profit_positive_4q: "quarters:nse_api", debt_to_equity: "screener" },
    updated_at: new Date(Date.now() - 3 * 3600e3).toISOString(),
    quarters: [],
    snapshots: {},
    ...over,
  };
}

test("colour hints follow the rules", () => {
  expect(hint("roce_pct", 15)).toBe("pos");
  expect(hint("roce_pct", 7.9)).toBe("amber");
  expect(hint("roce_pct", 10)).toBe("");
  expect(hint("debt_to_equity", 1.01)).toBe("amber");
  expect(hint("debt_to_equity", 1)).toBe("");
  expect(hint("promoter_change_1y_pp", -2.1)).toBe("amber");
  expect(hint("profit_positive_4q", 0)).toBe("neg");
  expect(hint("profit_positive_4q", 1)).toBe("");
  expect(hint("roce_pct", null)).toBe("");
});

test("relative time and source tags", () => {
  const now = new Date("2026-11-09T12:00:00Z");
  expect(relativeTime("2026-11-09T09:00:00Z", now)).toBe("3 hours ago");
  expect(relativeTime("2026-11-04T12:00:00Z", now)).toBe("5 days ago");
  expect(relativeTime(null)).toBe("never");
  expect(sourceTag("screener", LABELS)).toBe("Screener.in");
  expect(sourceTag("quarters:nse_api", LABELS)).toBe("NSE website data results");
});

test("panel shows labels, values, source tags, hints and updated time", () => {
  const { container } = render(<FundamentalsPanel fundamentals={fund()} fields={FIELDS} labels={LABELS} />);
  expect(screen.getByText("ROCE %")).toBeTruthy();
  expect(screen.getByText("20.0%")).toBeTruthy();
  expect(screen.getByText("No")).toBeTruthy();
  expect(screen.getByText("NSE website data results")).toBeTruthy();
  expect(container.querySelector('[data-field="roce_pct"] [data-hint="pos"]')).not.toBeNull();
  expect(container.querySelector('[data-field="debt_to_equity"] [data-hint="amber"]')).not.toBeNull();
  expect(container.querySelector('[data-field="profit_positive_4q"] [data-hint="neg"]')).not.toBeNull();
  expect(screen.getByText(/Updated 3 hours ago/)).toBeTruthy();
  expect(screen.getAllByRole("button", { name: "Explain" }).length).toBe(4);
});

test("panel empty states", () => {
  render(<FundamentalsPanel fundamentals={fund({ data: {} })} fields={FIELDS} labels={LABELS} />);
  expect(screen.getByText(/No fundamentals yet/)).toBeTruthy();
  cleanup();
  render(<FundamentalsPanel fundamentals={null} fields={FIELDS} labels={LABELS} />);
  expect(screen.getByText(/see Jobs/)).toBeTruthy();
});

function q(period_end: string, revenue: number, net_profit: number, extra: Partial<QuarterRow> = {}): QuarterRow {
  return { source: "nse_api", symbol: "AAA", period_end, consolidated: 1, revenue, net_profit, eps: 1, parse_error: null, ...extra };
}

test("official quarters: last 8, YoY, consolidated preferred, errors skipped", () => {
  const periods = ["2024-03-31", "2024-06-30", "2024-09-30", "2024-12-31", "2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31"];
  const rows = periods.map((p, i) => q(p, 100 + i * 10, 10 + i));
  rows.push(q("2026-03-31", 1, 1, { consolidated: 0 }), q("2025-12-31", 5, 5, { parse_error: "x" }));
  const f = fund({ quarters: rows });
  const { rows: out } = buildQuarterRows(f);
  expect(out).toHaveLength(8);
  expect(out[0].period).toBe("2024-06-30");
  const last = out[out.length - 1];
  expect(last.period).toBe("2026-03-31");
  expect(last.revenue).toBe(180); // consolidated, not the standalone 1
  expect(last.salesYoy).toBeCloseTo((180 / 140 - 1) * 100);
  expect(out[1].salesYoy).toBeNull(); // no year-ago quarter in the data
});

test("falls back to a Screener-style table", () => {
  const periods = ["a", "b", "c", "d", "e"];
  const t = { periods, rows: { Sales: [100, 100, 100, 100, 150], "Net Profit": [10, 10, 10, 10, 5], "EPS in Rs": [1, 2, 3, 4, 5] } };
  const rows = fromTable(t);
  expect(rows[4].salesYoy).toBeCloseTo(50);
  expect(rows[4].profitYoy).toBeCloseTo(-50);
  expect(rows[3].salesYoy).toBeNull();
  const built = buildQuarterRows(fund({ snapshots: { screener: { fetched_at: "x", detail: { quarters: t } } } }));
  expect(built.from).toBe("screener");
  render(<QuarterlyTable fundamentals={fund({ snapshots: { screener: { fetched_at: "x", detail: { quarters: t } } } })} labels={LABELS} />);
  expect(screen.getByText("Last 8 quarters")).toBeTruthy();
  expect(screen.getAllByRole("row")).toHaveLength(6);
});

test("quarterly table empty state", () => {
  render(<QuarterlyTable fundamentals={fund()} labels={LABELS} />);
  expect(screen.getByText("No quarterly results yet.")).toBeTruthy();
});

test("shareholding table shows promoters, FIIs, DIIs for the last 8 periods", () => {
  const periods = Array.from({ length: 10 }, (_, i) => `P${i}`);
  const rows = {
    Promoters: periods.map((_, i) => 70 + i / 10),
    FIIs: periods.map(() => 12),
    DIIs: periods.map(() => 10),
  };
  render(
    <ShareholdingMini
      fundamentals={fund({ snapshots: { screener: { fetched_at: "x", detail: { shareholding: { periods, rows } } } } })}
      labels={LABELS}
    />,
  );
  expect(screen.getAllByRole("columnheader")).toHaveLength(9);
  expect(screen.getByText("P9")).toBeTruthy();
  expect(screen.queryByText("P1")).toBeNull();
  expect(screen.getByText("Foreign investors")).toBeTruthy();
  expect(screen.getByText("70.9%")).toBeTruthy();
});

test("shareholding renders nothing without data", () => {
  const { container } = render(<ShareholdingMini fundamentals={fund()} labels={LABELS} />);
  expect(container.firstChild).toBeNull();
});
