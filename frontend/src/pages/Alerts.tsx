import type { ColumnDef } from "@tanstack/react-table";
import { Check } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { Alert, AlertKind } from "../api/types";
import { notifyAlertsChanged } from "../components/AlertBadge";
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toaster";
import { cn } from "@/lib/utils";
import { relativeAgo } from "../lib/dates";
import { useIsPhone } from "../lib/useIsPhone";

export const SEVERITY: Record<Alert["severity"], { icon: string; label: string }> = {
  info: { icon: "ℹ️", label: "For your information" },
  warn: { icon: "⚠️", label: "Needs a look" },
  critical: { icon: "🛑", label: "Act now" },
};

export default function Alerts() {
  const navigate = useNavigate();
  const phone = useIsPhone();
  const [view, setView] = useState<"unseen" | "all">("unseen");
  const [kind, setKind] = useState("");
  const [kinds, setKinds] = useState<AlertKind[]>([]);
  const [alerts, setAlerts] = useState<Alert[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const msg = (e: unknown) => (e instanceof ApiError ? e.message : String(e));

  useEffect(() => {
    api.get<AlertKind[]>("/alerts/kinds").then(setKinds).catch(() => undefined);
  }, []);

  const load = useCallback(async () => {
    const q = new URLSearchParams({ limit: "200" });
    if (view === "unseen") q.set("unseen", "1");
    if (kind) q.set("kind", kind);
    try {
      setAlerts(await api.get<Alert[]>(`/alerts?${q}`));
      setError(null);
    } catch (e) {
      setError(msg(e));
    }
  }, [view, kind]);

  useEffect(() => {
    load();
  }, [load]);

  const markAll = async () => {
    try {
      await api.post("/alerts/seen", {});
      notifyAlertsChanged();
      await load();
      toast.success("All alerts marked as seen.");
    } catch (e) {
      setError(msg(e));
    }
  };

  const open = async (a: Alert) => {
    if (!a.seen_at) {
      try {
        await api.post("/alerts/seen", { ids: [a.id] });
        notifyAlertsChanged();
      } catch (e) {
        setError(msg(e));
        return;
      }
    }
    if (a.link) navigate(a.link);
    else await load();
  };

  const markOne = useCallback(
    async (a: Alert) => {
      try {
        await api.post("/alerts/seen", { ids: [a.id] });
        notifyAlertsChanged();
        await load();
      } catch (e) {
        setError(msg(e));
      }
    },
    [load],
  );

  const kindLabel = useCallback((k: string) => kinds.find((x) => x.kind === k)?.label ?? k, [kinds]);
  const phoneColumns = useMemo<ColumnDef<Alert>[]>(
    () => [
      {
        accessorKey: "message",
        header: "Alert",
        enableSorting: false,
        meta: { phone: "title" },
        cell: ({ row }) => (
          <span className={cn("break-words", !row.original.seen_at && "font-semibold")}>
            <span role="img" aria-label={SEVERITY[row.original.severity].label}>{SEVERITY[row.original.severity].icon}</span>{" "}
            {row.original.message}
          </span>
        ),
      },
      {
        accessorKey: "created_at",
        header: "When",
        meta: { phone: "subtitle" },
        cell: ({ row }) => (
          <span>
            {row.original.symbol && <span className="font-mono">{row.original.symbol} · </span>}
            {relativeAgo(row.original.created_at)} · {kindLabel(row.original.kind)}
          </span>
        ),
      },
      {
        id: "seen",
        header: "Status",
        enableSorting: false,
        cell: ({ row }) =>
          row.original.seen_at ? (
            <span className="text-muted-foreground">Seen</span>
          ) : (
            <Button
              variant="outline"
              className="h-10"
              aria-label={`Mark seen: ${row.original.message}`}
              onClick={(e) => {
                e.stopPropagation();
                void markOne(row.original);
              }}
            >
              <Check size={14} /> Mark seen
            </Button>
          ),
      },
    ],
    [kindLabel, markOne],
  );

  if (phone) {
    return (
      <div className="min-w-0">
        <h1>Alerts</h1>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <span role="group" aria-label="Which alerts" className="flex gap-1">
            <Button variant={view === "unseen" ? "default" : "outline"} className="h-10" aria-pressed={view === "unseen"} onClick={() => setView("unseen")}>Unseen</Button>
            <Button variant={view === "all" ? "default" : "outline"} className="h-10" aria-pressed={view === "all"} onClick={() => setView("all")}>All</Button>
          </span>
          <Button variant="outline" className="h-10" onClick={markAll}>Mark all seen</Button>
          <Select aria-label="Type" className="h-10 w-full" value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">All types</option>
            {kinds.map((k) => (
              <option key={k.kind} value={k.kind}>{k.label}</option>
            ))}
          </Select>
        </div>
        {error && <p className="neg" role="alert">{error}</p>}
        {alerts === null && !error && <Skeleton className="h-24" />}
        {alerts && (
          <DataTable
            columns={phoneColumns}
            data={alerts}
            getRowId={(a) => String(a.id)}
            onRowClick={(a) => void open(a)}
            rowClassName={(a) =>
              cn(
                !a.seen_at && "border-l-4",
                !a.seen_at && (a.severity === "critical" ? "border-l-danger" : a.severity === "warn" ? "border-l-warning" : "border-l-accent"),
              )
            }
            emptyTitle={view === "unseen" ? "No unseen alerts. You're up to date." : "No alerts yet."}
          />
        )}
      </div>
    );
  }

  return (
    <div>
      <h1>Alerts</h1>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <span role="group" aria-label="Which alerts" className="flex gap-1">
          <Button variant={view === "unseen" ? "default" : "outline"} size="sm" aria-pressed={view === "unseen"} onClick={() => setView("unseen")}>Unseen</Button>
          <Button variant={view === "all" ? "default" : "outline"} size="sm" aria-pressed={view === "all"} onClick={() => setView("all")}>All</Button>
        </span>
        <label className="flex items-center gap-2">
          Type
          <Select aria-label="Type" value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">All types</option>
            {kinds.map((k) => (
              <option key={k.kind} value={k.kind}>{k.label}</option>
            ))}
          </Select>
        </label>
        <Button variant="outline" onClick={markAll}>Mark all seen</Button>
      </div>
      {error && <p className="neg" role="alert">{error}</p>}
      {alerts === null && !error && <Skeleton className="h-24" />}
      {alerts && alerts.length === 0 && (
        <EmptyState title={view === "unseen" ? "No unseen alerts. You're up to date." : "No alerts yet."} />
      )}
      {alerts && alerts.length > 0 && (
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          {alerts.map((a) => (
            <li
              key={a.id}
              className={cn(
                "rounded-card border border-border bg-card",
                !a.seen_at && "border-l-4 font-semibold",
                !a.seen_at && (a.severity === "critical" ? "border-l-danger" : a.severity === "warn" ? "border-l-warning" : "border-l-accent"),
              )}
            >
              <button
                type="button"
                className="block w-full cursor-pointer border-0 bg-transparent px-3 py-2.5 text-left text-inherit"
                style={{ font: "inherit" }}
                onClick={() => open(a)}
              >
                <span role="img" aria-label={SEVERITY[a.severity].label}>{SEVERITY[a.severity].icon}</span>{" "}
                <span>{a.message}</span>{" "}
                <span className="muted font-normal">
                  {kindLabel(a.kind)} · {relativeAgo(a.created_at)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
