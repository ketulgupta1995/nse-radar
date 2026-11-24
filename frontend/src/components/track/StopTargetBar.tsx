import { cn } from "@/lib/utils";

interface Props {
  stop: number | null | undefined;
  target: number | null | undefined;
  entry: number | null | undefined;
  current: number | null | undefined;
  className?: string;
}

/** Position of `v` between stop (0%) and target (100%), clamped. */
export function stopTargetPct(v: number, stop: number, target: number): number {
  if (target === stop) return 50;
  return Math.max(0, Math.min(100, ((v - stop) / (target - stop)) * 100));
}

/** Small bar from stop (left) to target (right): a tick at entry, a marker at today's price. */
export default function StopTargetBar({ stop, target, entry, current, className }: Props) {
  if (stop == null || target == null || entry == null || current == null) {
    return <span className="text-muted-foreground">Not entered yet</span>;
  }
  const e = stopTargetPct(entry, stop, target);
  const c = stopTargetPct(current, stop, target);
  return (
    <span
      className={cn("relative inline-block h-1.5 w-32 rounded-full bg-muted align-middle", className)}
      role="img"
      aria-label={`Price is ${Math.round(c)}% of the way from stop to target`}
      title="Stop on the left, target on the right"
    >
      <span className="absolute top-0 h-1.5 rounded-full bg-accent/45" style={{ left: `${Math.min(e, c)}%`, width: `${Math.abs(c - e)}%` }} />
      <span className="absolute -top-0.5 h-2.5 w-px bg-muted-foreground" style={{ left: `${e}%` }} />
      <span className="absolute -top-1 h-3.5 w-0.5 rounded-sm bg-foreground" style={{ left: `calc(${c}% - 1px)` }} />
    </span>
  );
}
