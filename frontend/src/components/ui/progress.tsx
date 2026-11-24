import { cn } from "@/lib/utils";

export function Progress({ value, max = 100, label, className }: { value: number; max?: number; label?: string; className?: string }) {
  const pct = max > 0 ? Math.min(100, Math.max(0, (value / max) * 100)) : 0;
  return (
    <div
      role="progressbar"
      aria-valuenow={value}
      aria-valuemin={0}
      aria-valuemax={max}
      className={cn("relative h-4 w-28 overflow-hidden rounded-control bg-muted align-middle", className)}
    >
      <div className="absolute inset-y-0 left-0 bg-accent/60" style={{ width: `${pct}%` }} />
      {label && <span className="relative px-1 text-[11px]">{label}</span>}
    </div>
  );
}
