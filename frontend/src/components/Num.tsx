export type NumKind = "pct" | "inr" | "cr" | "plain";

export function formatNum(value: number | null | undefined, kind: NumKind, digits?: number): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  switch (kind) {
    case "inr": {
      const s = Math.abs(value).toLocaleString("en-IN", {
        minimumFractionDigits: digits ?? 0,
        maximumFractionDigits: digits ?? 0,
      });
      return `${value < 0 ? "-" : ""}₹${s}`;
    }
    case "cr": {
      const s = Math.abs(value).toLocaleString("en-IN", {
        minimumFractionDigits: digits ?? 0,
        maximumFractionDigits: digits ?? 0,
      });
      return `${value < 0 ? "-" : ""}₹${s} Cr`;
    }
    case "pct": {
      const d = digits ?? 1;
      const s = value.toFixed(d);
      return `${value > 0 ? "+" : ""}${s}%`;
    }
    default:
      return value.toLocaleString("en-IN", {
        minimumFractionDigits: digits ?? 0,
        maximumFractionDigits: digits ?? 2,
      });
  }
}

interface Props {
  value: number | null | undefined;
  kind?: NumKind;
  digits?: number;
  /** Colour by the sign of `value`. Gains green, losses red: use only for P&L and price direction. */
  colored?: boolean;
  /** Colour by the sign of this change instead (for a price shown next to its change). */
  delta?: number | null;
  /** Right-align (for table cells). */
  right?: boolean;
}

export default function Num({ value, kind = "plain", digits, colored, delta, right }: Props) {
  const sign = delta !== undefined ? delta : colored ? value : null;
  const tone = sign ? (sign > 0 ? "pos" : sign < 0 ? "neg" : "") : "";
  const cls = ["num", tone, right ? "block text-right" : ""].filter(Boolean).join(" ");
  return <span className={cls}>{formatNum(value, kind, digits)}</span>;
}
