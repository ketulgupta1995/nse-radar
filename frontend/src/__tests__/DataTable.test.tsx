import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import type { ColumnDef } from "@tanstack/react-table";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { DataTable } from "../components/ui/data-table";

interface Row { sym: string; px: number }
const rows: Row[] = [{ sym: "B", px: 20 }, { sym: "A", px: 30 }, { sym: "C", px: 10 }];
const columns: ColumnDef<Row>[] = [
  { accessorKey: "sym", header: "Symbol" },
  { accessorKey: "px", header: "Price", meta: { right: true } },
];

beforeEach(() => localStorage.clear());
afterEach(cleanup);

const firstColumn = () => screen.getAllByRole("row").slice(1).map((r) => within(r).getAllByRole("cell")[0].textContent);

test("sorts ascending then descending when the header is clicked", () => {
  render(<DataTable columns={columns} data={rows} />);
  fireEvent.click(screen.getByRole("button", { name: "Symbol" }));
  expect(firstColumn()).toEqual(["A", "B", "C"]);
  fireEvent.click(screen.getByRole("button", { name: "Symbol" }));
  expect(firstColumn()).toEqual(["C", "B", "A"]);
});

test("row click passes the row", () => {
  const onRowClick = vi.fn();
  render(<DataTable columns={columns} data={rows} onRowClick={onRowClick} />);
  fireEvent.click(screen.getByText("A"));
  expect(onRowClick).toHaveBeenCalledWith(rows[1]);
});

test("density toggle switches the row height and is remembered", () => {
  render(<DataTable columns={columns} data={rows} showDensityToggle />);
  expect(screen.getAllByRole("row")[1].className).toContain("h-8");
  fireEvent.click(screen.getByRole("button", { name: "Comfortable" }));
  expect(screen.getAllByRole("row")[1].className).toContain("h-10");
  expect(localStorage.getItem("table-density")).toBe("comfortable");
});

test("empty state and loading skeletons", () => {
  const { rerender } = render(<DataTable columns={columns} data={[]} emptyTitle="No rows" />);
  expect(screen.getByText("No rows")).toBeTruthy();
  rerender(<DataTable columns={columns} data={[]} loading />);
  expect(screen.queryByText("No rows")).toBeNull();
});

test("expanded row and row class are rendered", () => {
  render(
    <DataTable
      columns={columns}
      data={rows}
      getRowId={(r) => r.sym}
      expandedRowId="A"
      renderExpanded={(r) => <span>details for {r.sym}</span>}
      rowClassName={(r) => (r.sym === "B" ? "dimmed" : undefined)}
    />,
  );
  expect(screen.getByText("details for A")).toBeTruthy();
  expect(screen.queryByText("details for B")).toBeNull();
  expect(screen.getByText("B").closest("tr")?.className).toContain("dimmed");
});
