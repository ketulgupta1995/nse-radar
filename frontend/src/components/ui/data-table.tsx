import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type Column,
  type OnChangeFn,
  type Row,
  type RowData,
  type SortingState,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ChevronDown, ChevronUp } from "lucide-react";
import { Fragment, useState, type ReactNode } from "react";
import Num from "@/components/Num";
import type { NumKind } from "@/components/Num";
import { Sparkline } from "@/components/ui/sparkline";
import { StatusChip } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useDensity, type Density } from "@/lib/density";
import { useIsPhone } from "@/lib/useIsPhone";
import { cn } from "@/lib/utils";

declare module "@tanstack/react-table" {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface ColumnMeta<TData extends RowData, TValue> {
    /** Right-align the column (numbers). */
    right?: boolean;
    /** Phone card role (SPEC §17.9): the card title, the muted line under it, or never shown. */
    phone?: "title" | "subtitle" | "hide";
    /** Plain-text label when the header is a component. */
    label?: string;
  }
}

/** How many label–value pairs a phone card shows before "More". */
const PHONE_PAIRS = 6;

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
  const phone = useIsPhone();
  const rowH = density === "compact" ? "h-8" : "h-10";
  const colCount = columns.length;

  if (phone) {
    return (
      <div className={className}>
        <PhoneSortBar columns={table.getAllLeafColumns()} sorting={sorting} setSorting={setSorting} />
        <div className="flex flex-col gap-2">
          {loading
            ? Array.from({ length: 3 }, (_, i) => (
                <div key={i} data-testid="card-skeleton" className="rounded-card border border-border bg-card p-3">
                  <Skeleton className="mb-2 h-5 w-1/2" />
                  <Skeleton className="h-4 w-full" />
                </div>
              ))
            : table.getRowModel().rows.map((row) => (
                <PhoneCard
                  key={row.id}
                  row={row}
                  onRowClick={onRowClick}
                  className={rowClassName?.(row.original)}
                  expanded={renderExpanded && expandedRowId === row.id ? renderExpanded(row.original) : null}
                />
              ))}
        </div>
        {!loading && data.length === 0 && <EmptyState title={emptyTitle} className="m-3">{emptyHint}</EmptyState>}
      </div>
    );
  }

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
                  const right = h.column.columnDef.meta?.right;
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
                        const right = cell.column.columnDef.meta?.right;
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

/** Plain-text name of a column: the string header, else `meta.label`, else its id. */
function columnLabel<T>(column: Column<T, unknown>): string {
  const header = column.columnDef.header;
  if (typeof header === "string") return header;
  return column.columnDef.meta?.label ?? column.id;
}

function PhoneSortBar<T>({
  columns,
  sorting,
  setSorting,
}: {
  columns: Column<T, unknown>[];
  sorting: SortingState;
  setSorting: OnChangeFn<SortingState>;
}) {
  const sortable = columns.filter((c) => c.getCanSort() && c.columnDef.meta?.phone !== "hide");
  if (sortable.length === 0) return null;
  const current = sorting[0];
  const desc = current?.desc ?? false;
  return (
    <div className="mb-2 flex items-center gap-2 text-sm">
      <label className="flex flex-1 items-center gap-2 text-muted-foreground">
        Sort by
        <Select
          aria-label="Sort by"
          className="h-10 flex-1"
          value={current?.id ?? ""}
          onChange={(e) => setSorting(e.target.value ? [{ id: e.target.value, desc }] : [])}
        >
          <option value="">Default order</option>
          {sortable.map((c) => (
            <option key={c.id} value={c.id}>
              {columnLabel(c)}
            </option>
          ))}
        </Select>
      </label>
      <button
        type="button"
        disabled={!current}
        aria-label={desc ? "Descending, tap for ascending" : "Ascending, tap for descending"}
        onClick={() => current && setSorting([{ id: current.id, desc: !desc }])}
        className="inline-flex h-10 min-w-10 cursor-pointer items-center justify-center gap-1 rounded-control border border-border bg-transparent px-2 text-muted-foreground disabled:opacity-50"
      >
        {desc ? <ArrowDown size={14} /> : <ArrowUp size={14} />}
        {desc ? "High first" : "Low first"}
      </button>
    </div>
  );
}

function PhoneCard<T>({
  row,
  onRowClick,
  className,
  expanded,
}: {
  row: Row<T>;
  onRowClick?: (row: T) => void;
  className?: string;
  expanded: ReactNode;
}) {
  const [more, setMore] = useState(false);
  const cells = row.getVisibleCells().filter((c) => c.column.columnDef.meta?.phone !== "hide");
  const title =
    cells.find((c) => c.column.columnDef.meta?.phone === "title") ?? cells.find((c) => !c.column.columnDef.meta?.phone);
  const subtitle = cells.find((c) => c.column.columnDef.meta?.phone === "subtitle" && c !== title);
  const pairs = cells.filter((c) => c !== title && c !== subtitle);
  const shown = more ? pairs : pairs.slice(0, PHONE_PAIRS);
  return (
    <div
      data-testid="phone-card"
      onClick={onRowClick ? () => onRowClick(row.original) : undefined}
      className={cn(
        "rounded-card border border-border bg-card p-3 text-sm",
        onRowClick && "cursor-pointer active:bg-muted",
        className,
      )}
    >
      {title && <div className="font-medium text-foreground">{flexRender(title.column.columnDef.cell, title.getContext())}</div>}
      {subtitle && (
        <div className="text-xs text-muted-foreground">{flexRender(subtitle.column.columnDef.cell, subtitle.getContext())}</div>
      )}
      {shown.length > 0 && (
        <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1">
          {shown.map((c) => (
            <Fragment key={c.id}>
              <dt className="text-muted-foreground">{columnLabel(c.column)}</dt>
              <dd className={cn("m-0", c.column.columnDef.meta?.right && "text-right")}>
                {flexRender(c.column.columnDef.cell, c.getContext())}
              </dd>
            </Fragment>
          ))}
        </dl>
      )}
      {pairs.length > PHONE_PAIRS && (
        <button
          type="button"
          aria-expanded={more}
          onClick={(e) => {
            e.stopPropagation();
            setMore((m) => !m);
          }}
          className="mt-1 inline-flex min-h-10 cursor-pointer items-center gap-1 border-0 bg-transparent p-0 text-xs text-accent"
        >
          {more ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          {more ? "Less" : "More"}
        </button>
      )}
      {expanded && <div className="mt-2 border-t border-border pt-2 text-muted-foreground">{expanded}</div>}
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
