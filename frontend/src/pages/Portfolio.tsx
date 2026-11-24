import type { ColumnDef } from "@tanstack/react-table";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { Position } from "../api/types";
import ExitChecklist from "../components/checklist/ExitChecklist";
import Explain from "../components/Explain";
import Num from "../components/Num";
import ResultsBadge from "../components/ResultsBadge";
import PlanBar from "../components/positions/PlanBar";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toaster";
import { useIsPhone } from "@/lib/useIsPhone";

function Stat({ label, children, help }: { label: string; children: React.ReactNode; help?: string }) {
  return (
    <Card className="flex flex-col gap-1 p-3">
      <div className="text-xs text-muted-foreground">
        {label}
        {help && <Explain text={help} />}
      </div>
      <div className="text-lg font-semibold">{children}</div>
    </Card>
  );
}

function timeStop(days: number | null) {
  if (days === null) return <span className="muted">—</span>;
  if (days < 0) return <span className="neg">{-days}d overdue</span>;
  return <span className={days < 7 ? "amber" : ""}>{days}d left</span>;
}

function EditRow({ p, onDone }: { p: Position; onDone: (p: Position) => void }) {
  const [stop, setStop] = useState(String(p.stop ?? ""));
  const [target, setTarget] = useState(String(p.target ?? ""));
  const [err, setErr] = useState<string | null>(null);
  const save = async () => {
    try {
      const body: Record<string, number> = {};
      if (stop) body.stop = Number(stop);
      if (target) body.target = Number(target);
      const updated = await api.put<Position>(`/positions/${p.id}`, body);
      toast.success(`Updated stop and target for ${p.symbol}.`);
      onDone(updated);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    }
  };
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      <Input className="w-24" aria-label="Stop" type="number" inputMode="decimal" step="any" value={stop} onChange={(e) => setStop(e.target.value)} />
      <Input className="w-24" aria-label="Target" type="number" inputMode="decimal" step="any" value={target} onChange={(e) => setTarget(e.target.value)} />
      <Button size="sm" onClick={() => void save()}>Save</Button>
      <Button variant="ghost" size="sm" onClick={() => onDone(p)}>Cancel</Button>
      {err && <span className="neg">{err}</span>}
    </span>
  );
}

export default function Portfolio() {
  const [rows, setRows] = useState<Position[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const [closing, setClosing] = useState<Position | null>(null);
  const phone = useIsPhone();

  const load = useCallback(async () => {
    try {
      setRows(await api.get<Position[]>("/positions?status=open"));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const columns = useMemo<ColumnDef<Position>[]>(
    () => [
      {
        accessorKey: "symbol",
        header: "Stock",
        meta: { phone: "title" },
        cell: ({ row }) => (
          <span className="inline-flex flex-wrap items-center gap-2">
            <Link to={`/stock/${row.original.symbol}`} className="font-mono">{row.original.symbol}</Link>
            <ResultsBadge next={row.original.next_results} />
          </span>
        ),
      },
      { accessorKey: "qty", header: "Qty", meta: { right: true, phone: "hide" }, cell: ({ row }) => <span className="num">{row.original.qty}</span> },
      {
        accessorKey: "entry_price",
        header: phone ? "Qty × avg price" : "Entry",
        meta: { right: true },
        cell: ({ row }) =>
          phone ? (
            <span className="num">{row.original.qty} × <Num value={row.original.entry_price} kind="inr" digits={2} /></span>
          ) : (
            <Num value={row.original.entry_price} kind="inr" digits={2} />
          ),
      },
      { accessorKey: "last_close", header: "Last", meta: { right: true }, sortUndefined: "last", cell: ({ row }) => <Num value={row.original.last_close} kind="inr" digits={2} /> },
      {
        accessorKey: "pnl_inr",
        header: "Profit / loss",
        meta: { right: true },
        sortUndefined: "last",
        cell: ({ row }) => (
          <>
            <Num value={row.original.pnl_inr} kind="inr" colored /> <Num value={row.original.pnl_pct} kind="pct" colored />
          </>
        ),
      },
      {
        accessorKey: "r_multiple",
        header: () => (
          <>
            R multiple
            <Explain text="Profit measured in units of the risk you took. +2R = twice what you risked." />
          </>
        ),
        meta: { right: true, label: "R multiple" },
        sortUndefined: "last",
        cell: ({ row }) => (row.original.r_multiple === null ? "—" : <Num value={row.original.r_multiple} kind="plain" digits={1} colored />),
      },
      {
        id: "plan",
        header: "Stop → target",
        enableSorting: false,
        cell: ({ row }) => {
          const p = row.original;
          if (editing === p.id)
            return (
              <EditRow
                p={p}
                onDone={(u) => {
                  setEditing(null);
                  setRows((cur) => (cur ? cur.map((r) => (r.id === u.id ? u : r)) : cur));
                }}
              />
            );
          return p.stop != null && p.target != null ? (
            <PlanBar stop={p.stop} entry={p.entry_price} target={p.target} last={p.last_close} />
          ) : (
            <span className="muted">no stop/target</span>
          );
        },
      },
      {
        id: "held",
        header: "Held / time stop",
        enableSorting: false,
        cell: ({ row }) => <>{row.original.days_held}d · {timeStop(row.original.days_to_time_stop)}</>,
      },
      {
        id: "actions",
        header: "",
        enableSorting: false,
        meta: { phone: "subtitle" },
        cell: ({ row }) => (
          <span className="mt-1 flex flex-wrap gap-1">
            <Button variant="outline" size="sm" className={phone ? "min-h-10" : undefined} onClick={() => setEditing(row.original.id)}>Edit stop/target</Button>
            <Button variant="outline" size="sm" className={phone ? "min-h-10" : undefined} onClick={() => setClosing(row.original)}>Close…</Button>
          </span>
        ),
      },
    ],
    [editing, phone],
  );

  if (error) return <p className="neg">{error}</p>;
  if (!rows)
    return (
      <div>
        <h1>Portfolio</h1>
        <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-[72px]" />)}</div>
        <Skeleton className="h-48" />
      </div>
    );
  if (rows.length === 0) {
    return (
      <div>
        <h1>Portfolio</h1>
        <EmptyState title="No open positions.">Find ideas in the Screener, then use the checklist on a stock page.</EmptyState>
      </div>
    );
  }

  const invested = rows.reduce((a, p) => a + p.qty * p.entry_price, 0);
  const value = rows.reduce((a, p) => a + p.qty * (p.last_close ?? p.entry_price), 0);
  const pnl = value - invested;
  const risk = rows.reduce((a, p) => a + (p.stop != null ? p.qty * (p.entry_price - p.stop) : 0), 0);

  return (
    <div>
      <h1>Portfolio</h1>
      {phone ? (
        <Card className="mb-3 flex flex-col gap-2 p-3" aria-label="Portfolio summary">
          <div>
            <div className="text-xs text-muted-foreground">Current value</div>
            <div className="text-2xl font-semibold"><Num value={value} kind="inr" /></div>
          </div>
          <dl className="m-0 grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
            <dt className="text-muted-foreground">Unrealised profit / loss</dt>
            <dd className="m-0 text-right"><Num value={pnl} kind="inr" colored /> <Num value={invested ? (pnl / invested) * 100 : 0} kind="pct" colored /></dd>
            <dt className="text-muted-foreground">Capital invested</dt>
            <dd className="m-0 text-right"><Num value={invested} kind="inr" /></dd>
            <dt className="text-muted-foreground">
              Total open risk
              <Explain text="Rupees you would lose if every stop-loss is hit, measured from your entry prices." />
            </dt>
            <dd className="m-0 text-right"><Num value={risk} kind="inr" /></dd>
          </dl>
        </Card>
      ) : (
        <div className="mb-4 grid grid-cols-4 gap-3">
          <Stat label="Capital invested"><Num value={invested} kind="inr" /></Stat>
          <Stat label="Current value"><Num value={value} kind="inr" /></Stat>
          <Stat label="Unrealised profit / loss">
            <Num value={pnl} kind="inr" colored /> <Num value={invested ? (pnl / invested) * 100 : 0} kind="pct" colored />
          </Stat>
          <Stat label="Total open risk" help="Rupees you would lose if every stop-loss is hit, measured from your entry prices.">
            <Num value={risk} kind="inr" />
          </Stat>
        </div>
      )}
      <DataTable columns={columns} data={rows} getRowId={(r) => String(r.id)} showDensityToggle />
      {closing && (
        <ExitChecklist
          position={closing}
          onClose={() => setClosing(null)}
          onClosed={() => {
            toast.success(`Closed ${closing.symbol}.`);
            setClosing(null);
            void load();
          }}
        />
      )}
    </div>
  );
}
