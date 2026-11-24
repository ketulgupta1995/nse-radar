import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "../api/client";
import type { DataHealth as Health, JobInfo, JobsResponse, SchedulePatch, SourceInfo } from "../api/types";
import Explain from "../components/Explain";
import DataChecks from "../components/jobs/DataChecks";
import DataHealth from "../components/jobs/DataHealth";
import JobRow, { JobCard } from "../components/jobs/JobRow";
import { useCloud } from "@/lib/cloud";
import { useIsPhone } from "@/lib/useIsPhone";
import RunDrawer from "../components/jobs/RunDrawer";
import RunHistory, { usePoll } from "../components/jobs/RunHistory";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { toast } from "@/components/ui/toaster";

function groupTitle(g: string, labels: Record<string, string>): string {
  if (g === "app") return "App";
  if (g.startsWith("source:")) return labels[g.slice(7)] ?? g.slice(7);
  return g;
}

function sourceOff(jobs: JobInfo[]): boolean {
  return jobs.length > 0 && jobs.every((j) => j.source_enabled === false);
}

export default function Jobs() {
  const phone = useIsPhone();
  const { runtime } = useCloud();
  const [data, setData] = useState<JobsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openRun, setOpenRun] = useState<number | null>(null);
  const [historyKey, setHistoryKey] = useState(0);
  const [tab, setTab] = useState<"jobs" | "checks">("jobs");
  const [health, setHealth] = useState<Health | null>(null);
  const [labels, setLabels] = useState<Record<string, string>>({});

  const loadHealth = useCallback(async () => {
    try {
      setHealth(await api.get<Health>("/data/health"));
      const sources = await api.get<SourceInfo[]>("/sources");
      setLabels(Object.fromEntries(sources.map((s) => [s.name, s.label])));
    } catch {
      /* the health strip is optional */
    }
  }, []);
  useEffect(() => {
    void loadHealth();
  }, [loadHealth]);

  const load = useCallback(async () => {
    try {
      setData(await api.get<JobsResponse>("/jobs"));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }, []);
  const anyRunning = data?.jobs.some((j) => j.running) ?? false;
  usePoll(load, anyRunning ? 5000 : 30000);

  async function act(fn: () => Promise<unknown>, done?: string) {
    try {
      await fn();
      setError(null);
      if (done) toast.success(done);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
    setHistoryKey((k) => k + 1);
    await load();
  }

  const handlers = {
    onOpen: setOpenRun,
    onRun: (n: string) =>
      act(async () => {
        const r = await api.post<{ run_id: number }>(`/jobs/${n}/run`, {});
        setOpenRun(r.run_id);
      }, "Job started."),
    onStop: (id: number) => act(() => api.post(`/jobs/runs/${id}/stop`), "Stop requested."),
    onSchedule: (n: string, p: SchedulePatch) => act(() => api.put(`/jobs/${n}/schedule`, p), "Schedule saved."),
  };

  const groups = new Map<string, JobInfo[]>();
  for (const j of data?.jobs ?? []) groups.set(j.group, [...(groups.get(j.group) ?? []), j]);
  const ordered = [...groups.keys()].sort((a, b) => (a === "app" ? -1 : b === "app" ? 1 : a.localeCompare(b)));

  return (
    <div>
      <h1>Jobs</h1>
      {runtime === "vercel" && (
        <p className="muted">
          Jobs run in the cloud worker (GitHub Actions), twice a day on schedule and within a couple of minutes when you press Run now.
        </p>
      )}
      <p>
        <label>
          <input
            type="checkbox"
            checked={data?.paused ?? false}
            onChange={(e) => act(() => api.post("/jobs/pause", { paused: e.target.checked }), e.target.checked ? "All schedules paused." : "Schedules resumed.")}
          />{" "}
          Pause all schedules
        </label>
        <Explain text="Running jobs finish; nothing new starts on its own. Run now still works." />
      </p>
      <DataHealth health={health} labels={labels} />
      <Tabs value={tab} onValueChange={(v) => setTab(v as "jobs" | "checks")}>
        <TabsList>
          <TabsTrigger value="jobs">Jobs</TabsTrigger>
          <TabsTrigger value="checks">
            Data checks{health && health.checks_open > 0 ? ` (${health.checks_open})` : ""}
          </TabsTrigger>
        </TabsList>
      </Tabs>
      {error && <p className="neg">{error}</p>}
      {tab === "checks" && <DataChecks labels={labels} onChanged={loadHealth} />}
      {tab === "jobs" && !data && !error && <Skeleton className="h-32" />}
      {tab === "jobs" && ordered.map((g) => (
        <Card key={g} className="mb-3 p-3">
        <details open={g === "app" || undefined} className="job-group">
          <summary>
            <h2 style={{ display: "inline" }}>{groupTitle(g, labels)}</h2>
            {sourceOff(groups.get(g)!) && <Badge className="ml-2">off</Badge>}
          </summary>
          {phone ? (
            <div className="mt-2">
              {groups.get(g)!.map((j) => (
                <JobCard key={j.name} job={j} historyKey={historyKey} {...handlers} />
              ))}
            </div>
          ) : (
          <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Job</th>
                <th>Schedule</th>
                <th>On</th>
                <th>Next run</th>
                <th>Last run (ok/failed/skipped)</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {groups.get(g)!.map((j) => (
                <JobRow key={j.name} job={j} historyKey={historyKey} {...handlers} />
              ))}
            </tbody>
          </table>
          </div>
          )}
        </details>
        </Card>
      ))}
      {tab === "jobs" && (
        <>
          <h2>Recent runs (all jobs)</h2>
          <RunHistory limit={20} refreshKey={historyKey} onOpen={setOpenRun} />
        </>
      )}
      {openRun !== null && (
        <RunDrawer
          runId={openRun}
          onClose={() => setOpenRun(null)}
          onChanged={() => act(async () => undefined)}
          onOpenRun={setOpenRun}
        />
      )}
    </div>
  );
}
