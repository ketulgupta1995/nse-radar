import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { DataHealth, SourceCoverage, SourceInfo } from "../api/types";
import { weekdaysBehind } from "../lib/dates";
import { Button } from "@/components/ui/button";

export const MIN_TRADING_DAYS = 20;

interface Priority {
  [capability: string]: unknown;
}

/** Job to run for `capability` on the top-priority enabled source (prefers a ".daily" variant). */
export function pickJob(capability: string, priority: Priority, sources: SourceInfo[]): string | null {
  const order = (priority[capability] as string[] | undefined) ?? [];
  for (const name of order) {
    const src = sources.find((s) => s.name === name && s.enabled);
    const jobs = src?.capabilities.find((c) => c.capability === capability)?.jobs ?? [];
    if (jobs.length) return jobs.find((j) => j.endsWith(".daily")) ?? jobs[0];
  }
  return null;
}

/** Trading days (Mon–Fri) the primary bars source spans, approximated from its first and last date. */
export function barDays(priority: Priority, coverage: SourceCoverage[]): number {
  const order = (priority.bars as string[] | undefined) ?? [];
  const row = coverage.find((c) => c.source === order[0]);
  if (!row?.first_date || !row.last_date) return 0;
  return weekdaysBehind(row.first_date, row.last_date) + 1;
}

interface Props {
  /** Changes whenever the page reloaded its data, so the checklist refreshes too. */
  reloadKey: number;
  onStarted: () => void;
}

interface State {
  universe: number;
  days: number;
  universeJob: string | null;
  barsJob: string | null;
}

export default function FirstRunPanel({ reloadKey, onStarted }: Props) {
  const [s, setS] = useState<State | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [started, setStarted] = useState<string[]>([]);

  useEffect(() => {
    let live = true;
    Promise.all([
      api.get<DataHealth>("/data/health"),
      api.get<Priority>("/sources/priority"),
      api.get<SourceInfo[]>("/sources"),
      api.get<SourceCoverage[]>("/sources/coverage?capability=bars"),
    ])
      .then(([health, priority, sources, coverage]) => {
        if (!live) return;
        setS({
          universe: health.universe,
          days: barDays(priority, coverage),
          universeJob: pickJob("universe", priority, sources),
          barsJob: pickJob("bars", priority, sources),
        });
      })
      .catch(() => live && setS(null)); // no panel if we can't tell
    return () => {
      live = false;
    };
  }, [reloadKey]);

  if (!s || s.days >= MIN_TRADING_DAYS) return null;

  const run = async (job: string | null) => {
    if (!job) return;
    setError(null);
    try {
      await api.post(`/jobs/${job}/run`);
      setStarted((x) => [...x, job]);
      onStarted();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };

  const step = (done: boolean, job: string | null, label: string) => (
    <li>
      <span aria-hidden="true">{done ? "✅" : "⬜"}</span> {label}{" "}
      {done ? (
        <span className="muted">done</span>
      ) : job ? (
        <Button variant="outline" size="sm" type="button" onClick={() => run(job)} disabled={started.includes(job)}>
          {started.includes(job) ? "Started…" : "Run"}
        </Button>
      ) : (
        <span className="muted">(no source is switched on for this, see Sources)</span>
      )}
    </li>
  );

  return (
    <section className="card first-run" aria-label="Getting started">
      <h2>Getting started</h2>
      <p>This app has little data yet. Do these in order:</p>
      <ol>
        {step(s.universe > 0, s.universeJob, "1. Load the stock list")}
        {step(s.days >= MIN_TRADING_DAYS, s.barsJob, `2. Load recent prices (${s.days} of ${MIN_TRADING_DAYS} days so far)`)}
        <li>
          <span aria-hidden="true">⏳</span> 3. Price history and fundamentals fill in by themselves over the next
          days. Leave the app running and watch it on the <Link to="/jobs">Jobs page</Link>.
        </li>
      </ol>
      {error && <p className="neg" role="alert">{error}</p>}
    </section>
  );
}
