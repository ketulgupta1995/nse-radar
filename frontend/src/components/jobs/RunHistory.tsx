import type { ColumnDef } from "@tanstack/react-table";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { RunStatus, RunSummary } from "../../api/types";
import { api } from "../../api/client";
import { StatusChip as Chip } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { Progress as Bar } from "@/components/ui/progress";

/** Calls `fn` now and then every `ms` while `ms` is not null. */
export function usePoll(fn: () => void | Promise<void>, ms: number | null): void {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => {
    void ref.current();
    if (ms === null) return;
    const t = setInterval(() => void ref.current(), ms);
    return () => clearInterval(t);
  }, [ms]);
}

export function relTime(iso: string | null): string {
  if (!iso) return "—";
  const diff = (new Date(iso).getTime() - Date.now()) / 1000;
  const abs = Math.abs(diff);
  const unit = abs < 90 ? `${Math.round(abs)} s` : abs < 5400 ? `${Math.round(abs / 60)} min` : abs < 129600 ? `${Math.round(abs / 3600)} h` : `${Math.round(abs / 86400)} d`;
  return diff >= 0 ? `in ${unit}` : `${unit} ago`;
}

export function fmtDuration(s: number | null): string {
  if (s === null) return "—";
  if (s < 60) return `${s.toFixed(0)} s`;
  if (s < 3600) return `${Math.floor(s / 60)} m ${Math.round(s % 60)} s`;
  return `${Math.floor(s / 3600)} h ${Math.round((s % 3600) / 60)} m`;
}

export function StatusChip({ status }: { status: RunStatus }) {
  return <Chip status={status} />;
}

export function Progress({ done, total }: { done: number; total: number | null }) {
  const label = `${done}${total ? `/${total}` : ""}`;
  return <Bar value={done} max={total ?? 0} label={label} />;
}

interface Props {
  job?: string;
  limit?: number;
  refreshKey?: number;
  onOpen: (runId: number) => void;
}

export default function RunHistory({ job, limit = 20, refreshKey = 0, onOpen }: Props) {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const load = useCallback(async () => {
    const q = `limit=${limit}${job ? `&job=${encodeURIComponent(job)}` : ""}`;
    setRuns(await api.get<RunSummary[]>(`/jobs/runs?${q}`));
  }, [job, limit]);
  useEffect(() => {
    void load();
  }, [load, refreshKey]);
  usePoll(load, runs.some((r) => r.status === "running" || r.status === "queued") ? 5000 : 30000);

  const columns = useMemo<ColumnDef<RunSummary>[]>(
    () => [
      { accessorKey: "id", header: "#" },
      ...(job ? [] : [{ accessorKey: "job", header: "Job" } satisfies ColumnDef<RunSummary>]),
      { accessorKey: "status", header: "Status", cell: ({ row }) => <StatusChip status={row.original.status} /> },
      { id: "started", header: "Started", enableSorting: false, cell: ({ row }) => relTime(row.original.started_at ?? row.original.queued_at) },
      { id: "took", header: "Took", enableSorting: false, cell: ({ row }) => fmtDuration(row.original.duration_s) },
      { id: "counts", header: "ok / failed / skipped", enableSorting: false, cell: ({ row }) => <>{row.original.ok} / {row.original.failed} / {row.original.skipped}</> },
      { accessorKey: "trigger", header: "Why it ran" },
    ],
    [job],
  );
  return (
    <DataTable
      columns={columns}
      data={runs}
      onRowClick={(r) => onOpen(r.id)}
      getRowId={(r) => String(r.id)}
      emptyTitle="No runs yet."
    />
  );
}
