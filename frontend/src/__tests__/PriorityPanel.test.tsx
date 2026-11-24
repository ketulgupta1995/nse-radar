import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import type { PriorityResponse } from "../api/types";
import PriorityPanel, { currentOrder } from "../components/sources/PriorityPanel";

afterEach(cleanup);

const priority: PriorityResponse = {
  bars: ["nse_bhav", "yfinance"],
  news: ["rss"],
  capabilities: { bars: ["nse_bhav", "yfinance"], news: ["rss"], actions: ["nse_api", "yfinance"] },
};
const labels = { nse_bhav: "NSE bhavcopy", yfinance: "Yahoo Finance", rss: "News feeds", nse_api: "NSE website" };

test("down/up buttons reorder and Save emits the new order for that capability", () => {
  const onSave = vi.fn();
  render(<PriorityPanel priority={priority} labels={labels} onSave={onSave} />);
  expect(screen.getByText("Save bars order").hasAttribute("disabled")).toBe(true);
  fireEvent.click(screen.getByLabelText("Move NSE bhavcopy down in bars"));
  fireEvent.click(screen.getByText("Save bars order"));
  expect(onSave).toHaveBeenCalledWith("bars", ["yfinance", "nse_bhav"]);
  fireEvent.click(screen.getByLabelText("Move NSE bhavcopy up in bars"));
  expect(screen.getByText("Save bars order").hasAttribute("disabled")).toBe(true); // back to saved order
});

test("first item can't move up, last can't move down", () => {
  render(<PriorityPanel priority={priority} labels={labels} onSave={() => {}} />);
  expect(screen.getByLabelText("Move NSE bhavcopy up in bars").hasAttribute("disabled")).toBe(true);
  expect(screen.getByLabelText("Move Yahoo Finance down in bars").hasAttribute("disabled")).toBe(true);
});

test("unlisted sources are appended by name; stale names dropped", () => {
  expect(currentOrder(priority, "actions")).toEqual(["nse_api", "yfinance"]);
  const p: PriorityResponse = { bars: ["gone", "b"], capabilities: { bars: ["a", "b", "c"] } };
  expect(currentOrder(p, "bars")).toEqual(["b", "a", "c"]);
});

test("explains how priority works", () => {
  render(<PriorityPanel priority={priority} labels={labels} onSave={() => {}} />);
  expect(screen.getAllByText(/first source in this list that has data/).length).toBeGreaterThan(0);
});
