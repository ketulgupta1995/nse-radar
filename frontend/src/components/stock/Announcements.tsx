import { useEffect, useState } from "react";
import { ApiError, api } from "../../api/client";
import type { Announcement, AnnouncementCategory } from "../../api/types";
import { shortDay } from "../../lib/dates";

const LABELS: Record<string, string> = {
  results: "Results",
  pledge: "Pledge",
  block_deal: "Block deal",
  order_win: "Order win",
  board_meeting: "Board meeting",
  credit_rating: "Rating",
  dividend: "Dividend",
  insider: "Insider",
  routine: "Routine",
  other_important: "Other important",
  other: "Other",
};

export function categoryLabel(c: string): string {
  return LABELS[c] ?? c.replace(/_/g, " ").replace(/^./, (m) => m.toUpperCase());
}

const LEAD_PREFIX = /^.*?\bhas informed the exchange\s+(?:about|regarding)\s*/i;

/** NSE's short subject is often generic ("Updates"); the useful sentence is in the body. */
export function bodyLead(body: string | null, max = 140): string {
  if (!body) return "";
  let t = body.replace(LEAD_PREFIX, "").trim();
  t = t.replace(/^['"‘“]+|['"’”.]+$/g, "").trim();
  return t.length > max ? `${t.slice(0, max - 1).trimEnd()}…` : t;
}

export function displayTitle(a: Announcement): { title: string; subject: string | null } {
  const lead = bodyLead(a.body);
  if (lead && lead.toLowerCase() !== a.headline.toLowerCase()) return { title: lead, subject: a.headline };
  return { title: a.headline, subject: null };
}

function Row({ a }: { a: Announcement }) {
  const { title, subject } = displayTitle(a);
  const chip = (
    <span className={`tag${a.category === "pledge" ? " amber" : ""}`} data-category={a.category}>
      {categoryLabel(a.category)}
    </span>
  );
  return (
    <li className="ann-row">
      <span className="muted">{shortDay(a.ts.slice(0, 10))}</span> {chip}{" "}
      {a.body ? (
        <details>
          <summary>
            <strong>{title}</strong>
            {subject && <span className="muted"> · {subject}</span>}
          </summary>
          <p>{a.body}</p>
        </details>
      ) : (
        <strong>{title}</strong>
      )}
      {a.url && (
        <>
          {" "}
          <a href={a.url} target="_blank" rel="noopener noreferrer">PDF</a>
        </>
      )}
    </li>
  );
}

export default function Announcements({ symbol }: { symbol: string }) {
  const [categories, setCategories] = useState<AnnouncementCategory[]>([]);
  const [category, setCategory] = useState<string | null>(null);
  const [showRoutine, setShowRoutine] = useState(false);
  const [rows, setRows] = useState<Announcement[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.get<AnnouncementCategory[]>("/news/categories").then(setCategories).catch(() => undefined);
  }, []);

  useEffect(() => {
    let stale = false;
    setRows(null);
    const q = new URLSearchParams({ symbol, include_hidden: showRoutine ? "1" : "0", limit: "100" });
    if (category) q.set("category", category);
    api
      .get<Announcement[]>(`/news/announcements?${q}`)
      .then((r) => {
        if (!stale) {
          setRows(r);
          setError(null);
        }
      })
      .catch((e) => !stale && setError(e instanceof ApiError ? e.message : String(e)));
    return () => {
      stale = true;
    };
  }, [symbol, category, showRoutine]);

  const chips = [...categories.filter((c) => !c.hidden).map((c) => c.category), "other"];
  return (
    <div>
      <div className="chip-row" role="group" aria-label="Filter by type">
        {chips.map((c) => (
          <button key={c} type="button" className="filter-chip" aria-pressed={category === c} onClick={() => setCategory(category === c ? null : c)}>
            {categoryLabel(c)}
          </button>
        ))}
      </div>
      <label>
        <input type="checkbox" checked={showRoutine} onChange={(e) => setShowRoutine(e.target.checked)} /> Show routine filings
      </label>
      {error && <p className="neg">{error}</p>}
      {rows === null && !error && <p className="muted">Loading…</p>}
      {rows && rows.length === 0 && (
        <p className="muted">No announcements{category ? " of this type" : ""} yet. They are fetched in the background (see Jobs).</p>
      )}
      {rows && rows.length > 0 && <ul className="ann-list">{rows.map((a) => <Row key={a.id} a={a} />)}</ul>}
    </div>
  );
}
