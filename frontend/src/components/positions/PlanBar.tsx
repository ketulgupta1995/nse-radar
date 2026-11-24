import { formatNum } from "../Num";

interface Props {
  stop: number;
  entry: number;
  target: number;
  last: number | null;
}

/** Positions of the markers, in % along the bar from stop (0) to target (100); clamped to the bar. */
export function planPositions(stop: number, entry: number, target: number, last: number | null) {
  const span = target - stop;
  const at = (v: number) => (span > 0 ? Math.min(100, Math.max(0, ((v - stop) / span) * 100)) : 0);
  return { entry: at(entry), last: last === null ? null : at(last) };
}

export default function PlanBar({ stop, entry, target, last }: Props) {
  const p = planPositions(stop, entry, target, last);
  const tip = `Stop ${formatNum(stop, "inr", 2)} · Entry ${formatNum(entry, "inr", 2)} · ${
    last === null ? "no price yet" : `Last ${formatNum(last, "inr", 2)}`
  } · Target ${formatNum(target, "inr", 2)}`;
  return (
    <div className="planbar" title={tip} role="img" aria-label={tip}>
      <div className="planbar-red" style={{ left: 0, width: `${p.entry}%` }} />
      <div className="planbar-green" style={{ left: `${p.entry}%`, width: `${100 - p.entry}%` }} />
      <div className="planbar-entry" style={{ left: `${p.entry}%` }} />
      {p.last !== null && <div className="planbar-last" style={{ left: `${p.last}%` }} data-testid="last-marker" />}
    </div>
  );
}
