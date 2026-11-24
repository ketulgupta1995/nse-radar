import { useCallback, useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import { api } from "../api/client";

export const ALERTS_CHANGED = "alerts-changed";
const POLL_MS = 60_000;

/** Tell the badge to refresh now (after alerts are marked seen). */
export function notifyAlertsChanged(): void {
  window.dispatchEvent(new Event(ALERTS_CHANGED));
}

export default function AlertBadge() {
  const [unseen, setUnseen] = useState<number | null>(null);

  const load = useCallback(() => {
    api
      .get<{ unseen: number }>("/alerts/count")
      .then((r) => setUnseen(r.unseen))
      .catch(() => undefined); // keep the last number; the next poll retries
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, POLL_MS);
    window.addEventListener(ALERTS_CHANGED, load);
    return () => {
      clearInterval(timer);
      window.removeEventListener(ALERTS_CHANGED, load);
    };
  }, [load]);

  const label = unseen === null ? "Alerts" : unseen === 0 ? "No new alerts" : `${unseen} new alert${unseen === 1 ? "" : "s"}`;
  return (
    <NavLink to="/alerts" className={`flex items-center gap-1.5 rounded-control px-2 py-1.5 text-sm no-underline text-foreground hover:bg-muted${unseen ? " font-semibold" : ""}`} aria-label={label} title={label}>
      <span aria-hidden="true">🔔</span>
      {unseen !== null && unseen > 0 && <span className="rounded-full bg-danger px-1.5 text-xs text-white">{unseen > 99 ? "99+" : unseen}</span>}
      <span className="badge-text">{unseen ? "new" : unseen === 0 ? "No new alerts" : "Alerts"}</span>
    </NavLink>
  );
}
