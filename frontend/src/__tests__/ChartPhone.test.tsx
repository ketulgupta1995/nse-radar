import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import type { PriceSeries } from "../api/types";
import PriceChart from "../components/chart/PriceChart";
import { setPhone } from "./phone";

const h = vi.hoisted(() => ({ heights: [] as number[] }));
vi.mock("lightweight-charts", () => ({
  CandlestickSeries: "candles",
  HistogramSeries: "hist",
  LineSeries: "line",
  createSeriesMarkers: () => undefined,
  createChart: (_el: unknown, o: { height: number }) => {
    h.heights.push(o.height);
    return {
      addSeries: () => ({ setData: () => undefined, priceScale: () => ({ applyOptions: () => undefined }) }),
      timeScale: () => ({
        fitContent: () => undefined,
        setVisibleRange: () => undefined,
        subscribeVisibleLogicalRangeChange: () => undefined,
        setVisibleLogicalRange: () => undefined,
      }),
      subscribeCrosshairMove: () => undefined,
      applyOptions: () => undefined,
      remove: () => undefined,
    };
  },
}));

const data = {
  symbol: "X",
  source: "nse",
  bars: [{ t: "2026-11-06", o: 5, h: 6, l: 5, c: 6, v: 10 }],
  indicators: {},
  actions: [],
} as unknown as PriceSeries;

beforeEach(() => {
  h.heights.length = 0;
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});
afterEach(() => {
  cleanup();
  act(() => setPhone(false));
  vi.unstubAllGlobals();
});

test("on a phone the chart gets a responsive height and a shorter second pane", () => {
  act(() => setPhone(true));
  render(<PriceChart data={data} active={[]} catalogue={[]} />);
  expect(screen.getByTestId("chart-main").style.height).toBe("max(220px, 60vw)");
  expect(h.heights).toEqual([220, 100]); // jsdom width is 0, so the 220 px floor applies
});

test("on a laptop the heights are unchanged", () => {
  act(() => setPhone(false));
  render(<PriceChart data={data} active={[]} catalogue={[]} />);
  expect(screen.getByTestId("chart-main").style.height).toBe("");
  expect(h.heights).toEqual([380, 140]);
});
