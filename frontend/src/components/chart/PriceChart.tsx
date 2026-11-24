import {
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  createChart,
  createSeriesMarkers,
} from "lightweight-charts";
import type { IChartApi, SeriesMarker, Time } from "lightweight-charts";
import { useEffect, useRef, useState } from "react";
import type { IndicatorDef, PriceSeries } from "../../api/types";
import { Button } from "@/components/ui/button";
import { chartColors, useThemeVersion } from "@/lib/chartTheme";
import { chipLabel } from "./IndicatorPicker";

const PALETTE = ["#e6a23c", "#7b61ff", "#16a085", "#d6336c", "#2a9df4", "#8d6e63"];

interface Props {
  data: PriceSeries;
  active: string[];
  catalogue: IndicatorDef[];
}

export const TIMEFRAMES: [string, number | null][] = [["1M", 30], ["3M", 91], ["6M", 182], ["1Y", 365], ["All", null]];

/** First bar date to show for a timeframe, or null for "all the data". */
export function rangeFrom(bars: { t: string }[], days: number | null): string | null {
  if (days === null || bars.length === 0) return null;
  const last = new Date(`${bars[bars.length - 1].t}T00:00:00Z`);
  last.setUTCDate(last.getUTCDate() - days);
  const cutoff = last.toISOString().slice(0, 10);
  return bars.find((b) => b.t >= cutoff)?.t ?? bars[0].t;
}

interface LegendValue {
  label: string;
  color: string;
  value: number;
}
interface Legend {
  t: string;
  o: number;
  h: number;
  l: number;
  c: number;
  inds: LegendValue[];
}

const fmt = (n: number) => n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function markerFor(subject: string): { text: string } {
  return { text: /bonus/i.test(subject) ? "B" : "S" };
}

export default function PriceChart({ data, active, catalogue }: Props) {
  const mainRef = useRef<HTMLDivElement>(null);
  const subRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [range, setRange] = useState("1Y");
  const rangeRef = useRef(range);
  const [legend, setLegend] = useState<Legend | null>(null);
  const theme = useThemeVersion();

  const applyRange = (chart: IChartApi, key: string) => {
    const days = TIMEFRAMES.find(([k]) => k === key)?.[1] ?? null;
    const from = rangeFrom(data.bars, days);
    if (from === null) chart.timeScale().fitContent();
    else chart.timeScale().setVisibleRange({ from: from as Time, to: data.bars[data.bars.length - 1].t as Time });
  };

  useEffect(() => {
    const main = mainRef.current;
    const sub = subRef.current;
    if (!main || !sub) return;
    const c = chartColors();
    const opts = {
      layout: { background: { color: c.background }, textColor: c.text, fontFamily: "Inter Variable, system-ui, sans-serif" },
      grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
      crosshair: { vertLine: { color: c.crosshair }, horzLine: { color: c.crosshair } },
      // same axis width on both panes so their plot areas (and dates) line up
      rightPriceScale: { borderColor: c.grid, minimumWidth: 80 },
      timeScale: { borderColor: c.grid },
    };
    const pos = c.up;
    const neg = c.down;

    const chart: IChartApi = createChart(main, { ...opts, height: 380, width: main.clientWidth });
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: pos, downColor: neg, borderVisible: false, wickUpColor: pos, wickDownColor: neg,
    });
    candles.setData(data.bars.map((b) => ({ time: b.t as Time, open: b.o, high: b.h, low: b.l, close: b.c })));
    const vol = chart.addSeries(HistogramSeries, { priceScaleId: "vol", priceFormat: { type: "volume" } });
    vol.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    vol.setData(
      data.bars.map((b) => ({ time: b.t as Time, value: b.v, color: b.c >= b.o ? `${pos}66` : `${neg}66` })),
    );

    const hasSub = active.some((spec) => {
      const def = catalogue.find((c) => c.name === spec.split(":")[0]);
      return def?.pane === "separate" && (data.indicators[spec]?.length ?? 0) > 0;
    });
    sub.style.display = hasSub ? "block" : "none"; // before createChart, so it gets the real width
    const subChart: IChartApi = createChart(sub, { ...opts, height: 140, width: sub.clientWidth });
    // blank points on every bar date keep both panes' bar positions identical
    subChart
      .addSeries(LineSeries, { lastValueVisible: false, priceLineVisible: false })
      .setData(data.bars.map((b) => ({ time: b.t as Time })));
    const lines: { series: ReturnType<typeof chart.addSeries>; label: string; color: string }[] = [];
    active.forEach((spec, i) => {
      const def = catalogue.find((c) => c.name === spec.split(":")[0]);
      const points = data.indicators[spec];
      if (!def || !points || points.length === 0 || def.pane === "none") return;
      const color = PALETTE[i % PALETTE.length];
      const line = (def.pane === "price" ? chart : subChart).addSeries(LineSeries, {
        color, lineWidth: 2, priceLineVisible: false, title: chipLabel(spec, catalogue),
      });
      line.setData(points.map((p) => ({ time: p.t as Time, value: p.v })));
      lines.push({ series: line, label: chipLabel(spec, catalogue), color });
    });

    // legend: OHLC and indicator values for the hovered bar (the last bar when not hovering)
    const lastLegend = (): Legend | null => {
      const b = data.bars[data.bars.length - 1];
      if (!b) return null;
      const inds = active.flatMap((spec, i) => {
        const pts = data.indicators[spec];
        const v = pts?.[pts.length - 1]?.v;
        return v === undefined ? [] : [{ label: chipLabel(spec, catalogue), color: PALETTE[i % PALETTE.length], value: v }];
      });
      return { t: b.t, o: b.o, h: b.h, l: b.l, c: b.c, inds };
    };
    setLegend(lastLegend());
    chart.subscribeCrosshairMove((param) => {
      const bar = param.seriesData.get(candles) as { open: number; high: number; low: number; close: number } | undefined;
      if (!param.time || !bar) {
        setLegend(lastLegend());
        return;
      }
      const inds = lines.flatMap((ln) => {
        const d = param.seriesData.get(ln.series) as { value?: number } | undefined;
        return d?.value === undefined ? [] : [{ label: ln.label, color: ln.color, value: d.value }];
      });
      setLegend({ t: String(param.time), o: bar.open, h: bar.high, l: bar.low, c: bar.close, inds });
    });

    const seen = new Set<string>();
    const markers: SeriesMarker<Time>[] = data.actions
      .filter((a) => (seen.has(a.ex_date) ? false : (seen.add(a.ex_date), true)))
      .filter((a) => data.bars.some((b) => b.t >= a.ex_date))
      .map((a) => ({
        time: (data.bars.find((b) => b.t >= a.ex_date) ?? data.bars[0]).t as Time,
        position: "aboveBar" as const,
        shape: "arrowDown" as const,
        color: c.accent,
        text: markerFor(a.subject).text,
      }));
    if (markers.length) createSeriesMarkers(candles, markers);

    // keep the two time axes in step, whichever pane is scrolled or zoomed
    let syncing = false;
    const follow = (from: IChartApi, to: IChartApi) =>
      from.timeScale().subscribeVisibleLogicalRangeChange((r) => {
        if (!r || syncing || !hasSub) return;
        syncing = true;
        to.timeScale().setVisibleLogicalRange(r);
        syncing = false;
      });
    follow(chart, subChart);
    follow(subChart, chart);
    chartRef.current = chart;
    applyRange(chart, rangeRef.current);

    const ro = new ResizeObserver(() => {
      chart.applyOptions({ width: main.clientWidth });
      subChart.applyOptions({ width: sub.clientWidth });
    });
    ro.observe(main);
    ro.observe(sub);
    return () => {
      ro.disconnect();
      chartRef.current = null;
      chart.remove();
      subChart.remove();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, active, catalogue, theme]);

  const pickRange = (key: string) => {
    setRange(key);
    rangeRef.current = key;
    if (chartRef.current) applyRange(chartRef.current, key);
  };

  const actions = data.actions.filter((a, i, all) => all.findIndex((x) => x.ex_date === a.ex_date) === i);
  return (
    <div className="price-chart">
      <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1">
        <div className="flex gap-1" role="group" aria-label="Timeframe">
          {TIMEFRAMES.map(([k]) => (
            <Button key={k} variant={k === range ? "default" : "outline"} size="sm" aria-pressed={k === range} onClick={() => pickRange(k)}>
              {k}
            </Button>
          ))}
        </div>
        {legend && (
          <div className="font-mono text-xs" aria-label="Chart legend" data-testid="legend">
            <span className="text-muted-foreground">{legend.t}</span>{" "}
            O {fmt(legend.o)} H {fmt(legend.h)} L {fmt(legend.l)} C {fmt(legend.c)}
            {legend.inds.map((i) => (
              <span key={i.label} style={{ color: i.color }}> {i.label} {fmt(i.value)}</span>
            ))}
          </div>
        )}
      </div>
      <div ref={mainRef} />
      <div ref={subRef} style={{ display: "none" }} />
      {actions.length > 0 && (
        <p className="muted">
          Markers: {actions.map((a) => `${markerFor(a.subject).text} = ${a.subject} (${a.ex_date})`).join(" · ")}
        </p>
      )}
    </div>
  );
}
