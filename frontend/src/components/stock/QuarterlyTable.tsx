import type { Fundamentals, QuarterRow, TableData } from "../../api/types";
import Num from "../Num";
import { sourceTag } from "./FundamentalsPanel";

export interface QRow {
  period: string;
  revenue: number | null;
  profit: number | null;
  eps: number | null;
  salesYoy: number | null;
  profitYoy: number | null;
}

function yoy(now: number | null, then: number | null): number | null {
  if (now === null || then === null || then <= 0) return null;
  return (now / then - 1) * 100;
}

/** Days from `earlier` to `later` (negative if `earlier` is actually later). */
function daysBetween(later: string, earlier: string): number {
  return (Date.parse(later) - Date.parse(earlier)) / 864e5;
}

/** One usable row per period: consolidated preferred, first source seen wins. Newest last. */
function pick(rows: QuarterRow[]): QuarterRow[] {
  const byPeriod = new Map<string, QuarterRow>();
  for (const r of rows) {
    if (r.parse_error) continue;
    const have = byPeriod.get(r.period_end);
    if (!have || (r.consolidated && !have.consolidated)) byPeriod.set(r.period_end, r);
  }
  return [...byPeriod.values()].sort((a, b) => a.period_end.localeCompare(b.period_end));
}

export function fromResults(rows: QuarterRow[], last = 8): QRow[] {
  const all = pick(rows);
  const out = all.map((r) => {
    const prior = all.find((p) => Math.abs(daysBetween(r.period_end, p.period_end) - 365) <= 20);
    return {
      period: r.period_end,
      revenue: r.revenue,
      profit: r.net_profit,
      eps: r.eps,
      salesYoy: prior ? yoy(r.revenue, prior.revenue) : null,
      profitYoy: prior ? yoy(r.net_profit, prior.net_profit) : null,
    };
  });
  return out.slice(-last);
}

/** Fallback from a Screener-style table: rows "Sales", "Net Profit", "EPS in Rs"; 4 columns back = a year. */
export function fromTable(t: TableData, last = 8): QRow[] {
  const sales = t.rows["Sales"] ?? [];
  const profit = t.rows["Net Profit"] ?? [];
  const eps = t.rows["EPS in Rs"] ?? [];
  const out = t.periods.map((period, i) => ({
    period,
    revenue: sales[i] ?? null,
    profit: profit[i] ?? null,
    eps: eps[i] ?? null,
    salesYoy: i >= 4 ? yoy(sales[i] ?? null, sales[i - 4] ?? null) : null,
    profitYoy: i >= 4 ? yoy(profit[i] ?? null, profit[i - 4] ?? null) : null,
  }));
  return out.slice(-last);
}

export function buildQuarterRows(f: Fundamentals): { rows: QRow[]; from: string } {
  const official = fromResults(f.quarters);
  if (official.length > 0) {
    const src = f.quarters.find((q) => !q.parse_error)?.source ?? "";
    return { rows: official, from: `${src}` };
  }
  for (const [source, snap] of Object.entries(f.snapshots)) {
    const t = snap.detail?.quarters;
    if (t && t.periods.length > 0) {
      const rows = fromTable(t);
      if (rows.length > 0) return { rows, from: source };
    }
  }
  return { rows: [], from: "" };
}

interface Props {
  fundamentals: Fundamentals | null;
  labels: Record<string, string>;
}

export default function QuarterlyTable({ fundamentals, labels }: Props) {
  const built = fundamentals ? buildQuarterRows(fundamentals) : { rows: [], from: "" };
  return (
    <section className="rounded-card border border-border bg-card p-4" aria-label="Quarterly results">
      <h2>Last 8 quarters</h2>
      {built.rows.length === 0 ? (
        <p className="muted">No quarterly results yet.</p>
      ) : (
        <>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Quarter ended</th>
                  <th>Sales</th>
                  <th>Profit</th>
                  <th>Earnings per share</th>
                  <th>Sales vs a year ago</th>
                  <th>Profit vs a year ago</th>
                </tr>
              </thead>
              <tbody>
                {built.rows.map((r) => (
                  <tr key={r.period}>
                    <td>{r.period}</td>
                    <td><Num value={r.revenue} kind="cr" /></td>
                    <td><Num value={r.profit} kind="cr" /></td>
                    <td><Num value={r.eps} kind="inr" digits={2} /></td>
                    <td><Num value={r.salesYoy} kind="pct" colored /></td>
                    <td><Num value={r.profitYoy} kind="pct" colored /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted">
            Source: <span className="tag">{sourceTag(built.from, labels)}</span>. Amounts in ₹ crore.
          </p>
        </>
      )}
    </section>
  );
}
