import type { ColumnDef } from "@tanstack/react-table";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
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
          <DataTable columns={columns} data={items} getRowId={(r) => r.symbol} showDensityToggle />
        </Card>
      )}
    </div>
  );
}
