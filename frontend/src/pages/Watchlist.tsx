import type { ColumnDef } from "@tanstack/react-table";
import { ChevronDown, ChevronUp } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useIsPhone } from "../lib/useIsPhone";
import { ApiError, api } from "../api/client";
import type { WatchItem } from "../api/types";
import Num from "../components/Num";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toaster";

export default function Watchlist() {
  const [items, setItems] = useState<WatchItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const phone = useIsPhone();

  const load = useCallback(() => {
    api
      .get<WatchItem[]>("/watchlist")
      .then(setItems)
      .catch((e) => setError(e instanceof ApiError ? e.message : String(e)));
  }, []);
  useEffect(load, [load]);

  const remove = useCallback(async (symbol: string) => {
    try {
      await api.del(`/watchlist/${symbol}`);
      setItems((cur) => (cur ? cur.filter((i) => i.symbol !== symbol) : cur));
      toast.success(`${symbol} removed from watchlist`);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : String(e));
    }
  }, []);

  const columns = useMemo<ColumnDef<WatchItem>[]>(
    () => [
      {
        accessorKey: "symbol",
        header: "Stock",
        cell: ({ row }) => <Link to={`/stock/${row.original.symbol}`} className="font-mono">{row.original.symbol}</Link>,
      },
      { accessorKey: "name", header: "Name", cell: ({ row }) => row.original.name ?? "—" },
      {
        id: "close",
        header: "Last close",
        meta: { right: true },
        sortUndefined: "last",
        accessorFn: (r) => r.last_close ?? undefined,
        cell: ({ row }) => <Num value={row.original.last_close} kind="inr" digits={2} />,
      },
      { accessorKey: "added_at", header: "Added", cell: ({ row }) => row.original.added_at.slice(0, 10) },
      {
        id: "added_close",
        header: "Close when added",
        meta: { right: true },
        sortUndefined: "last",
        accessorFn: (r) => r.added_close ?? undefined,
        cell: ({ row }) => <Num value={row.original.added_close} kind="inr" digits={2} />,
      },
      {
        id: "since",
        header: "Change since added",
        meta: { right: true },
        sortUndefined: "last",
        accessorFn: (r) => (r.added_close && r.last_close ? (r.last_close / r.added_close - 1) * 100 : undefined),
        cell: ({ row }) => {
          const { added_close: a, last_close: l } = row.original;
          return <Num value={a && l ? (l / a - 1) * 100 : null} kind="pct" colored />;
        },
      },
      { accessorKey: "note", header: "Note", cell: ({ row }) => row.original.note ?? "" },
      {
        id: "remove",
        header: "",
        enableSorting: false,
        cell: ({ row }) => (
          <Button type="button" variant="ghost" size="sm" onClick={() => void remove(row.original.symbol)}>
            Remove
          </Button>
        ),
      },
    ],
    [remove],
  );

  const phoneColumns = useMemo<ColumnDef<WatchItem>[]>(
    () => [
      {
        accessorKey: "symbol",
        header: "Stock",
        meta: { phone: "title" },
        cell: ({ row }) => (
          <Link to={`/stock/${row.original.symbol}`} className="font-mono" onClick={(e) => e.stopPropagation()}>
            {row.original.symbol}
          </Link>
        ),
      },
      { accessorKey: "name", header: "Name", meta: { phone: "subtitle" }, cell: ({ row }) => row.original.name ?? "—" },
      columns[2],
      columns[5],
      {
        id: "more",
        header: "Details",
        enableSorting: false,
        cell: ({ row }) => {
          const open = expanded === row.original.symbol;
          return (
            <button
              type="button"
              aria-expanded={open}
              aria-label={`${open ? "Hide" : "More"} details for ${row.original.symbol}`}
              onClick={(e) => {
                e.stopPropagation();
                setExpanded(open ? null : row.original.symbol);
              }}
              className="inline-flex min-h-10 cursor-pointer items-center gap-1 border-0 bg-transparent p-0 text-xs text-accent"
            >
              {open ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
              {open ? "Less" : "More"}
            </button>
          );
        },
      },
    ],
    [columns, expanded],
  );

  const renderDetails = (r: WatchItem) => (
    <dl className="m-0 grid grid-cols-2 gap-x-3 gap-y-1">
      <dt>Added</dt>
      <dd className="m-0">{r.added_at.slice(0, 10)}</dd>
      <dt>Close when added</dt>
      <dd className="m-0 text-right"><Num value={r.added_close} kind="inr" digits={2} /></dd>
      <dt>Note</dt>
      <dd className="m-0 break-words">{r.note ?? "—"}</dd>
      <dd className="col-span-2 m-0">
        <Button type="button" variant="outline" className="h-10" onClick={() => void remove(r.symbol)}>
          Remove
        </Button>
      </dd>
    </dl>
  );

  if (error) return <p className="neg">{error}</p>;
  if (!items)
    return (
      <div>
        <h1>Watchlist</h1>
        <Skeleton className="h-32" />
      </div>
    );
  return (
    <div>
      <h1>Watchlist</h1>
      {items.length === 0 ? (
        <EmptyState title="Your watchlist is empty.">Open a stock and press “Watch” to add it here.</EmptyState>
      ) : (
        <Card>
          {phone ? (
            <DataTable
              columns={phoneColumns}
              data={items}
              getRowId={(r) => r.symbol}
              expandedRowId={expanded}
              renderExpanded={renderDetails}
            />
          ) : (
            <DataTable columns={columns} data={items} getRowId={(r) => r.symbol} showDensityToggle />
          )}
        </Card>
      )}
    </div>
  );
}
