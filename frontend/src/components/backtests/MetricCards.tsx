import type { MetricSet, Metrics } from "../../api/types";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import Explain from "../Explain";
import Num from "../Num";

interface Row {
  label: string;
  explain: string;
  render: (m: MetricSet) => React.ReactNode;
}

const ROWS: Row[] = [
  {
    label: "Yearly return",
    explain: "How much the strategy grew per year on average (CAGR), next to the Nifty 500 index over the same days.",
    render: (m) => (
      <>
        <Num value={m.cagr} kind="pct" colored /> <span className="muted">vs index </span>
        <Num value={m.bench_cagr} kind="pct" />
      </>
    ),
  },
  {
    label: "Beat the index by",
    explain: "Strategy yearly return minus the index's. Positive means the strategy did better than just holding the index.",
    render: (m) => <Num value={m.excess} kind="pct" colored />,
  },
  {
    label: "Worst fall",
    explain: "The biggest drop from a high point in your account value (max drawdown). Ask yourself if you could sit through it.",
    render: (m) => <Num value={m.max_drawdown} kind="pct" colored />,
  },
  {
    label: "Winning trades",
    explain: "Share of trades that made money. A low number can still be fine if the wins are much bigger than the losses.",
    render: (m) => <Num value={m.win_rate} kind="pct" digits={0} />,
  },
  {
    label: "Number of trades",
    explain: "More trades make the numbers more trustworthy. Under 30 is too few to learn much.",
    render: (m) => <Num value={m.trades} />,
  },
  {
    label: "Average days held",
    explain: "How long a typical trade lasted, in trading days.",
    render: (m) => <Num value={m.avg_days} digits={1} />,
  },
  {
    label: "Profit factor",
    explain: "Money won on winning trades divided by money lost on losing trades. Above 1 means profitable; blank means no losing trades.",
    render: (m) => <Num value={m.profit_factor} digits={2} />,
  },
];

type Col = { key: "all" | "is" | "oos"; title: string; sub: string };

const LEGACY_COLS: Col[] = [
  { key: "all", title: "All history", sub: "" },
  { key: "is", title: "In-sample", sub: "the part you could tweak against" },
  { key: "oos", title: "Out-of-sample", sub: "the hidden last part — trust this most" },
];
const EXPLORE_COLS: Col[] = [{ key: "is", title: "Training period", sub: "the years you tweak against" }];
const FINAL_COLS: Col[] = [
  { key: "all", title: "Whole period", sub: "" },
  { key: "is", title: "Training period", sub: "the years you could tweak against" },
  { key: "oos", title: "Test period (trust this most)", sub: "years the rule never saw" },
];

export default function MetricCards({ metrics, kind = "legacy" }: { metrics: Metrics; kind?: "explore" | "final" | "legacy" }) {
  const cols = (kind === "explore" ? EXPLORE_COLS : kind === "final" ? FINAL_COLS : LEGACY_COLS).filter((c) => metrics[c.key]);
  return (
    <div className={cn("mb-4 grid gap-4", cols.length === 1 ? "max-w-xl grid-cols-1" : "grid-cols-3")}>
      {cols.map((c) => (
        <Card key={c.key} data-metric-col={c.key} data-emphasis={c.key === "oos"} className={cn("min-w-0", c.key === "oos" && "border-accent")}>
          <h3>{c.title}</h3>
          {c.sub && <p className="muted">{c.sub}</p>}
          <dl className="m-0">
            {ROWS.map((r) => (
              <div key={r.label} className="flex items-baseline justify-between gap-2 border-b border-border py-1.5 last:border-b-0">
                <dt>
                  {r.label}
                  <Explain text={r.explain} />
                </dt>
                <dd className="m-0 text-right">{r.render(metrics[c.key] as MetricSet)}</dd>
              </div>
            ))}
          </dl>
        </Card>
      ))}
    </div>
  );
}
