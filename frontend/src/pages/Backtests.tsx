import type { ColumnDef } from "@tanstack/react-table";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useMatch, useNavigate, useParams } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { Backtest, BacktestListItem, RunSummary } from "../api/types";
import BacktestForm from "../components/backtests/BacktestForm";
import EquityChart from "../components/backtests/EquityChart";
import MetricCards from "../components/backtests/MetricCards";
import TradesTable from "../components/backtests/TradesTable";
import WarningsBox from "../components/backtests/WarningsBox";
import Num from "../components/Num";
import { Badge, StatusChip } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { Skeleton } from "@/components/ui/skeleton";
import { useCloud } from "@/lib/cloud";
import { useIsPhone } from "@/lib/useIsPhone";
import { toast } from "@/components/ui/toaster";

const CLOUD_WAIT = "Waiting for the cloud worker (usually 1–2 min)";
const POLL_MS = 1500;
const msg = (e: unknown) => (e instanceof ApiError ? e.message : String(e));

const KIND_LABEL: Record<string, string> = { explore: "Training", final: "Final", legacy: "Old" };

/** Explore runs only have training numbers; final and old runs show the test period. */
const shown = (b: BacktestListItem) => (b.kind === "explore" ? b.metrics?.is : b.metrics?.oos);
const suffix = (b: BacktestListItem) =>
  b.kind === "explore" ? <span className="text-muted-foreground"> (training)</span> : null;

function List({ onNew }: { onNew: () => void }) {
  const [items, setItems] = useState<BacktestListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.get<BacktestListItem[]>("/backtests").then(setItems).catch((e) => setError(msg(e)));
  }, []);
  const phone = useIsPhone();
  const { runtime } = useCloud();
  const columns = useMemo<ColumnDef<BacktestListItem>[]>(
    () => [
      { id: "name", header: "Name", meta: { phone: "title" }, accessorFn: (b) => b.name || `Backtest ${b.id}`, cell: ({ row }) => <Link to={`/backtests/${row.original.id}`}>{row.original.name || `Backtest ${row.original.id}`}</Link> },
      {
        accessorKey: "status", header: "Status",
        cell: ({ row }) => {
          const b = row.original;
          if (phone && b.status === "done") return null; // a phone card only shows status while it matters
          return (
            <>
              <StatusChip status={b.status} />
              {b.status === "queued" && runtime === "vercel" && <span className="block text-muted-foreground">{CLOUD_WAIT}</span>}
            </>
          );
        },
      },
      { id: "created_at", header: "Started", accessorFn: (b) => b.created_at, cell: ({ row }) => row.original.created_at.slice(0, 16).replace("T", " ") },
      {
        id: "kind", header: "Kind", meta: { phone: "subtitle" }, accessorFn: (b) => KIND_LABEL[b.kind] ?? b.kind,
        cell: ({ row }) => {
          const label = KIND_LABEL[row.original.kind] ?? row.original.kind;
          return phone ? <Badge variant={row.original.kind === "final" ? "info" : "neutral"}>{label}</Badge> : label;
        },
      },
      { id: "cagr", header: "Yearly return", meta: { right: true }, sortUndefined: "last", accessorFn: (b) => shown(b)?.cagr ?? undefined, cell: ({ row }) => <><Num value={shown(row.original)?.cagr} kind="pct" colored />{suffix(row.original)}</> },
      { id: "excess", header: "Beat the index by", meta: { right: true }, sortUndefined: "last", accessorFn: (b) => shown(b)?.excess ?? undefined, cell: ({ row }) => <><Num value={shown(row.original)?.excess} kind="pct" colored />{suffix(row.original)}</> },
      // phone cards also show the worst fall and the trade count (laptop columns stay as they were)
      ...(phone
        ? ([
            { id: "max_drawdown", header: "Worst fall", sortUndefined: "last", accessorFn: (b) => shown(b)?.max_drawdown ?? undefined, cell: ({ row }) => <Num value={shown(row.original)?.max_drawdown} kind="pct" colored /> },
            { id: "trades", header: "Trades", sortUndefined: "last", accessorFn: (b) => shown(b)?.trades ?? undefined, cell: ({ row }) => <Num value={shown(row.original)?.trades} /> },
          ] satisfies ColumnDef<BacktestListItem>[])
        : []),
    ],
    [phone, runtime],
  );
  return (
    <>
      <p>
        <Button onClick={onNew}>New backtest</Button>
      </p>
      {error && <p className="neg" role="alert">{error}</p>}
      <DataTable
        columns={columns}
        data={items ?? []}
        loading={items === null && !error}
        getRowId={(b) => String(b.id)}
        emptyTitle="No backtests yet."
        emptyHint="A backtest replays a buy rule on past prices to see how it would have done."
      />
    </>
  );
}

function Result({ id }: { id: number }) {
  const navigate = useNavigate();
  const [bt, setBt] = useState<Backtest | null>(null);
  const [run, setRun] = useState<RunSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [confirmFinal, setConfirmFinal] = useState(false);
  const [parentOk, setParentOk] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async () => {
    try {
      const b = await api.get<Backtest>(`/backtests/${id}`);
      setBt(b);
      if (b.status === "queued" || b.status === "running") {
        if (b.run_id) setRun(await api.get<RunSummary>(`/jobs/runs/${b.run_id}`));
        timer.current = setTimeout(load, POLL_MS);
      } else setRun(null);
    } catch (e) {
      setError(msg(e));
    }
  }, [id]);

  useEffect(() => {
    void load();
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [load]);

  const stop = async () => {
    if (bt?.run_id) {
      await api.post(`/jobs/runs/${bt.run_id}/stop`).then(() => toast.success("Stop requested.")).catch((e) => setError(msg(e)));
    }
  };
  const parentId = bt?.parent_id ?? null;
  useEffect(() => {
    setParentOk(false);
    if (parentId == null) return;
    api.get<Backtest>(`/backtests/${parentId}`).then(() => setParentOk(true)).catch(() => setParentOk(false));
  }, [parentId]);

  const runFinal = async () => {
    try {
      const made = await api.post<{ id: number }>(`/backtests/${id}/final`);
      navigate(`/backtests/${made.id}`);
    } catch (e) {
      setConfirmFinal(false);
      setError(msg(e));
    }
  };
  const remove = async () => {
    try {
      await api.del(`/backtests/${id}`);
      toast.success("Backtest deleted.");
      navigate("/backtests");
    } catch (e) {
      setError(msg(e));
    }
  };

  if (error) return <p className="neg" role="alert">{error}</p>;
  if (!bt) return <Skeleton className="h-48" />;
  const running = bt.status === "queued" || bt.status === "running";
  return (
    <>
      <p><Link to="/backtests">← All backtests</Link></p>
      <h2>{bt.name || `Backtest ${bt.id}`}</h2>
      {bt.kind === "final" && (
        <p>
          <Badge variant="info">Final test · attempt {bt.attempt ?? 1}</Badge>
          {parentOk && bt.parent_id != null && <> <Link to={`/backtests/${bt.parent_id}`}>← training run #{bt.parent_id}</Link></>}
        </p>
      )}
      {bt.kind === "legacy" && (
        <p className="text-muted-foreground">
          Made before training and test periods were separated; the test part may have been seen while tweaking.
        </p>
      )}
      {running && (
        <p role="status">
          {bt.status === "queued" ? "Waiting in the queue…" : "Running…"}
          {run?.total ? ` day ${run.done} of ${run.total}` : ""}{" "}
          <Button variant="outline" size="sm" onClick={stop}>Stop</Button>
        </p>
      )}
      {(bt.status === "failed" || bt.status === "cancelled") && <p className="neg">This backtest {bt.status}.</p>}
      <p className="text-muted-foreground">
        Stocks tested:{" "}
        {bt.config?.universe === "current" ? "today's Nifty 500" : "most-traded 500 at the time"}
      </p>
      <WarningsBox warnings={bt.warnings ?? []} />
      {bt.metrics && bt.equity && (
        <>
          <h3>Account value against the Nifty 500</h3>
          <EquityChart points={bt.equity} oosStart={bt.kind === "explore" ? null : bt.metrics.oos_start} />
          <MetricCards metrics={bt.metrics} kind={bt.kind} />
          {bt.kind === "explore" && bt.explore_runs > 1 && (
            <p className="text-muted-foreground">
              {bt.explore_runs} backtests have been run on this training period. The best of many always looks better than it really is.
            </p>
          )}
          {bt.kind === "explore" && bt.status === "done" && (
            <Card className="mb-4 max-w-xl">
              <p>
                <strong>
                  Test period {bt.metrics.oos_start ?? bt.config.oos_start} → {bt.config.end || "latest"} is still hidden.
                </strong>
              </p>
              {confirmFinal ? (
                <div role="group" aria-label="Confirm final test">
                  <p>
                    Run this once, when you've finished tweaking. If you change the rule after seeing the result, the test years stop being a fair check.
                  </p>
                  <Button onClick={runFinal}>Run final test</Button>{" "}
                  <Button variant="outline" onClick={() => setConfirmFinal(false)}>Not yet</Button>
                </div>
              ) : (
                <p>
                  <Button onClick={() => setConfirmFinal(true)}>Run final test</Button>{" "}
                  <Button variant="outline" onClick={() => navigate(`/backtests/new?from=${bt.id}`)}>Tweak and rerun</Button>
                </p>
              )}
            </Card>
          )}
          {bt.kind !== "explore" && (
            <p>
              <Button variant="outline" onClick={() => navigate(`/backtests/new?from=${bt.id}`)}>Tweak and rerun</Button>
            </p>
          )}
        </>
      )}
      {bt.trades && (
        <>
          <h3>Trades ({bt.trades.length})</h3>
          <TradesTable trades={bt.trades} />
        </>
      )}
      <p>
        {confirmDelete ? (
          <span role="group" aria-label="Confirm delete">
            Delete this backtest? <Button variant="danger" size="sm" onClick={remove}>Yes, delete</Button>{" "}
            <Button variant="outline" size="sm" onClick={() => setConfirmDelete(false)}>Keep it</Button>
          </span>
        ) : (
          <Button variant="outline" onClick={() => setConfirmDelete(true)}>Delete</Button>
        )}
      </p>
    </>
  );
}

export default function Backtests() {
  const { id } = useParams();
  const navigate = useNavigate();
  const isNew = useMatch("/backtests/new") !== null;
  return (
    <div className="backtests">
      <h1>Backtests</h1>
      {isNew ? (
        <BacktestForm
          onStarted={(n) => navigate(`/backtests/${n}`)}
          onBatchStarted={() => navigate("/backtests")}
          onCancel={() => navigate("/backtests")} />
      ) : id ? (
        <Result key={id} id={Number(id)} />
      ) : (
        <List onNew={() => navigate("/backtests/new")} />
      )}
    </div>
  );
}
