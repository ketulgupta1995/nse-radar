import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { Alert, AlertKind } from "../api/types";
import { notifyAlertsChanged } from "../components/AlertBadge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toaster";
import { cn } from "@/lib/utils";
import { relativeAgo } from "../lib/dates";

export const SEVERITY: Record<Alert["severity"], { icon: string; label: string }> = {
  info: { icon: "ℹ️", label: "For your information" },
  warn: { icon: "⚠️", label: "Needs a look" },
  critical: { icon: "🛑", label: "Act now" },
};

export default function Alerts() {
  const navigate = useNavigate();
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

  const kindLabel = (k: string) => kinds.find((x) => x.kind === k)?.label ?? k;
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
