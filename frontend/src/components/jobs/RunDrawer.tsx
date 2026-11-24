import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "../../api/client";
import type { LogLine, RunDetail } from "../../api/types";
import { Progress, StatusChip, fmtDuration, relTime, usePoll } from "./RunHistory";
import { Button } from "@/components/ui/button";
import { useIsPhone } from "@/lib/useIsPhone";
import { cn } from "@/lib/utils";

interface Props {
  runId: number;
  onClose: () => void;
  onChanged: () => void;
  onOpenRun: (id: number) => void;
}

export default function RunDrawer({ runId, onClose, onChanged, onOpenRun }: Props) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [logs, setLogs] = useState<LogLine[]>([]);
  const [error, setError] = useState<string | null>(null);
  const lastId = useRef(0);
  const logBox = useRef<HTMLDivElement>(null);
  const phone = useIsPhone();

  useEffect(() => {
    setRun(null);
    setLogs([]);
    lastId.current = 0;
  }, [runId]);

  const load = useCallback(async () => {
    try {
      const r = await api.get<RunDetail>(`/jobs/runs/${runId}`);
      const fresh = await api.get<LogLine[]>(`/jobs/runs/${runId}/logs?after_id=${lastId.current}`);
      if (fresh.length) {
        lastId.current = fresh[fresh.length - 1].id;
        setLogs((l) => [...l, ...fresh]);
      }
      setRun(r);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }, [runId]);

  const active = run === null || run.status === "queued" || run.status === "running";
  usePoll(load, active ? 2000 : null);

  useEffect(() => {
    const el = logBox.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [logs]);

  async function act(path: string) {
    setError(null);
    try {
      const res = await api.post<{ run_id?: number }>(path);
      onChanged();
      if (res && res.run_id) onOpenRun(res.run_id);
      else await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }

  return (
    <aside
      className={cn(
        "fixed inset-y-0 right-0 z-20 overflow-auto bg-card p-4",
        phone ? "left-0 w-screen" : "w-[min(520px,100vw)] border-l border-border shadow-[-4px_0_16px_#0003]",
      )}
      aria-label="Run details"
    >
      <div className="flex items-center justify-between gap-2">
        <h2>
          Run #{runId} {run && <span className="muted">{run.job}</span>}
        </h2>
        <Button variant="outline" size="sm" type="button" onClick={onClose} aria-label="Close">
          ✕
        </Button>
      </div>
      {error && <p className="neg">{error}</p>}
      {run && (
        <>
          <p>
            <StatusChip status={run.status} /> started by <b>{run.trigger}</b>
            {run.retry_of ? ` (retry of #${run.retry_of})` : ""}
          </p>
          <p className="muted">
            Queued {relTime(run.queued_at)} · started {relTime(run.started_at)} · finished{" "}
            {relTime(run.finished_at)} · took {fmtDuration(run.duration_s)}
          </p>
          <p>
            <Progress done={run.done} total={run.total} /> ok {run.ok} · failed {run.failed} · skipped {run.skipped}
          </p>
          {run.message && <p>{run.message}</p>}
          {(run.status === "queued" || run.status === "running") && (
            <Button variant="outline" size="sm" type="button" onClick={() => act(`/jobs/runs/${runId}/stop`)}>
              Stop
            </Button>
          )}
          {run.items_failed.length > 0 && (
            <>
              <h3>Failed items</h3>
              <Button variant="outline" size="sm" type="button" onClick={() => act(`/jobs/runs/${runId}/retry`)}>
                Retry failed ({run.items_failed.length})
              </Button>
              <div className="scroll-box">
                <table>
                  <thead>
                    <tr>
                      <th>Item</th>
                      <th>What went wrong</th>
                    </tr>
                  </thead>
                  <tbody>
                    {run.items_failed.map((i) => (
                      <tr key={i.key}>
                        <td>{i.key}</td>
                        <td>{i.detail}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}
      <h3>Log</h3>
      <div className={cn("log", phone && "max-h-[50vh]")} ref={logBox}>
        {logs.length === 0 && <span className="muted">No log lines yet.</span>}
        {logs.map((l) => (
          <div key={l.id} className={`log-${l.level}`}>
            {l.at.slice(11, 19)} {l.msg}
          </div>
        ))}
      </div>
    </aside>
  );
}
