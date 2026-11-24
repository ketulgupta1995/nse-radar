import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import type { PriceSeries } from "../api/types";
import PriceChart, { rangeFrom } from "../components/chart/PriceChart";
import { chartColors } from "../lib/chartTheme";
// A stand-in for lightweight-charts: records calls so the toolbar and legend can be checked without a canvas.
const h = vi.hoisted(() => ({
  setVisibleRange: vi.fn(),
  fitContent: vi.fn(),
  series: [] as object[],
  crosshair: null as null | ((p: unknown) => void),
}));
vi.mock("lightweight-charts", () => ({
  CandlestickSeries: "candles",
  HistogramSeries: "hist",
  LineSeries: "line",
  createSeriesMarkers: () => undefined,
  createChart: () => ({
    addSeries: () => {
      const s = { setData: () => undefined, priceScale: () => ({ applyOptions: () => undefined }) };
      h.series.push(s);
      return s;
    },
    timeScale: () => ({
      fitContent: h.fitContent,
      setVisibleRange: h.setVisibleRange,
      subscribeVisibleLogicalRangeChange: () => undefined,
      setVisibleLogicalRange: () => undefined,
    }),
    subscribeCrosshairMove: (fn: (p: unknown) => void) => {
      h.crosshair = fn;
    },
    applyOptions: () => undefined,
    remove: () => undefined,
  }),
}));

beforeEach(() => {
  h.series.length = 0;
  h.setVisibleRange.mockClear();
  h.fitContent.mockClear();
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  document.documentElement.classList.remove("dark");
});

const bars = [
  { t: "2025-01-02", o: 1, h: 2, l: 1, c: 2, v: 10 },
  { t: "2026-10-01", o: 3, h: 4, l: 3, c: 4, v: 10 },
  { t: "2026-11-06", o: 5, h: 6, l: 5, c: 6, v: 10 },
];
const data = { symbol: "X", source: "nse", bars, indicators: {}, actions: [] } as unknown as PriceSeries;

test("chart colours differ between dark and light", () => {
  const light = chartColors();
  document.documentElement.classList.add("dark");
  const dark = chartColors();
  expect(dark.background).not.toBe(light.background);
  expect(dark.text).not.toBe(light.text);
});

test("rangeFrom picks the first bar inside the window, or null for All", () => {
  expect(rangeFrom(bars, 30)).toBe("2026-11-06"); // cutoff 2026-10-07: the 10-01 bar is too old
  expect(rangeFrom(bars, 91)).toBe("2026-10-01"); // cutoff 2026-08-07
  expect(rangeFrom(bars, null)).toBeNull();
  expect(rangeFrom([], 30)).toBeNull();
});

test("timeframe buttons set the visible range without new data", () => {
  render(<PriceChart data={data} active={[]} catalogue={[]} />);
  // default 1Y: one year before 2026-11-06 is 2025-11-06, so the first bar from then on is 2026-10-01
  expect(h.setVisibleRange).toHaveBeenLastCalledWith({ from: "2026-10-01", to: "2026-11-06" });
  fireEvent.click(screen.getByRole("button", { name: "1M" }));
  expect(h.setVisibleRange).toHaveBeenLastCalledWith({ from: "2026-11-06", to: "2026-11-06" });
  fireEvent.click(screen.getByRole("button", { name: "All" }));
  expect(h.fitContent).toHaveBeenCalled();
});

test("legend shows the last bar, then the hovered bar", () => {
  render(<PriceChart data={data} active={[]} catalogue={[]} />);
  expect(screen.getByTestId("legend").textContent).toContain("C 6.00");
  act(() => h.crosshair?.({ time: "2026-10-01", seriesData: new Map([[h.series[0], { open: 3, high: 4, low: 3, close: 4 }]]) }));
  expect(screen.getByTestId("legend").textContent).toContain("2026-10-01");
  expect(screen.getByTestId("legend").textContent).toContain("C 4.00");
  act(() => h.crosshair?.({ time: undefined, seriesData: new Map() }));
  expect(screen.getByTestId("legend").textContent).toContain("C 6.00");
});
