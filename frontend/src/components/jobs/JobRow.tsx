import { Fragment, useState } from "react";
import { Badge } from "@/components/ui/badge";
import type { JobInfo, SchedulePatch } from "../../api/types";
import RunHistory, { Progress, StatusChip, fmtDuration, relTime } from "./RunHistory";
import ScheduleEditor, { scheduleWords } from "./ScheduleEditor";
import { Button } from "@/components/ui/button";

interface Props {
  job: JobInfo;
  historyKey: number;
  onRun: (name: string) => void;
  onStop: (runId: number) => void;
  onSchedule: (name: string, patch: SchedulePatch) => void;
  onOpen: (runId: number) => void;
}

export default function JobRow({ job, historyKey, onRun, onStop, onSchedule, onOpen }: Props) {
  const [editing, setEditing] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const s = job.schedule;
  const off = job.source_enabled === false;
  return (
    <Fragment>
      <tr>
        <td>
          <button type="button" className="link" onClick={() => setExpanded((e) => !e)} aria-expanded={expanded}>
            {expanded ? "▾" : "▸"} {job.title}
          </button>
          <div className="muted">{job.description}</div>
        </td>
        <td className={off ? "muted" : ""}>
          {scheduleWords(s)} {off && <Badge>source off</Badge>}{" "}
          <Button variant="outline" size="sm" type="button" onClick={() => setEditing((e) => !e)}>
            Edit
          </Button>
        </td>
        <td>
          <label>
            <input
              type="checkbox"
              aria-label={`Enable ${job.title}`}
              checked={s.enabled}
              disabled={s.kind === "manual"}
              onChange={(e) => onSchedule(job.name, { enabled: e.target.checked })}
            />
          </label>
        </td>
        <td>{s.enabled && s.next_run_at ? relTime(s.next_run_at) : "—"}</td>
        <td>
          {job.running ? (
            <>
              <StatusChip status="running" /> <Progress done={job.running.done} total={job.running.total} />
            </>
          ) : job.last_run ? (
            <button type="button" className="link" onClick={() => onOpen(job.last_run!.id)}>
              <StatusChip status={job.last_run.status} /> {job.last_run.ok}/{job.last_run.failed}/
              {job.last_run.skipped} · {fmtDuration(job.last_run.duration_s)}
            </button>
          ) : (
            <span className="muted">never run</span>
          )}
        </td>
        <td>
          {job.running ? (
            <Button variant="outline" size="sm" type="button" onClick={() => onStop(job.running!.id)}>
              Stop
            </Button>
          ) : (
            <Button variant="outline" size="sm" type="button" onClick={() => onRun(job.name)}>
              Run now
            </Button>
          )}
        </td>
      </tr>
      {editing && (
        <tr>
          <td colSpan={6}>
            <ScheduleEditor
              schedule={s}
              onCancel={() => setEditing(false)}
              onSave={(p) => {
                onSchedule(job.name, p);
                setEditing(false);
              }}
            />
          </td>
        </tr>
      )}
      {expanded && (
        <tr>
          <td colSpan={6}>
            <RunHistory job={job.name} limit={20} refreshKey={historyKey} onOpen={onOpen} />
          </td>
        </tr>
      )}
    </Fragment>
  );
}
