import { useEffect, useState } from "react";
import { ApiError, api } from "../../api/client";
import type { NewsItem } from "../../api/types";
import { shortDay } from "../../lib/dates";

/** "2026-11-09T18:41:00+05:30" -> "9 Nov, 18:41" (the feed's own IST time). */
export function newsTime(ts: string): string {
  return `${shortDay(ts.slice(0, 10))}, ${ts.slice(11, 16)}`;
}

export default function NewsList({ symbol }: { symbol: string }) {
  const [items, setItems] = useState<NewsItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let stale = false;
    setItems(null);
    api
      .get<NewsItem[]>(`/news/items?symbol=${encodeURIComponent(symbol)}&limit=30`)
      .then((r) => {
        if (!stale) {
          setItems(r);
          setError(null);
        }
      })
      .catch((e) => !stale && setError(e instanceof ApiError ? e.message : String(e)));
    return () => {
      stale = true;
    };
  }, [symbol]);

  if (error) return <p className="neg">{error}</p>;
  if (items === null) return <p className="muted">Loading…</p>;
  if (items.length === 0) return <p className="muted">No news mentions this stock yet.</p>;
  return (
    <ul className="news-list">
      {items.map((n) => (
        <li key={n.id}>
          <a href={n.url} target="_blank" rel="noopener noreferrer">{n.title}</a>{" "}
          <span className="muted">
            {n.feed} · {newsTime(n.ts)}
          </span>
        </li>
      ))}
    </ul>
  );
}
