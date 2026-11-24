import type { ColumnDef, SortingState } from "@tanstack/react-table";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { BacktestTrade } from "../../api/types";
import { DataTable } from "@/components/ui/data-table";
import Num from "../Num";

export default function TradesTable({ trades }: { trades: BacktestTrade[] }) {
  const [sorting, setSorting] = useState<SortingState>([{ id: "exit_date", desc: true }]);
  const columns = useMemo<ColumnDef<BacktestTrade>[]>(
    () => [
      { id: "symbol", header: "Stock", accessorFn: (t) => t.symbol, cell: ({ row }) => <Link to={`/stock/${row.original.symbol}`} className="font-mono">{row.original.symbol}</Link> },
      { id: "entry_date", header: "Bought", accessorFn: (t) => t.entry_date },
      { id: "entry", header: "Buy price", meta: { right: true }, accessorFn: (t) => t.entry, cell: ({ row }) => <Num value={row.original.entry} kind="inr" digits={2} /> },
      { id: "exit_date", header: "Sold", accessorFn: (t) => t.exit_date },
      { id: "exit", header: "Sell price", meta: { right: true }, accessorFn: (t) => t.exit, cell: ({ row }) => <Num value={row.original.exit} kind="inr" digits={2} /> },
      { id: "qty", header: "Shares", meta: { right: true }, accessorFn: (t) => t.qty, cell: ({ row }) => <Num value={row.original.qty} /> },
      { id: "pnl", header: "Profit (₹)", meta: { right: true }, accessorFn: (t) => t.pnl, cell: ({ row }) => <Num value={row.original.pnl} kind="inr" colored /> },
      { id: "pnl_pct", header: "Profit %", meta: { right: true }, accessorFn: (t) => t.pnl_pct, cell: ({ row }) => <Num value={row.original.pnl_pct} kind="pct" colored /> },
      { id: "reason", header: "Why sold", accessorFn: (t) => t.reason },
      { id: "days", header: "Days held", meta: { right: true }, accessorFn: (t) => t.days, cell: ({ row }) => <Num value={row.original.days} /> },
    ],
    [],
  );
  return (
    <DataTable
      columns={columns}
      data={trades}
      sorting={sorting}
      onSortingChange={setSorting}
      showDensityToggle
      getRowId={(t, i) => `${t.symbol}-${t.entry_date}-${i}`}
    />
  );
}
