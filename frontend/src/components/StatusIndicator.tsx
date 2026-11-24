import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { JobsStatus } from "../api/types";
import { formatDay } from "../lib/dates";

export const STATUS_CHANGED = "status-changed";
const FAST_MS = 5_000;
const SLOW_MS = 60_000;

/** Ask the indicator to look again now (after "Refresh now"). */
export function notifyStatusChanged(): void {
  window.dispatchEvent(new Event(STATUS_CHANGED));
}

const nice = (job: string) => job.replace(/_/g, " ");

export default function StatusIndicator() {
  const [status, setStatus] = useState<JobsStatus | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async () => {
    if (timer.current) clearTimeout(timer.current);
    let next = SLOW_MS;
    try {
      const s = await api.get<JobsStatus>("/jobs/status");
      setStatus(s);
      if (s.updating) next = FAST_MS;
    } catch {
      /* keep the last status; the next poll retries */
    }
    timer.current = setTimeout(load, next);
  }, []);

  useEffect(() => {
    void load();
    window.addEventListener(STATUS_CHANGED, load);
    return () => {
      if (timer.current) clearTimeout(timer.current);
      window.removeEventListener(STATUS_CHANGED, load);
    };
  }, [load]);

  if (!status) return <div className="status-indicator muted">Checking data…</div>;
  if (status.updating) {
    const run = status.background.running;
    const progress = run?.total ? ` ${run.done}/${run.total}` : "";
    return (
      <Link to="/jobs" className="status-indicator updating">
        Updating{run ? `: ${nice(run.job)}${progress}` : ""}…
      </Link>
    );
  }
  return <div className="status-indicator muted">Data as of {formatDay(status.last_trading_date)}</div>;
}
