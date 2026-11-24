import type { ColumnDef } from "@tanstack/react-table";
import { X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { Alert, Dashboard as DashboardData, DashboardSince, Health, JobsStatus, ShortlistItem } from "../api/types";
import Explain from "../components/Explain";
import FirstRunPanel from "../components/FirstRunPanel";
import Num from "../components/Num";
import ResultsBadge from "../components/ResultsBadge";
import { notifyStatusChanged } from "../components/StatusIndicator";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDay } from "../lib/dates";

const POLL_MS = 5_000;
const msg = (e: unknown) => (e instanceof ApiError ? e.message : String(e));

export function sinceCount(s: DashboardSince | null): number {
  if (!s) return 0;
  return (
    s.alerts.length +
    s.new_in_screens.reduce((n, x) => n + x.symbols.length, 0) +
    s.positions.length +
    s.announcements.length
  );
}

const DISMISS_KEY = "since-dismissed";
function readDismissed(): string | null {
  try {
    return localStorage.getItem(DISMISS_KEY);
  } catch {
    return null;
  }
}

/** Dismissing is remembered for this visit only: a new "last visit" time shows the banner again. */
export function SinceStrip({ since }: { since: DashboardSince | null }) {
  const [dismissed, setDismissed] = useState(readDismissed);
  if (!since || sinceCount(since) === 0 || dismissed === since.last_visit_at) return null;
  const moves = since.positions.filter((p) => p.change_pct_since_visit !== 0);
  const dismiss = () => {
    try {
      localStorage.setItem(DISMISS_KEY, since.last_visit_at);
    } catch {
      /* ignore */
    }
    setDismissed(since.last_visit_at);
  };
  return (
    <section className="mb-4 flex items-start justify-between gap-3 rounded-card border border-accent bg-card px-4 py-2.5" aria-label="Since you were away">
      <div>
      <strong>Since you were away</strong> <span className="muted">(since {since.last_visit_at.slice(0, 16).replace("T", " ")})</span>
      <div>
        {since.alerts.length > 0 && (
          <details>
            <summary>{since.alerts.length} new alert{since.alerts.length === 1 ? "" : "s"}</summary>
            <ul>{since.alerts.map((a) => <li key={a.id}>{a.message}</li>)}</ul>
          </details>
        )}
        {since.new_in_screens.length > 0 && (
          <details>
            <summary>{since.new_in_screens.reduce((n, x) => n + x.symbols.length, 0)} new in screens</summary>
            <ul>
              {since.new_in_screens.map((s) => (
                <li key={s.screen}>
                  {s.screen}: {s.symbols.map((sym) => <Link key={sym} to={`/stock/${sym}`}>{sym} </Link>)}
                </li>
              ))}
            </ul>
          </details>
        )}
        {moves.length > 0 && (
          <details>
            <summary>{moves.length} position move{moves.length === 1 ? "" : "s"}</summary>
            <ul>
              {moves.map((p) => (
                <li key={p.symbol}>
                  <Link to={`/stock/${p.symbol}`}>{p.symbol}</Link> <Num value={p.change_pct_since_visit} kind="pct" colored />
                </li>
              ))}
            </ul>
          </details>
        )}
        {since.announcements.length > 0 && (
          <details>
            <summary>{since.announcements.length} announcement{since.announcements.length === 1 ? "" : "s"}</summary>
            <ul>
              {since.announcements.map((a) => (
                <li key={a.id}>
                  <Link to={`/stock/${a.symbol}`}>{a.symbol}</Link>: {a.headline}
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
      </div>
      <Button variant="ghost" size="icon" aria-label="Dismiss" onClick={dismiss}>
        <X size={16} />
      </Button>
    </section>
  );
}

const COMPONENT_LABELS: Record<string, string> = {
  rs: "Relative strength", trend: "Trend", fundamentals: "Business quality", backtest: "Screen track record",
};

function breakdownOf(item: ShortlistItem): string {
  return Object.entries(item.components)
    .map(([k, v]) => `${COMPONENT_LABELS[k] ?? k}: ${Math.round(v)}/100`)
    .join(" · ");
}

export function ShortlistTable({ items, loading }: { items: ShortlistItem[]; loading: boolean }) {
  const nav = useNavigate();
  const columns = useMemo<ColumnDef<ShortlistItem>[]>(
    () => [
      { id: "rank", header: "#", enableSorting: false, cell: ({ row }) => <span className="muted">{row.index + 1}</span> },
      {
        accessorKey: "symbol",
        header: "Stock",
        cell: ({ row }) => (
          <>
            <Link to={`/stock/${row.original.symbol}`} onClick={(e) => e.stopPropagation()}>
              <strong className="font-mono">{row.original.symbol}</strong>
            </Link>{" "}
            <span className="muted">{row.original.name}</span>{" "}
            <ResultsBadge next={row.original.next_results} />
          </>
        ),
      },
      {
        accessorKey: "score",
        header: "Score",
        meta: { right: true },
        cell: ({ row }) => {
          const it = row.original;
          const breakdown = breakdownOf(it);
          return (
            <span title={breakdown}>
              <span className="score-bar" aria-label={`Score ${it.score.toFixed(0)} out of 100`}>
                <span style={{ width: `${Math.max(0, Math.min(100, it.score))}%` }} />
              </span>{" "}
              <span className="num">{it.score.toFixed(0)}</span>
              <Explain text={`Score out of 100 against the other candidates. ${breakdown}`} />
            </span>
          );
        },
      },
      {
        id: "why",
        header: "Why it is here",
        enableSorting: false,
        cell: ({ row }) => (
          <div className="flex flex-wrap gap-1">
            {row.original.reasons.map((r) => <span key={r} className="chip">{r}</span>)}
            {row.original.screens.map((sc) => <span key={sc} className="chip screen">{sc}</span>)}
          </div>
        ),
      },
    ],
    [],
  );
  return (
    <DataTable
      columns={columns}
      data={items}
      loading={loading}
      showDensityToggle
      onRowClick={(r) => nav(`/stock/${r.symbol}`)}
      getRowId={(r) => r.symbol}
      emptyTitle="No candidates yet"
      emptyHint="Run a screen on the Screener page to fill this list."
    />
  );
}

function Kpi({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <Card className="flex flex-col gap-1 p-3">
      <div className="text-xs text-muted-foreground">
        {label}
        {hint && <Explain text={hint} />}
      </div>
      <div className="text-lg font-semibold">{children}</div>
    </Card>
  );
}

export function KpiStrip({ data }: { data: DashboardData | null }) {
  if (!data) {
    return (
      <div className="mb-4 grid grid-cols-4 gap-3">
        {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-[72px]" />)}
      </div>
    );
  }
  const { positions, alerts, data: d } = data;
  const value = positions.open > 0 ? positions.invested + positions.pnl : null;
  const status = d.updating ? "Updating…" : d.stale ? "Out of date" : "Up to date";
  return (
    <div className="mb-4 grid grid-cols-4 gap-3">
      <Kpi label="Portfolio value" hint="Money invested plus profit or loss so far, on open positions.">
        <Num value={value} kind="inr" />
      </Kpi>
      <Kpi label="Day P&L" hint="Today's change on open positions. Not available yet: the app only tracks profit since you bought.">
        <span className="muted">n/a</span>
      </Kpi>
      <Kpi label="Open alerts">
        <Num value={alerts.length} />
      </Kpi>
      <Kpi label="Data">
        <span className={d.stale ? "neg" : undefined}>{status}</span>
        <span className="text-xs font-normal text-muted-foreground"> · {formatDay(d.last_trading_date)}</span>
      </Kpi>
    </div>
  );
}

export function AlertList({ alerts }: { alerts: Alert[] }) {
  if (alerts.length === 0) return <EmptyState title="Nothing needs your attention." />;
  return (
    <ul>
      {alerts.map((a) => (
        <li key={a.id} className={a.severity === "critical" ? "neg" : undefined}>
          {a.link ? <Link to={a.link}>{a.message}</Link> : a.message}
        </li>
      ))}
    </ul>
  );
}

export default function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [health, setHealth] = useState("checking backend…");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await api.get<DashboardData>("/dashboard"));
      setReloadKey((k) => k + 1);
      setError(null);
    } catch (e) {
      setError(msg(e));
    }
  }, []);

  useEffect(() => {
    void load();
    api
      .get<Health>("/health")
      .then((h) => setHealth(h.ok ? "backend ok" : "backend not ok"))
      .catch((e: Error) => setHealth(`backend error: ${e.message}`));
  }, [load]);

  // While updating, watch the job status and reload the page's numbers once it finishes.
  const updating = refreshing || !!data?.data.updating;
  useEffect(() => {
    if (!updating) return;
    const tick = async () => {
      try {
        const s = await api.get<JobsStatus>("/jobs/status");
        if (!s.updating) {
          setRefreshing(false);
          await load();
          return;
        }
      } catch {
        /* try again */
      }
      timer.current = setTimeout(tick, POLL_MS);
    };
    timer.current = setTimeout(tick, POLL_MS);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [updating, load]);

  // Leaving the page (or the tab) marks "last visit". Not on load, so a reload keeps the summary.
  useEffect(() => {
    const visit = () => void api.post("/dashboard/visit").catch(() => undefined);
    const onHide = () => {
      if (document.visibilityState === "hidden") visit();
    };
    document.addEventListener("visibilitychange", onHide);
    return () => {
      document.removeEventListener("visibilitychange", onHide);
      visit();
    };
  }, []);

  const refresh = async () => {
    setError(null);
    try {
      await api.post("/jobs/refresh");
      setRefreshing(true);
      notifyStatusChanged();
    } catch (e) {
      setError(msg(e));
    }
  };

  return (
    <div className="dashboard">
      <h1>Dashboard</h1>
      {error && <p className="neg" role="alert">{error}</p>}
      <FirstRunPanel reloadKey={reloadKey} onStarted={() => { setRefreshing(true); notifyStatusChanged(); }} />
      {data && <SinceStrip since={data.since} />}
      <div className="mb-4 flex flex-wrap items-center gap-x-6 gap-y-2">
        <span className={data?.data.stale ? "stale" : undefined}>
          Prices up to {formatDay(data?.data.last_trading_date)}
          {data?.data.stale ? " (out of date)" : ""}
        </span>
        {updating && <span role="status">Updating…</span>}
        {!!data?.data.checks_open && (
          <Link to="/jobs">{data.data.checks_open} price check{data.data.checks_open === 1 ? "" : "s"} need a look</Link>
        )}
        <Button variant="outline" onClick={refresh} disabled={refreshing}>Refresh now</Button>
      </div>

      <KpiStrip data={data} />

      <div className="mb-4 grid grid-cols-[minmax(0,1fr)_minmax(0,2fr)] items-start gap-4">
        <Card>
          <CardHeader><CardTitle>Needs attention</CardTitle></CardHeader>
          {data ? <AlertList alerts={data.alerts} /> : <Skeleton className="h-16" />}
          <p><Link to="/alerts">All alerts</Link></p>
        </Card>

        <Card>
          <CardHeader><CardTitle>Today's shortlist{updating ? " (updating…)" : ""}</CardTitle></CardHeader>
          <p className="disclaimer">Ideas to research, not advice. Use the checklist before any trade.</p>
          <ShortlistTable items={data?.shortlist ?? []} loading={!data} />
        </Card>
      </div>

      <Card className="mb-4">
        <CardHeader><CardTitle>My positions</CardTitle></CardHeader>
        {data ? (
          <div className="grid grid-cols-4 gap-3">
            <Kpi label="Open positions"><Num value={data.positions.open} /></Kpi>
            <Kpi label="Money invested"><Num value={data.positions.invested} kind="inr" /></Kpi>
            <Kpi label="Profit or loss so far">
              <Num value={data.positions.pnl} kind="inr" colored />{" "}
              <Num value={data.positions.pnl_pct} kind="pct" colored />
            </Kpi>
            <Kpi label="Money at risk" hint="What you would lose if every open position hit its stop-loss.">
              <Num value={data.positions.open_risk} kind="inr" />
            </Kpi>
          </div>
        ) : (
          <Skeleton className="h-16" />
        )}
        <p><Link to="/positions">Go to Portfolio</Link></p>
      </Card>

      <footer className="page-footer">{health}</footer>
    </div>
  );
}
