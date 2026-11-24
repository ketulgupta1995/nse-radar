import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { Idea, IdeaSeen } from "../../api/types";
import Explain from "../Explain";
import Num from "../Num";
import { Badge } from "@/components/ui/badge";
import { shortDay } from "@/lib/dates";
import { cn } from "@/lib/utils";
import { stopTargetPct } from "./StopTargetBar";

const BEST_WORST =
  "The highest and lowest the price went while the idea was running, in units of risk. A stopped-out idea with a big best point means the target may be too far away; a winner with a deep worst point means the stop was nearly hit.";

export const STATUS_LABEL: Record<string, string> = { open: "Open", pending: "Pending", closed: "Closed", no_data: "No data" };

export function ideaStatus(i: Idea): string {
  return i.outcome?.status ?? "pending";
}

export function StatusPill({ status }: { status: string }) {
  const variant = status === "open" ? "info" : status === "pending" ? "warning" : "neutral";
  return <Badge variant={variant}>{STATUS_LABEL[status] ?? status}</Badge>;
}

export function seenLabel(s: IdeaSeen): string {
  return s.source === "screen" ? (s.screen_name ?? "Screen") : `Shortlist #${s.rank ?? "?"}`;
}

export function R({ value, className }: { value: number | null | undefined; className?: string }) {
  if (value === null || value === undefined) return <span className={cn("num", className)}>—</span>;
  const s = `${value > 0 ? "+" : ""}${value.toFixed(1)}R`;
  return <span className={cn("num", value > 0 ? "pos" : value < 0 ? "neg" : "", className)}>{s}</span>;
}

function Big({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col">
      <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{label}</span>
      <span className="text-xl">{children}</span>
    </div>
  );
}

function Label({ children }: { children: ReactNode }) {
  return <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{children}</div>;
}

function Ladder({ idea }: { idea: Idea }) {
  const { planned_stop: stop, planned_target: target, planned_entry: entry } = idea;
  if (stop == null || target == null || entry == null) return null;
  const cur = idea.outcome?.status === "pending" || !idea.outcome ? null : idea.current_price ?? null;
  const p = (v: number) => 4 + stopTargetPct(v, stop, target) * 0.92;
  const tick = (left: number, label: string, value: number, dot: string, shift = "-translate-x-1/2") => (
    <div className={cn("absolute top-0 flex flex-col items-center gap-0.5 text-[11px] text-muted-foreground", shift)} style={{ left: `${left}%` }}>
      <span>{label}</span>
      <span className="num text-xs text-foreground">{value.toLocaleString("en-IN")}</span>
      <span className={cn("mt-1 size-2.5 rounded-full border-2 border-card", dot)} />
    </div>
  );
  return (
    <div className="relative mx-1.5 h-[74px]" aria-label="Price line from stop to target">
      <div className="absolute inset-x-0 top-[34px] h-1 rounded-full bg-muted" />
      {cur != null && (
        <div className="absolute top-[34px] h-1 rounded-full bg-accent/55" style={{ left: `${Math.min(p(entry), p(cur))}%`, width: `${Math.abs(p(cur) - p(entry))}%` }} />
      )}
      {tick(p(stop), "Stop", stop, "bg-neg", "-translate-x-[15%]")}
      {tick(p(entry), "Entry", entry, "bg-muted-foreground")}
      {tick(p(target), "Target", target, "bg-pos", "-translate-x-[85%]")}
      {cur != null && (
        <div className="absolute top-[30px] flex -translate-x-1/2 flex-col items-center gap-0.5" style={{ left: `${p(cur)}%` }}>
          <span className="size-2.5 rounded-full border-2 border-card bg-accent" />
          <span className="num text-xs font-medium">{cur.toLocaleString("en-IN")}</span>
          <span className="text-[11px] text-muted-foreground">now</span>
        </div>
      )}
    </div>
  );
}

export default function IdeaPanel({ idea }: { idea: Idea | null }) {
  if (!idea) {
    return <p className="py-12 text-center text-muted-foreground">Select an idea to see its plan, reasons and result.</p>;
  }
  const status = ideaStatus(idea);
  const o = idea.outcome;
  const days = new Set(idea.seen.map((s) => s.as_of)).size;
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h2 className="m-0 font-mono text-lg font-semibold">{idea.symbol}</h2>
          <div className="text-xs text-muted-foreground">
            {idea.name ?? idea.symbol} · logged {idea.first_as_of}
          </div>
        </div>
        <StatusPill status={status} />
      </div>

      <div className="flex gap-6">
        {status === "pending" ? (
          <>
            <Big label="Return">—</Big>
            <Big label="Enters"><span className="text-base">next open</span></Big>
          </>
        ) : (
          <>
            <Big label={status === "closed" ? "Final return" : "Return so far"}><Num value={o?.return_pct} kind="pct" colored /></Big>
            <Big label="Result in R"><R value={o?.r_multiple} /></Big>
          </>
        )}
      </div>

      <div>
        <Label>Plan</Label>
        <Ladder idea={idea} />
      </div>

      <dl className="m-0 grid grid-cols-[1fr_auto] gap-x-3 gap-y-1.5">
        <dt className="text-muted-foreground">Entry price</dt><dd className="m-0 text-right"><Num value={idea.planned_entry} kind="inr" digits={2} /></dd>
        <dt className="text-muted-foreground">Current price</dt><dd className="m-0 text-right"><Num value={idea.current_price} kind="inr" digits={2} /></dd>
        <dt className="text-muted-foreground">Stop</dt><dd className="m-0 text-right"><Num value={idea.planned_stop} kind="inr" digits={2} /></dd>
        <dt className="text-muted-foreground">Target</dt><dd className="m-0 text-right"><Num value={idea.planned_target} kind="inr" digits={2} /></dd>
        {status !== "pending" && o && (
          <>
            <dt className="text-muted-foreground">Best point<Explain text={BEST_WORST} /></dt><dd className="m-0 text-right"><R value={o.mfe_r} /></dd>
            <dt className="text-muted-foreground">Worst point</dt><dd className="m-0 text-right"><R value={o.mae_r} /></dd>
          </>
        )}
        {status === "closed" && o && (
          <>
            <dt className="text-muted-foreground">How it ended</dt><dd className="m-0 text-right">{o.exit_reason ?? "—"}{o.exit_date ? `, ${o.exit_date}` : ""}</dd>
            <dt className="text-muted-foreground">Beat Nifty by</dt><dd className="m-0 text-right"><Num value={o.excess_pct} kind="pct" colored /></dd>
          </>
        )}
      </dl>

      <div>
        <Label>
          Picked {idea.seen.length} time{idea.seen.length === 1 ? "" : "s"}
          {days > 1 ? ` over ${days} days` : ""}
        </Label>
        <ol className="m-0 flex list-none flex-col gap-2 border-l-2 border-border py-0 pl-3.5 pr-0">
          {idea.seen.map((s, i) => (
            <li key={s.signal_id} className="relative grid grid-cols-[48px_1fr_auto] items-baseline gap-2">
              <span className={cn("absolute -left-[20px] top-1.5 size-2.5 rounded-full border-2 border-card", i === 0 ? "bg-accent" : "bg-muted-foreground")} />
              <span className="num text-xs">{shortDay(s.as_of)}</span>
              <span>
                {seenLabel(s)}
                {i === 0 && <span className="ml-1 text-[11px] text-accent">graded from here</span>}
              </span>
              <span className="num text-xs text-muted-foreground">{s.score == null ? "" : `score ${Math.round(s.score)}`}</span>
            </li>
          ))}
        </ol>
      </div>

      <div>
        <Label>Why it was picked</Label>
        {idea.reasons.length === 0 ? (
          <p className="m-0 text-muted-foreground">No reasons recorded.</p>
        ) : (
          <ul className="m-0 flex flex-col gap-1 pl-4">
            {idea.reasons.map((r, i) => <li key={i}>{typeof r === "string" ? r : JSON.stringify(r)}</li>)}
          </ul>
        )}
      </div>

      <Link to={`/stock/${idea.symbol}`} className="text-sm">Open {idea.symbol} stock page →</Link>
    </div>
  );
}
