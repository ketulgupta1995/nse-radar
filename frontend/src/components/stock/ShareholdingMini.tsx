import type { Fundamentals, TableData } from "../../api/types";
import Explain from "../Explain";

const ROWS: [string, string][] = [
  ["Promoters", "Promoters (founders/parent)"],
  ["FIIs", "Foreign investors"],
  ["DIIs", "Indian funds and institutions"],
];

export function findShareholding(f: Fundamentals): { table: TableData; source: string } | null {
  for (const [source, snap] of Object.entries(f.snapshots)) {
    const t = snap.detail?.shareholding;
    if (t && t.periods.length > 0 && t.rows["Promoters"]) return { table: t, source };
  }
  return null;
}

interface Props {
  fundamentals: Fundamentals | null;
  labels: Record<string, string>;
}

export default function ShareholdingMini({ fundamentals, labels }: Props) {
  const found = fundamentals ? findShareholding(fundamentals) : null;
  if (!found) return null;
  const { table, source } = found;
  const n = Math.min(8, table.periods.length);
  const periods = table.periods.slice(-n);
  return (
    <section aria-label="Who owns the company">
      <h2>
        Who owns the company
        <Explain text="Share of the company held by each group, quarter by quarter. A falling promoter share can be a warning." />
      </h2>
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>Holder</th>
              {periods.map((p) => (
                <th key={p}>{p}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ROWS.filter(([k]) => table.rows[k]).map(([k, label]) => (
              <tr key={k}>
                <td>{label}</td>
                {table.rows[k].slice(-n).map((v, i) => (
                  <td key={periods[i]} className="num">
                    {v === null ? "—" : `${v.toFixed(1)}%`}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted">
        Source: <span className="tag">{labels[source] ?? source}</span>
      </p>
    </section>
  );
}
