import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeAll, expect, test, vi } from "vitest";

import { api } from "../api/client";
import type { ResearchReport } from "../api/types";
import Research from "../pages/Research";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const report = (id: string, stock: string, type: "Buy" | "Sell", tracked: boolean): ResearchReport => ({
  source: "s", report_id: id, date: "2026-11-27", symbol: stock.toUpperCase(), stock, author: "North Broker", type,
  ltp: 1020, target: 1300, reco_price: 1000, change_pct: 2, upside_pct: 27.45, url: null,
  fetched_at: "2026-11-27T21:30:00+05:30", tracked,
});

test("lists calls, links tracked stocks, and filters", async () => {
  vi.spyOn(api, "get").mockResolvedValue([report("2", "Alpha", "Buy", true), report("1", "Beta", "Sell", false)]);
  render(<MemoryRouter><Research /></MemoryRouter>);
  await waitFor(() => expect(screen.getByRole("link", { name: "Alpha" })).toBeTruthy());
  expect(screen.queryByRole("link", { name: "Beta" })).toBeNull();
  expect(screen.getAllByText("27.45%")).toHaveLength(2); // no "+": a Sell call's upside points down
  expect(screen.getAllByText("2026-11-27 21:30")).toHaveLength(2);
  fireEvent.change(screen.getByRole("combobox", { name: "Type" }), { target: { value: "Sell" } });
  expect(screen.queryByText("Alpha")).toBeNull();
  expect(screen.getByText("1 of 2 reports")).toBeTruthy();
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "zzz" } });
  expect(screen.getByText("No reports match.")).toBeTruthy();
});
