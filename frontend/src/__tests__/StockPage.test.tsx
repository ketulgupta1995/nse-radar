import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { setPhone } from "./phone";

import { api } from "../api/client";
import Stock from "../pages/Stock";

vi.mock("../components/chart/PriceChart", () => ({ default: () => <div>chart</div> }));

let tft: Record<string, unknown> = {};

beforeEach(() => {
  tft = {};
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  vi.spyOn(api, "get").mockImplementation(async (p: string) => {
    if (p.startsWith("/symbols/TCS"))
      return { symbol: "TCS", name: "Tata Consultancy", last_close: 4000, change_pct: -1.5, last_date: "2026-11-06", bars_source: "nse", in_watchlist: false, open_position_id: null, ...tft } as never;
    if (p.startsWith("/prices/")) return { bars: [{ t: "2026-11-06", o: 1, h: 2, l: 1, c: 2, v: 1 }], indicators: {} } as never;
    if (p.startsWith("/fundamentals/fields") || p.startsWith("/indicators") || p.startsWith("/sources") || p.startsWith("/ai/requests")) return [] as never;
    if (p.startsWith("/announcements") || p.startsWith("/news")) return [] as never;
    return null as never;
  });
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const page = () =>
  render(
    <MemoryRouter initialEntries={["/stock/TCS"]}>
      <Routes><Route path="/stock/:symbol" element={<Stock />} /></Routes>
    </MemoryRouter>,
  );

test("header shows symbol, price, change and the watchlist star", async () => {
  page();
  expect(await screen.findByText("TCS")).toBeTruthy();
  expect(screen.getByText("₹4,000.00")).toBeTruthy();
  expect(screen.getByText("-1.5%")).toBeTruthy();
  expect(screen.getByRole("button", { name: /Watch/ })).toBeTruthy();
  expect(screen.getByText("Start checklist")).toBeTruthy();
});

test("trade-for-trade badge shows only for BE/BZ stocks", async () => {
  page();
  await screen.findByText("TCS");
  expect(screen.queryByText("Trade-for-trade")).toBeNull();
  cleanup();
  tft = { series: "BE", trade_for_trade: true };
  page();
  expect(await screen.findByText("Trade-for-trade")).toBeTruthy();
});

test("right-hand tabs switch content", async () => {
  page();
  await screen.findByText("TCS");
  expect(screen.getByRole("tab", { name: "Fundamentals", selected: true })).toBeTruthy();
  fireEvent.mouseDown(screen.getByRole("tab", { name: "Ask Claude" }), { button: 0, ctrlKey: false });
  expect(await screen.findByRole("tab", { name: "Ask Claude", selected: true })).toBeTruthy();
  expect(screen.getByLabelText("Ask Claude", { selector: "section" })).toBeTruthy();
});

describe("on a phone", () => {
  beforeEach(() => act(() => setPhone(true)));
  afterEach(() => act(() => setPhone(false)));

  test("tabs render and switch, actions are icon buttons", async () => {
    page();
    await screen.findByText("TCS");
    for (const n of ["Overview", "Quarterly", "News", "AI"]) expect(screen.getByRole("tab", { name: n })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Overview", selected: true })).toBeTruthy();
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Quarterly" }), { button: 0, ctrlKey: false });
    expect(await screen.findByRole("tab", { name: "Quarterly", selected: true })).toBeTruthy();
    expect(screen.getByLabelText("Quarterly results", { selector: "section" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Start checklist" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Ask Claude" }));
    expect(await screen.findByRole("tab", { name: "AI", selected: true })).toBeTruthy();
  });
});
