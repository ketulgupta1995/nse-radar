import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type OnChangeFn,
  type SortingState,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp } from "lucide-react";
import { Fragment, useState, type ReactNode } from "react";
import Num from "@/components/Num";
import type { NumKind } from "@/components/Num";
import { Sparkline } from "@/components/ui/sparkline";
import { StatusChip } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { useDensity, type Density } from "@/lib/density";
import { cn } from "@/lib/utils";

export function DensityToggle({ density, onChange }: { density: Density; onChange: (d: Density) => void }) {
  return (
    <div role="group" aria-label="Row density" className="inline-flex overflow-hidden rounded-control border border-border text-xs">
      {(["compact", "comfortable"] as const).map((d) => (
        <button
          key={d}
          type="button"
          aria-pressed={density === d}
          onClick={() => onChange(d)}
          className={cn(
            "cursor-pointer border-0 px-2 py-1",
            density === d ? "bg-accent text-accent-foreground" : "bg-transparent text-muted-foreground hover:bg-muted",
          )}
        >
          {d === "compact" ? "Compact" : "Comfortable"}
        </button>
      ))}
    </div>
  );
}

interface Props<T> {
  columns: ColumnDef<T>[];
  data: T[];
  /** Makes rows clickable. */
  onRowClick?: (row: T) => void;
  zebra?: boolean;
  loading?: boolean;
  emptyTitle?: string;
  emptyHint?: ReactNode;
  /** Show the density toggle above the table. */
  showDensityToggle?: boolean;
  /** Stable key for a row (defaults to its index). */
  getRowId?: (row: T, index: number) => string;
  className?: string;
  /** Optional controlled sorting, for callers that need to know the order (e.g. to copy it). */
  sorting?: SortingState;
  onSortingChange?: OnChangeFn<SortingState>;
  /** Extra class for a row (e.g. to grey out unreliable rows). */
  rowClassName?: (row: T) => string | undefined;
  /** Show `renderExpanded(row)` in a full-width row under the row whose id is `expandedRowId`. */
  expandedRowId?: string | null;
  renderExpanded?: (row: T) => ReactNode;
}

export function DataTable<T>({
  columns,
  data,
  onRowClick,
  zebra,
  loading,
  emptyTitle = "Nothing here yet",
  emptyHint,
  showDensityToggle,
  getRowId,
  className,
  sorting: controlledSorting,
  onSortingChange,
  rowClassName,
  expandedRowId,
  renderExpanded,
}: Props<T>) {
  const [innerSorting, setInnerSorting] = useState<SortingState>([]);
  const sorting = controlledSorting ?? innerSorting;
  const setSorting = onSortingChange ?? setInnerSorting;
  const { density, setDensity } = useDensity();
  const table = useReactTable({
    sortDescFirst: false,
    data,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getRowId,
  });
  const rowH = density === "compact" ? "h-8" : "h-10";
  const colCount = columns.length;

  return (
    <div className={className}>
      {showDensityToggle && (
        <div className="mb-2 flex justify-end">
          <DensityToggle density={density} onChange={setDensity} />
        </div>
      )}
      <div className="overflow-auto rounded-card border border-border">
        <table className="w-full border-collapse text-sm" data-density={density}>
          <thead className="sticky top-0 z-10 bg-card">
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                {hg.headers.map((h) => {
                  const sorted = h.column.getIsSorted();
                  const canSort = h.column.getCanSort();
                  const right = (h.column.columnDef.meta as { right?: boolean } | undefined)?.right;
                  return (
                    <th
                      key={h.id}
                      aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : undefined}
                      className={cn("border-b border-border px-3 py-2 font-medium text-muted-foreground", right ? "text-right" : "text-left")}
                    >
                      {h.isPlaceholder ? null : canSort ? (
                        <button
                          type="button"
                          onClick={h.column.getToggleSortingHandler()}
                          className="inline-flex cursor-pointer items-center gap-1 border-0 bg-transparent p-0 font-medium text-inherit hover:text-foreground"
                          style={{ font: "inherit" }}
                        >
                          {flexRender(h.column.columnDef.header, h.getContext())}
                          {sorted === "asc" ? <ArrowUp size={12} /> : sorted === "desc" ? <ArrowDown size={12} /> : null}
                        </button>
                      ) : (
                        flexRender(h.column.columnDef.header, h.getContext())
                      )}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {loading
              ? Array.from({ length: 5 }, (_, i) => (
                  <tr key={i} className={rowH}>
                    <td colSpan={colCount} className="border-b border-border px-3 py-1">
                      <Skeleton className="h-4 w-full" />
                    </td>
                  </tr>
                ))
              : table.getRowModel().rows.map((row, i) => (
                  <Fragment key={row.id}>
                    <tr
                      onClick={onRowClick ? () => onRowClick(row.original) : undefined}
                      className={cn(
                        rowH,
                        zebra && i % 2 === 1 && "bg-muted/40",
                        "hover:bg-muted",
                        onRowClick && "cursor-pointer",
                        rowClassName?.(row.original),
                      )}
                    >
                      {row.getVisibleCells().map((cell) => {
                        const right = (cell.column.columnDef.meta as { right?: boolean } | undefined)?.right;
                        return (
                          <td key={cell.id} className={cn("border-b border-border px-3 py-0", right && "text-right")}>
                            {flexRender(cell.column.columnDef.cell, cell.getContext())}
                          </td>
                        );
                      })}
                    </tr>
                    {renderExpanded && expandedRowId === row.id && (
                      <tr>
                        <td colSpan={colCount} className="border-b border-border px-3 py-2 text-muted-foreground">
                          {renderExpanded(row.original)}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
          </tbody>
        </table>
        {!loading && data.length === 0 && <EmptyState title={emptyTitle} className="m-3">{emptyHint}</EmptyState>}
      </div>
    </div>
  );
}

/** Cell helpers. Pass as `cell: ({ getValue }) => ...` or call directly. */
export function DeltaCell({ value, kind = "pct", digits }: { value: number | null | undefined; kind?: NumKind; digits?: number }) {
  return <Num value={value} kind={kind} digits={digits} colored right />;
}
export function SparklineCell({ values }: { values: number[] | null | undefined }) {
  return values && values.length > 1 ? <Sparkline values={values} /> : <span className="text-muted-foreground">—</span>;
}
export function StatusCell({ status }: { status: string }) {
  return <StatusChip status={status} />;
}
