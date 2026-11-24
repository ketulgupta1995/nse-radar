import { useMemo, useState } from "react";
import type { ColumnDef, SortingState } from "@tanstack/react-table";
import { Link, useNavigate } from "react-router-dom";
import type { ScreenResult } from "../../api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { toast } from "@/components/ui/toaster";
import Num from "../Num";

/** Symbols first seen in the latest run. Not flagged when everything is new (nothing to compare with). */
export function newSymbols(results: ScreenResult[]): Set<string> {
  if (results.length === 0) return new Set();
  const latest = results.reduce((m, r) => (r.first_seen > m ? r.first_seen : m), "");
  const hasOlder = results.some((r) => r.first_seen < latest);
  return hasOlder ? new Set(results.filter((r) => r.first_seen === latest).map((r) => r.symbol)) : new Set();
}

type Key = "symbol" | "name" | "first_seen" | "score" | `v:${string}`;

function cell(r: ScreenResult, key: Key): string | number | null {
  if (key === "symbol") return r.symbol;
  if (key === "name") return r.name ?? "";
  if (key === "first_seen") return r.first_seen;
  if (key === "score") return r.score;
  return r.values[key.slice(2)] ?? null;
}

export function sortResults(rows: ScreenResult[], key: Key, dir: 1 | -1): ScreenResult[] {
  return [...rows].sort((a, b) => {
    const x = cell(a, key);
    const y = cell(b, key);
    if (x === null && y === null) return 0;
    if (x === null) return 1; // blanks last, whichever way we sort
    if (y === null) return -1;
    return (typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y))) * dir;
  });
}

function toText(rows: ScreenResult[], columns: string[], showScore: boolean): string {
  const head = ["Symbol", "Name", ...columns, "First seen", ...(showScore ? ["Score"] : [])];
  const lines = rows.map((r) => [
    r.symbol,
    r.name ?? "",
    ...columns.map((c) => r.values[c] ?? ""),
    r.first_seen,
    ...(showScore ? [r.score ?? ""] : []),
  ]);
  return [head, ...lines].map((l) => l.join("\t")).join("\n");
}

async function copy(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

export default function ScreenResults({ results }: { results: ScreenResult[] }) {
  const nav = useNavigate();
  const [sorting, setSorting] = useState<SortingState>([{ id: "symbol", desc: false }]);
  const [copied, setCopied] = useState<string | null>(null);
  const columns = useMemo(() => {
    const seen: string[] = [];
    for (const r of results) for (const k of Object.keys(r.values)) if (!seen.includes(k)) seen.push(k);
    return seen;
  }, [results]);
  const showScore = results.some((r) => r.score !== null);
  const fresh = useMemo(() => newSymbols(results), [results]);
  const key = (sorting[0]?.id ?? "symbol") as Key;
  const dir = sorting[0]?.desc ? -1 : 1;
  const rows = useMemo(() => sortResults(results, key, dir), [results, key, dir]);

  const cols = useMemo<ColumnDef<ScreenResult>[]>(
    () => [
      {
        id: "symbol",
        header: "Symbol",
        accessorFn: (r) => r.symbol,
        cell: ({ row }) => (
          <Link to={`/stock/${encodeURIComponent(row.original.symbol)}`} className="font-mono" onClick={(e) => e.stopPropagation()}>
            {row.original.symbol}
          </Link>
        ),
      },
      { id: "name", header: "Name", accessorFn: (r) => r.name ?? "", cell: ({ row }) => row.original.name },
      ...columns.map<ColumnDef<ScreenResult>>((c) => ({
        id: `v:${c}`,
        header: c,
        meta: { right: true },
        sortUndefined: "last",
        accessorFn: (r) => r.values[c] ?? undefined,
        cell: ({ row }) => <Num value={row.original.values[c]} digits={2} />,
      })),
      {
        id: "first_seen",
        header: "First seen",
        accessorFn: (r) => r.first_seen,
        cell: ({ row }) => (
          <>
            {row.original.first_seen}
            {fresh.has(row.original.symbol) && <Badge variant="info" className="ml-1">NEW</Badge>}
          </>
        ),
      },
      ...(showScore
        ? [
            {
              id: "score",
              header: "Score",
              meta: { right: true },
              sortUndefined: "last",
              accessorFn: (r: ScreenResult) => r.score ?? undefined,
              cell: ({ row }: { row: { original: ScreenResult } }) => <Num value={row.original.score} digits={0} />,
            } satisfies ColumnDef<ScreenResult>,
          ]
        : []),
    ],
    [columns, fresh, showScore],
  );

  const doCopy = async (what: string, text: string) => {
    const ok = await copy(text);
    setCopied(ok ? `Copied ${what}.` : "Couldn't copy: select the table and copy it by hand.");
    if (ok) toast.success(`Copied ${what}.`);
  };

  if (results.length === 0) {
    return <EmptyState title="No stocks match right now.">Try Run now, or loosen a condition.</EmptyState>;
  }
  return (
    <div>
      <p className="flex items-center gap-2">
        <Button variant="outline" size="sm" onClick={() => doCopy("the symbols", rows.map((r) => r.symbol).join("\n"))}>
          Copy symbols
        </Button>
        <Button variant="outline" size="sm" onClick={() => doCopy("the table", toText(rows, columns, showScore))}>
          Copy table
        </Button>
        {copied && <span className="muted" role="status">{copied}</span>}
      </p>
      <DataTable
        columns={cols}
        data={results}
        sorting={sorting}
        onSortingChange={setSorting}
        showDensityToggle
        getRowId={(r) => r.symbol}
        onRowClick={(r) => nav(`/stock/${encodeURIComponent(r.symbol)}`)}
      />
    </div>
  );
}
