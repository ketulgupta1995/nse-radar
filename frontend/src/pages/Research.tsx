import type { ColumnDef } from "@tanstack/react-table";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { ResearchReport } from "../api/types";
import Explain from "../components/Explain";
import Num from "../components/Num";
import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";

function head(label: string, help: string) {
  return () => (
    <span>
      {label}
      <Explain text={help} />
    </span>
  );
}

function numberColumn(
  key: "ltp" | "target",
  label: string,
  help: string,
): ColumnDef<ResearchReport> {
  return {
    id: key,
    header: head(label, help),
    meta: { right: true, label },
    sortUndefined: "last",
    accessorFn: (r) => r[key] ?? undefined,
    cell: ({ row }) => <Num value={row.original[key]} kind="inr" digits={2} />,
  };
}

const columns: ColumnDef<ResearchReport>[] = [
  {
    accessorKey: "date",
    header: "Date",
    cell: ({ row }) => <span className="num whitespace-nowrap">{row.original.date}</span>,
  },
  {
    accessorKey: "stock",
    header: "Stock",
    meta: { phone: "title" },
    cell: ({ row: { original: r } }) =>
      r.tracked && r.symbol ? <Link to={`/stock/${r.symbol}`}>{r.stock}</Link> : <span>{r.stock}</span>,
  },
  {
    accessorKey: "author",
    header: "Author",
    meta: { phone: "subtitle" },
    cell: ({ row: { original: r } }) =>
      r.url ? (
        <a href={r.url} target="_blank" rel="noreferrer">
          {r.author}
        </a>
      ) : (
        <span>{r.author}</span>
      ),
  },
  numberColumn("ltp", "LTP", "Last traded price when this row was last fetched. It is not a live price."),
  numberColumn("target", "Target", "The price the broker expects the stock to reach."),
  {
    id: "reco_price",
    header: head(
      "Price at reco (change)",
      "The price when the broker made the call, and how far the price had moved since then at the last fetch.",
    ),
    meta: { right: true, label: "Price at reco (change)" },
    sortUndefined: "last",
    accessorFn: (r) => r.reco_price ?? undefined,
    cell: ({ row: { original: r } }) => (
      <span className="whitespace-nowrap">
        <Num value={r.reco_price} kind="inr" digits={2} />
        {r.change_pct !== null && (
          <>
            {" ("}
            <Num value={r.change_pct} kind="pct" digits={2} colored />
            {")"}
          </>
        )}
      </span>
    ),
  },
  {
    id: "upside_pct",
    header: head(
      "Upside",
      "How far the target is from the price, in percent, as Trendlyne published it. It has no plus or minus sign: on a Sell call the target is usually below the price, so this is the expected fall.",
    ),
    meta: { right: true, label: "Upside" },
    sortUndefined: "last",
    accessorFn: (r) => r.upside_pct ?? undefined,
    // No "+": the source publishes a size, which for a Sell call points downwards.
    cell: ({ row: { original: r } }) => (
      <span className="num">{r.upside_pct === null ? "—" : `${r.upside_pct.toFixed(2)}%`}</span>
    ),
  },
  {
    accessorKey: "type",
    header: "Type",
    cell: ({ row: { original: r } }) => (
      <Badge variant={r.type === "Buy" ? "info" : "warning"}>{r.type}</Badge>
    ),
  },
  {
    accessorKey: "fetched_at",
    header: head("Last checked", "When LTP and the change since the call were last read (India time)."),
    meta: { label: "Last checked" },
    cell: ({ row }) => <span className="num whitespace-nowrap">{row.original.fetched_at.slice(0, 16).replace("T", " ")}</span>,
  },
];

export default function Research() {
  const [rows, setRows] = useState<ResearchReport[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [type, setType] = useState("all");
  const [search, setSearch] = useState("");

  useEffect(() => {
    api
      .get<ResearchReport[]>("/research/reports?limit=2000")
      .then(setRows)
      .catch((e) => setError(e instanceof ApiError ? e.message : String(e)));
  }, []);

  const shown = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (rows ?? []).filter(
      (r) =>
        (type === "all" || r.type === type) &&
        (!q || `${r.stock} ${r.symbol ?? ""} ${r.author}`.toLowerCase().includes(q)),
    );
  }, [rows, type, search]);

  if (error) return <p className="neg">{error}</p>;

  return (
    <div>
      <h1>Broker reports</h1>
      <p className="text-sm text-muted-foreground">
        Brokers&apos; Buy and Sell calls, collected once a day from{" "}
        <a href="https://trendlyne.com/research-reports/all/" target="_blank" rel="noreferrer">
          Trendlyne
        </a>
        . These are other people&apos;s opinions, not signals from this app.
      </p>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Select aria-label="Type" value={type} onChange={(e) => setType(e.target.value)}>
          <option value="all">Buy and Sell</option>
          <option value="Buy">Buy only</option>
          <option value="Sell">Sell only</option>
        </Select>
        <Input
          aria-label="Search stock or author"
          placeholder="Search stock or author"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        {rows && (
          <span className="text-sm text-muted-foreground">
            {shown.length} of {rows.length} reports
          </span>
        )}
      </div>
      <DataTable
        columns={columns}
        data={shown}
        loading={rows === null}
        showDensityToggle
        getRowId={(r) => `${r.source}:${r.report_id}`}
        emptyTitle={rows?.length ? "No reports match." : "No reports yet."}
        emptyHint={
          rows?.length ? undefined : (
            <span>
              Run &quot;Trendlyne research reports&quot; on the <Link to="/jobs">Jobs page</Link>.
            </span>
          )
        }
      />
    </div>
  );
}
