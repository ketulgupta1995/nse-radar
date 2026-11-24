import type { FundField, Fundamentals } from "../../api/types";
import Explain from "../Explain";
import Num from "../Num";

export type Hint = "pos" | "amber" | "neg" | "";

/** Colour hint for a value: green is good, amber is a caution, red is a warning. */
export function hint(field: string, value: number | string | null | undefined): Hint {
  if (typeof value !== "number") return "";
  if (field === "roce_pct") return value >= 15 ? "pos" : value < 8 ? "amber" : "";
  if (field === "debt_to_equity") return value > 1 ? "amber" : "";
  if (field === "promoter_change_1y_pp") return value < -2 ? "amber" : "";
  if (field === "profit_positive_4q") return value === 0 ? "neg" : "";
  return "";
}

export function relativeTime(iso: string | null, now: Date = new Date()): string {
  if (!iso) return "never";
  const mins = Math.max(0, Math.round((now.getTime() - new Date(iso).getTime()) / 60000));
  if (Number.isNaN(mins)) return "never";
  if (mins < 60) return "just now";
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.round(hours / 24);
  return `${days} days ago`;
}

/** "quarters:nse_api" -> "<label> results"; plain names use the label map. */
export function sourceTag(source: string | undefined, labels: Record<string, string>): string {
  if (!source) return "";
  if (source.startsWith("quarters:")) {
    const name = source.slice("quarters:".length);
    return `${labels[name] ?? name} results`;
  }
  return labels[source] ?? source;
}

function Value({ meta, value }: { meta: FundField; value: number | string | null | undefined }) {
  if (value === null || value === undefined) return <span className="muted">—</span>;
  if (typeof value === "string") return <span>{value}</span>;
  switch (meta.unit) {
    case "₹ cr":
      return <Num value={value} kind="cr" />;
    case "flag":
      return <span>{value >= 1 ? "Yes" : "No"}</span>;
    case "%":
      return <span className="num">{value.toFixed(1)}%</span>;
    case "pp":
      return <span className="num">{`${value > 0 ? "+" : ""}${value.toFixed(1)} pp`}</span>;
    default:
      return <Num value={value} digits={2} />;
  }
}

interface Props {
  fundamentals: Fundamentals | null;
  fields: FundField[];
  labels: Record<string, string>;
}

export default function FundamentalsPanel({ fundamentals, fields, labels }: Props) {
  const data = fundamentals?.data ?? {};
  const shown = fields.filter((f) => data[f.field] !== undefined && data[f.field] !== null);
  return (
    <section aria-label="Fundamentals">
      <h2>Company quality and value</h2>
      {fundamentals === null || shown.length === 0 ? (
        <p className="muted">
          No fundamentals yet; they fill in over a few days in the background (see Jobs).
        </p>
      ) : (
        <>
          <div className="fund-grid">
            {shown.map((f) => {
              const v = data[f.field];
              return (
                <div key={f.field} className="fund-item" data-field={f.field}>
                  <div className="muted">
                    {f.label}
                    <Explain text={f.explain} />
                  </div>
                  <div className={hint(f.field, v)} data-hint={hint(f.field, v)}>
                    <Value meta={f} value={v} />{" "}
                    <span className="tag" title="Where this number came from">
                      {sourceTag(fundamentals.sources[f.field], labels)}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
          <p className="muted">Updated {relativeTime(fundamentals.updated_at)}</p>
        </>
      )}
    </section>
  );
}
