import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import type { ColumnDef } from "@tanstack/react-table";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { DataTable } from "../components/ui/data-table";
import { setPhone } from "./phone";

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

describe("on a phone", () => {
  interface Wide { sym: string; name: string; secret: string; a: number; b: number; c: number; d: number; e: number; f: number; g: number }
  const wide: Wide[] = [
    { sym: "TCS", name: "Tata Consultancy", secret: "s1", a: 1, b: 2, c: 3, d: 4, e: 5, f: 6, g: 7 },
    { sym: "INFY", name: "Infosys", secret: "s2", a: 9, b: 2, c: 3, d: 4, e: 5, f: 6, g: 8 },
    { sym: "HDFC", name: "HDFC Bank", secret: "s3", a: 5, b: 2, c: 3, d: 4, e: 5, f: 6, g: 9 },
  ];
  const wideCols: ColumnDef<Wide>[] = [
    { accessorKey: "secret", header: "Secret", meta: { phone: "hide" } },
    { accessorKey: "name", header: "Name", meta: { phone: "subtitle" } },
    { accessorKey: "sym", header: "Symbol", meta: { phone: "title" } },
    { accessorKey: "a", header: () => <span>Alpha</span>, meta: { label: "Alpha score" } },
    { accessorKey: "b", header: "Beta" },
    { accessorKey: "c", header: "Gamma" },
    { accessorKey: "d", header: "Delta" },
    { accessorKey: "e", header: "Eps" },
    { accessorKey: "f", header: "Zeta" },
    { accessorKey: "g", header: "Eta" },
  ];
  const cards = () => screen.getAllByTestId("phone-card");
  const titles = () => cards().map((c) => c.firstElementChild?.textContent);

  beforeEach(() => act(() => setPhone(true)));
  afterEach(() => act(() => setPhone(false)));

  test("3 rows render 3 cards, no table and no density toggle", () => {
    render(<DataTable columns={wideCols} data={wide} showDensityToggle />);
    expect(cards()).toHaveLength(3);
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByRole("button", { name: "Comfortable" })).toBeNull();
  });

  test("title, subtitle and hide are respected; 6 pairs until More", () => {
    render(<DataTable columns={wideCols} data={wide} />);
    const card = cards()[0];
    expect(card.children[0].textContent).toBe("TCS");
    expect(card.children[1].textContent).toBe("Tata Consultancy");
    expect(within(card).queryByText("s1")).toBeNull();
    expect(within(card).queryByText("Secret")).toBeNull();
    expect(within(card).getAllByRole("term").map((t) => t.textContent)).toEqual([
      "Alpha score", "Beta", "Gamma", "Delta", "Eps", "Zeta",
    ]);
    expect(within(card).queryByText("Eta")).toBeNull();
    fireEvent.click(within(card).getByRole("button", { name: "More" }));
    expect(within(card).getByText("Eta")).toBeTruthy();
    expect(within(card).getAllByRole("term")).toHaveLength(7);
  });

  test("title defaults to the first visible column", () => {
    render(<DataTable columns={columns} data={rows} />);
    expect(titles()).toEqual(["B", "A", "C"]);
    expect(within(cards()[0]).getByRole("term").textContent).toBe("Price");
  });

  test("Sort by select and direction toggle reorder the cards", () => {
    render(<DataTable columns={columns} data={rows} />);
    const select = screen.getByRole("combobox", { name: "Sort by" });
    expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual(["Default order", "Symbol", "Price"]);
    fireEvent.change(select, { target: { value: "sym" } });
    expect(titles()).toEqual(["A", "B", "C"]);
    fireEvent.click(screen.getByRole("button", { name: /Ascending/ }));
    expect(titles()).toEqual(["C", "B", "A"]);
    fireEvent.change(select, { target: { value: "px" } });
    expect(titles()).toEqual(["A", "B", "C"]);
  });

  test("card click calls onRowClick; More does not", () => {
    const onRowClick = vi.fn();
    render(<DataTable columns={wideCols} data={wide} onRowClick={onRowClick} />);
    fireEvent.click(within(cards()[0]).getByRole("button", { name: "More" }));
    expect(onRowClick).not.toHaveBeenCalled();
    fireEvent.click(cards()[1]);
    expect(onRowClick).toHaveBeenCalledWith(wide[1]);
  });

  test("expanded content and row class apply to the card", () => {
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
    expect(within(cards()[1]).getByText("details for A")).toBeTruthy();
    expect(cards()[0].className).toContain("dimmed");
  });

  test("empty state and 3 skeleton cards", () => {
    const { rerender } = render(<DataTable columns={columns} data={[]} emptyTitle="No rows" />);
    expect(screen.getByText("No rows")).toBeTruthy();
    rerender(<DataTable columns={columns} data={[]} loading />);
    expect(screen.getAllByTestId("card-skeleton")).toHaveLength(3);
    expect(screen.queryByText("No rows")).toBeNull();
  });
});
