import type { NextResults } from "../api/types";
import { Badge } from "@/components/ui/badge";
import Explain from "./Explain";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-11-12" -> "12 Nov" */
export function shortDate(iso: string): string {
  const [, m, d] = iso.split("-");
  return `${Number(d)} ${MONTHS[Number(m) - 1] ?? m}`;
}

interface Props {
  next: NextResults | null | undefined;
  /** Warning tone when the results are this many days away or fewer (default 14). */
  withinDays?: number;
}

export default function ResultsBadge({ next, withinDays = 14 }: Props) {
  if (!next) return null;
  const when = next.days === 0 ? " (today)" : next.days === 1 ? " (tomorrow)" : "";
  return (
    <span className="inline-flex items-center gap-1">
      <Badge variant={next.days <= withinDays ? "warning" : "neutral"}>
        Results {shortDate(next.date)}
        {when}
      </Badge>
      <Explain text="The company's board meets on this date to approve its quarterly results. The price often jumps or falls sharply the next trading day." />
    </span>
  );
}
