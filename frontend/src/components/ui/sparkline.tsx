/** A tiny inline line for a run of values. Draws nothing for fewer than two numbers. */
export function Sparkline({ values, width = 80, height = 20 }: { values: number[]; width?: number; height?: number }) {
  if (values.length < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pts = values
    .map((v, i) => `${((i / (values.length - 1)) * width).toFixed(1)},${(height - 2 - ((v - min) / span) * (height - 4)).toFixed(1)}`)
    .join(" ");
  const up = values[values.length - 1] >= values[0];
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Trend" className="inline-block align-middle">
      <polyline points={pts} fill="none" stroke={up ? "var(--pos)" : "var(--neg)"} strokeWidth={1.5} strokeLinejoin="round" />
    </svg>
  );
}
