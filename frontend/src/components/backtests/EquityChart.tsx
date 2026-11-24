import { LineSeries, createChart, createSeriesMarkers } from "lightweight-charts";
import type { SeriesMarker, Time } from "lightweight-charts";
import { useEffect, useRef } from "react";
import type { EquityPoint } from "../../api/types";

function css(name: string, fallback: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

/** First point on or after the out-of-sample start, so the marker lands on a real bar. */
export function oosMarkerTime(points: EquityPoint[], oosStart: string | null): string | null {
  if (!oosStart) return null;
  return points.find((p) => p.t >= oosStart)?.t ?? null;
}

interface Props {
  points: EquityPoint[];
  oosStart: string | null;
}

export default function EquityChart({ points, oosStart }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || points.length === 0) return;
    const text = css("--text", "#1d2330");
    const grid = css("--border", "#dde1e8");
    const chart = createChart(el, {
      layout: { background: { color: "transparent" }, textColor: text },
      grid: { vertLines: { color: grid }, horzLines: { color: grid } },
      rightPriceScale: { borderColor: grid },
      timeScale: { borderColor: grid },
      height: 340,
      width: el.clientWidth,
    });
    const strat = chart.addSeries(LineSeries, {
      color: css("--accent", "#2a5bd7"), lineWidth: 2, priceLineVisible: false, title: "Strategy",
    });
    strat.setData(points.map((p) => ({ time: p.t as Time, value: p.v })));
    const bench = points.filter((p) => p.bench !== undefined);
    if (bench.length) {
      const b = chart.addSeries(LineSeries, {
        color: css("--muted", "#6a7385"), lineWidth: 2, priceLineVisible: false, title: "Nifty 500",
      });
      b.setData(bench.map((p) => ({ time: p.t as Time, value: p.bench as number })));
    }
    const at = oosMarkerTime(points, oosStart);
    if (at) {
      const marker: SeriesMarker<Time> = {
        time: at as Time, position: "aboveBar", shape: "arrowDown",
        color: css("--neg", "#c0392b"), text: "Out-of-sample starts",
      };
      createSeriesMarkers(strat, [marker]);
    }
    chart.timeScale().fitContent();
    const onResize = () => chart.applyOptions({ width: el.clientWidth });
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.remove();
    };
  }, [points, oosStart]);

  return <div ref={ref} className="equity-chart" aria-label="Account value over time, strategy against the Nifty 500" />;
}
