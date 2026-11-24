import type { ColumnDef } from "@tanstack/react-table";
import { Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { Idea, IdeasPage, SignalGroup, SignalsSummary } from "../api/types";
import Explain from "../components/Explain";
import Num from "../components/Num";
import IdeaPanel, { R, StatusPill, ideaStatus, seenLabel } from "../components/track/IdeaPanel";
import StopTargetBar from "../components/track/StopTargetBar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { shortDay, todayIso } from "@/lib/dates";
import { cn } from "@/lib/utils";

export { R };

const EMPTY = "Nothing logged yet. New ideas are recorded each evening after the screens run.";
const TOO_EARLY = "Fewer than 30 finished ideas: the numbers can swing a lot by luck.";
const GROUPED = "A stock picked again while its first idea is still running is the same trade, so it counts once.";
const PER_PAGE = 50;

const COLUMNS: [string, string][] = [
  ["Closed", "Ideas that have finished: they hit the stop, the target or the time limit."],
  ["Still open", "Ideas that have been entered and are still being followed."],
  ["Win rate", "Share of finished ideas that made money."],
  ["Avg return", "Average % gain or loss per finished idea, after the entry gap."],
  ["Avg R", "Average result in units of risk. +1R means you gained as much as you risked at the stop."],
  ["Beat Nifty by", "Average % by which the idea beat the Nifty index over the same days."],
  ["Avg days", "Average number of days an idea was held."],
];

const TABS = [
  ["open", "Open"],
  ["pending", "Pending entry"],
  ["closed", "Closed"],
  ["all", "All"],
] as const;
const RANGES = [
  ["7", "7 days"],
  ["30", "30 days"],
  ["90", "90 days"],
  ["0", "All time"],
] as const;

function TooEarly() {
  return (
    <>
      <Badge variant="warning" className="ml-1.5">too early</Badge>
      <Explain text={TOO_EARLY} />
    </>
  );
}

function daysBefore(iso: string, n: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - n);
  return d.toISOString().slice(0, 10);
}

function FromChips({ idea }: { idea: Idea }) {
  const labels = [...new Set(idea.seen.map(seenLabel))];
  const extra = labels.length - 2;
  return (
    <span className="inline-flex items-center gap-1">
      {labels.slice(0, 2).map((l) => (
        <Badge key={l} className="font-normal text-foreground">{l}</Badge>
      ))}
      {extra > 0 && <Badge className="bg-transparent font-normal" title={labels.slice(2).join(", ")}>+{extra}</Badge>}
    </span>
  );
}

function isTyping(t: EventTarget | null): boolean {
  return t instanceof HTMLElement && (t.isContentEditable || ["INPUT", "SELECT", "TEXTAREA"].includes(t.tagName));
}

function LoggedIdeas({ screens }: { screens: SignalGroup[] }) {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "open";
  const q = params.get("q") ?? "";
  const source = params.get("source") ?? "";
  const screenId = params.get("screen") ?? "";
  const range = params.get("range") ?? "90";
  const page = Number(params.get("page") ?? "0") || 0;

  const [qInput, setQInput] = useState(q);
  const [data, setData] = useState<IdeasPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selId, setSelId] = useState<number | null>(null);

  const update = (patch: Record<string, string>, keepPage = false) => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        for (const [k, v] of Object.entries(patch)) {
          if (v === "") next.delete(k);
          else next.set(k, v);
        }
        if (!keepPage) next.delete("page");
        return next;
      },
      { replace: true },
    );
  };

  // debounce the search box into the URL
  useEffect(() => {
    if (qInput === q) return;
    const t = setTimeout(() => update({ q: qInput.trim() }), 250);
    return () => clearTimeout(t);
  }, [qInput]);

  useEffect(() => {
    const p = new URLSearchParams();
    if (tab !== "all") p.set("status", tab);
    if (source) p.set("source", source);
    if (screenId) p.set("screen_id", screenId);
    if (q) p.set("q", q);
    if (range !== "0") p.set("since", daysBefore(todayIso(), Number(range)));
    p.set("limit", String(PER_PAGE));
    p.set("offset", String(page * PER_PAGE));
    let live = true;
    api
      .get<IdeasPage>(`/signals/ideas?${p.toString()}`)
      .then((d) => {
        if (!live) return;
        setData(d);
        setSelId((cur) => (cur != null && d.rows.some((r) => r.id === cur) ? cur : (d.rows[0]?.id ?? null)));
      })
      .catch((e) => live && setError(e instanceof ApiError ? e.message : String(e)));
    return () => {
      live = false;
    };
  }, [tab, source, screenId, q, range, page]);

  const rows = useMemo(() => data?.rows ?? [], [data]);

  // keyboard: j/k move, / searches, Esc clears
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e.target)) {
        if (e.key === "Escape" && e.target instanceof HTMLElement) e.target.blur();
        return;
      }
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "/") {
        e.preventDefault();
        document.getElementById("idea-search")?.focus();
      } else if (e.key === "Escape") {
        setSelId(null);
      } else if ((e.key === "j" || e.key === "k") && rows.length) {
        setSelId((cur) => {
          const i = rows.findIndex((r) => r.id === cur);
          const next = i < 0 ? 0 : Math.max(0, Math.min(rows.length - 1, i + (e.key === "j" ? 1 : -1)));
          return rows[next].id;
        });
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [rows]);

  const closedTab = tab === "closed";
  const columns = useMemo<ColumnDef<Idea>[]>(
    () => [
      {
        id: "symbol",
        header: "Stock",
        accessorFn: (i) => i.symbol,
        cell: ({ row }) => (
          <div className="py-1.5">
            <Link to={`/stock/${row.original.symbol}`} className="font-mono font-medium" onClick={(e) => e.stopPropagation()}>
              {row.original.symbol}
            </Link>
            <div className="max-w-44 truncate text-xs text-muted-foreground">{row.original.name ?? ""}</div>
          </div>
        ),
      },
      {
        id: "logged",
        header: "Logged",
        accessorFn: (i) => i.first_as_of,
        cell: ({ row }) => {
          const days = new Set(row.original.seen.map((s) => s.as_of)).size;
          return (
            <div>
              <div className="num">{shortDay(row.original.first_as_of)}</div>
              {days > 1 && <div className="text-xs text-muted-foreground">+{days - 1} more day{days > 2 ? "s" : ""}</div>}
            </div>
          );
        },
      },
      { id: "from", header: "From", enableSorting: false, cell: ({ row }) => <FromChips idea={row.original} /> },
      { id: "status", header: "Status", accessorFn: ideaStatus, cell: ({ row }) => <StatusPill status={ideaStatus(row.original)} /> },
      closedTab
        ? {
            id: "ended",
            header: "Ended",
            accessorFn: (i) => i.outcome?.exit_date ?? "",
            cell: ({ row }) => (
              <span>
                {row.original.outcome?.exit_reason ?? "—"}{" "}
                <span className="num text-muted-foreground">{shortDay(row.original.outcome?.exit_date)}</span>
              </span>
            ),
          }
        : {
            id: "progress",
            header: () => <>Stop to target<Explain text="Where today's price sits between your stop (left) and target (right). The thin tick is the entry price." /></>,
            enableSorting: false,
            cell: ({ row }) => {
              const i = row.original;
              const entered = ideaStatus(i) !== "pending";
              return <StopTargetBar stop={i.planned_stop} target={i.planned_target} entry={i.planned_entry} current={entered ? i.current_price : null} />;
            },
          },
      {
        id: "return",
        header: () => <>Return<Explain text={closedTab ? "% gain or loss when the idea ended, after costs." : "% gain or loss so far, valued at the last close, after costs."} /></>,
        meta: { right: true },
        sortUndefined: "last",
        accessorFn: (i) => i.outcome?.return_pct ?? undefined,
        cell: ({ row }) => <Num value={row.original.outcome?.return_pct} kind="pct" colored />,
      },
      {
        id: "r",
        header: () => <>R<Explain text={COLUMNS[4][1].replace("Average result", "Result")} /></>,
        meta: { right: true },
        sortUndefined: "last",
        accessorFn: (i) => i.outcome?.r_multiple ?? undefined,
        cell: ({ row }) => <R value={row.original.outcome?.r_multiple} />,
      },
    ],
    [closedTab],
  );

  if (error) return <p className="neg">{error}</p>;

  const counts = data?.counts;
  const tabCount = (k: string) =>
    !counts ? null : k === "all" ? counts.open + counts.pending + counts.closed + counts.no_data : counts[k as keyof typeof counts];
  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PER_PAGE));
  const selected = rows.find((r) => r.id === selId) ?? null;

  return (
    <Card>
      <CardHeader><CardTitle>Every logged idea</CardTitle></CardHeader>

      <div role="tablist" aria-label="Idea status" className="flex flex-wrap gap-1 border-b border-border">
        {TABS.map(([k, label]) => (
          <button
            key={k}
            role="tab"
            type="button"
            aria-selected={tab === k}
            onClick={() => update({ tab: k === "open" ? "" : k })}
            className={cn(
              "-mb-px flex cursor-pointer items-center gap-2 border-0 border-b-2 border-transparent bg-transparent px-3 py-2 text-sm text-muted-foreground hover:text-foreground",
              tab === k && "border-accent text-foreground",
            )}
          >
            {label}
            <span className={cn("num rounded-full bg-muted px-1.5 text-xs", tab === k && "bg-accent/15 text-accent")}>{tabCount(k) ?? "…"}</span>
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-3 py-3">
        <label className="relative">
          <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input
            id="idea-search"
            type="search"
            value={qInput}
            onChange={(e) => setQInput(e.target.value)}
            placeholder="Find a stock, e.g. TCS"
            aria-label="Find a stock"
            className="w-64 pl-8"
          />
        </label>
        <label className="flex items-center gap-2 text-muted-foreground">
          Source
          <Select value={source} onChange={(e) => update(e.target.value === "shortlist" ? { source: e.target.value, screen: "" } : { source: e.target.value })}>
            <option value="">All</option>
            <option value="screen">Screens</option>
            <option value="shortlist">Shortlist</option>
          </Select>
        </label>
        <label className="flex items-center gap-2 text-muted-foreground">
          Screen
          <Select value={screenId} onChange={(e) => update({ screen: e.target.value })}>
            <option value="">All</option>
            {screens.map((g) => <option key={g.key} value={g.key.replace("screen:", "")}>{g.label}</option>)}
          </Select>
        </label>
        <div role="group" aria-label="Logged within" className="inline-flex overflow-hidden rounded-control border border-border">
          {RANGES.map(([v, label]) => (
            <button
              key={v}
              type="button"
              aria-pressed={range === v}
              onClick={() => update({ range: v === "90" ? "" : v })}
              className={cn(
                "cursor-pointer border-0 border-r border-border bg-transparent px-2.5 py-1 text-sm text-muted-foreground last:border-r-0 hover:bg-muted",
                range === v && "bg-accent/15 font-medium text-accent",
              )}
            >
              {label}
            </button>
          ))}
        </div>
        <span className="flex-1" />
        <span className="text-xs text-muted-foreground">{data ? `${total} idea${total === 1 ? "" : "s"} in this view` : ""}</span>
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)_360px] items-start gap-4">
        <div className="min-w-0">
          <DataTable
            columns={columns}
            data={rows}
            loading={!data}
            getRowId={(i) => String(i.id)}
            onRowClick={(i) => setSelId(i.id)}
            rowClassName={(i) => (i.id === selId ? "bg-accent/10 shadow-[inset_3px_0_0_var(--accent)] hover:bg-accent/10" : undefined)}
            emptyTitle="No ideas match these filters. Try a longer date range or clear the search."
          />
          <div className="flex flex-wrap items-center justify-between gap-2 pt-3 text-xs text-muted-foreground">
            <span>{total ? `Showing ${page * PER_PAGE + 1}–${Math.min(total, (page + 1) * PER_PAGE)} of ${total}` : ""}</span>
            <span>
              <kbd className="num rounded border border-border px-1">j</kbd> <kbd className="num rounded border border-border px-1">k</kbd> move ·{" "}
              <kbd className="num rounded border border-border px-1">/</kbd> search · <kbd className="num rounded border border-border px-1">Esc</kbd> clear
            </span>
            <span className="flex items-center gap-2">
              <Button variant="outline" size="sm" disabled={page === 0} onClick={() => update({ page: String(page - 1) }, true)}>Previous</Button>
              Page {page + 1} of {pages}
              <Button variant="outline" size="sm" disabled={page >= pages - 1} onClick={() => update({ page: String(page + 1) }, true)}>Next</Button>
            </span>
          </div>
        </div>
        <aside className="sticky top-4 rounded-card border border-border p-4" aria-live="polite">
          <IdeaPanel idea={selected} />
        </aside>
      </div>
    </Card>
  );
}

export default function TrackRecord() {
  const [summary, setSummary] = useState<SignalsSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.get<SignalsSummary>("/signals/summary").then(setSummary).catch((e) => setError(e instanceof ApiError ? e.message : String(e)));
  }, []);

  const groupCols = useMemo<ColumnDef<SignalGroup>[]>(
    () => [
      {
        id: "group",
        header: "Group",
        enableSorting: false,
        cell: ({ row }) => (
          <>
            {row.original.label}
            {!row.original.enough && <TooEarly />}
          </>
        ),
      },
      { id: "closed", header: () => <>Closed<Explain text={COLUMNS[0][1]} /></>, enableSorting: false, meta: { right: true }, cell: ({ row }) => <span className="num">{row.original.n_closed}</span> },
      { id: "open", header: () => <>Still open<Explain text={COLUMNS[1][1]} /></>, enableSorting: false, meta: { right: true }, cell: ({ row }) => <span className="num">{row.original.n_open}</span> },
      { id: "win", header: () => <>Win rate<Explain text={COLUMNS[2][1]} /></>, enableSorting: false, meta: { right: true }, cell: ({ row }) => <Num value={row.original.hit_rate_pct} kind="pct" digits={0} /> },
      { id: "ret", header: () => <>Avg return<Explain text={COLUMNS[3][1]} /></>, enableSorting: false, meta: { right: true }, cell: ({ row }) => <Num value={row.original.avg_return_pct} kind="pct" colored /> },
      { id: "r", header: () => <>Avg R<Explain text={COLUMNS[4][1]} /></>, enableSorting: false, meta: { right: true }, cell: ({ row }) => <R value={row.original.avg_r} /> },
      { id: "beat", header: () => <>Beat Nifty by<Explain text={COLUMNS[5][1]} /></>, enableSorting: false, meta: { right: true }, cell: ({ row }) => <Num value={row.original.avg_excess_pct} kind="pct" colored /> },
      { id: "days", header: () => <>Avg days<Explain text={COLUMNS[6][1]} /></>, enableSorting: false, meta: { right: true }, cell: ({ row }) => <Num value={row.original.avg_days} digits={1} /> },
    ],
    [],
  );

  if (error) return <p className="neg">{error}</p>;
  if (!summary)
    return (
      <div>
        <h1>Track record</h1>
        <Skeleton className="h-40" />
      </div>
    );

  const cov = summary.coverage;
  const empty = summary.n_signals === 0;
  const screens = summary.groups.filter((g) => g.kind === "screen");

  return (
    <div>
      <h1>Track record</h1>
      <p className="muted">
        Every new idea is recorded the day it appears, then followed with your stop, target and time stop. This is the honest test: none of it was known when the idea was logged.
      </p>

      {empty ? (
        <EmptyState title={EMPTY} />
      ) : (
        <>
          {cov.first_day && (
            <p>
              Logging since {cov.first_day}: {cov.days_logged} of {cov.trading_days} trading days
              <Explain text="Days the app was switched off can't be logged afterwards, so some trading days are missing." />
            </p>
          )}

          <Card className="mb-4">
            <CardHeader><CardTitle>How the ideas did</CardTitle></CardHeader>
            <DataTable
              columns={groupCols}
              data={summary.groups}
              getRowId={(g) => g.key}
              rowClassName={(g) => (g.enough ? undefined : "opacity-55")}
            />
            <p className="mb-0 mt-2 text-xs text-muted-foreground">
              {summary.n_signals} loggings grouped into {summary.n_ideas} ideas
              <Explain text={GROUPED} />
            </p>
          </Card>

          <LoggedIdeas screens={screens} />
        </>
      )}
    </div>
  );
}
