const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-11-06" -> "6 Nov" */
export function shortDay(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [, m, d] = iso.split("-").map(Number);
  return `${d} ${MONTHS[m - 1]}`;
}

/** Weekdays (Mon-Fri) strictly after `from` up to and including `to`. */
export function weekdaysBehind(from: string, to: string): number {
  const a = new Date(`${from}T00:00:00Z`);
  const b = new Date(`${to}T00:00:00Z`);
  let n = 0;
  for (const d = new Date(a.getTime() + 864e5); d <= b; d.setUTCDate(d.getUTCDate() + 1)) {
    const wd = d.getUTCDay();
    if (wd !== 0 && wd !== 6) n++;
  }
  return n;
}

export function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

/** "5 min ago", "3 hours ago", "2 days ago". */
export function relativeAgo(iso: string, now: Date = new Date()): string {
  const mins = Math.round((now.getTime() - new Date(iso).getTime()) / 60000);
  if (Number.isNaN(mins)) return "";
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  return `${Math.round(hours / 24)} days ago`;
}

/** "2026-11-06" -> "Fri 6 Nov" (no timezone maths: the date is taken as written). */
export function formatDay(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  const wd = new Date(Date.UTC(y, m - 1, d)).getUTCDay();
  return `${["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][wd]} ${d} ${MONTHS[m - 1]}`;
}
