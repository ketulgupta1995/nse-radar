import type { DataHealth as Health } from "../../api/types";
import { shortDay, todayIso, weekdaysBehind } from "../../lib/dates";

interface Props {
  health: Health | null;
  labels: Record<string, string>;
  today?: string;
}

const n = (x: number) => x.toLocaleString("en-IN");

export default function DataHealth({ health: h, labels, today = todayIso() }: Props) {
  if (!h) return null;
  const stale = h.last_trading_date !== null && weekdaysBehind(h.last_trading_date, today) > 2;
  const name = (s: string) => labels[s] ?? s;
  return (
    <div className="health">
      <span className={stale || !h.last_trading_date ? "warn" : undefined}>
        Prices up to {h.last_trading_date ? shortDay(h.last_trading_date) : "— (none yet)"}
      </span>
      {Object.entries(h.bars).map(([s, b]) => (
        <span key={s}>
          {name(s)}: {n(b.symbols)} stocks, to {shortDay(b.last_date)}
        </span>
      ))}
      <span className={h.checks_open > 0 ? "warn" : undefined}>Open data issues: {h.checks_open}</span>
      {Object.entries(h.fundamentals).map(([s, c]) => (
        <span key={`f${s}`}>
          Fundamentals {s === "merged" ? "(combined)" : `(${name(s)})`}: {n(c)}
        </span>
      ))}
      {Object.entries(h.quarters).map(([s, c]) => (
        <span key={`q${s}`}>
          Quarterly results ({name(s)}): {n(c)}
        </span>
      ))}
      <span>
        News, last 7 days: {n(h.news.announcements_7d)} announcements, {n(h.news.news_7d)} headlines
      </span>
    </div>
  );
}
