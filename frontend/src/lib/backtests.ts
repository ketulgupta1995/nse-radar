import type { Backtest, BacktestConfig, BacktestTrade, ExitDefInfo, ExitSpec, Screen } from "../api/types";
import { emptyRule } from "./rules";

export const DEFAULT_EXITS: ExitSpec[] = [
  { type: "stop_atr", params: { k: 2 } },
  { type: "target_atr", params: { k: 4 } },
  { type: "time_stop", params: { days: 40 } },
];

export const TREND_EXITS: ExitSpec[] = [
  { type: "stop_atr", params: { k: 3 } },
  {
    type: "rule_exit",
    params: {
      rule: {
        all: [{ left: { ind: "close" }, op: "<", right: { ind: "sma", params: { n: 50 } } }],
      },
    },
  },
  { type: "time_stop", params: { days: 80 } },
];

export const POSITION_EXITS: ExitSpec[] = [
  { type: "stop_atr", params: { k: 3 } },
  {
    type: "rule_exit",
    params: {
      rule: {
        all: [{ left: { ind: "close" }, op: "<", right: { ind: "sma", params: { n: 100 } } }],
      },
    },
  },
  { type: "time_stop", params: { days: 120 } },
];

export const SHORT_EXITS: ExitSpec[] = [
  {
    type: "rule_exit",
    params: {
      rule: {
        all: [{ left: { ind: "close" }, op: ">", right: { ind: "sma", params: { n: 5 } } }],
      },
    },
  },
  { type: "time_stop", params: { days: 10 } },
];

export const EXIT_SETS: { label: string; exits: ExitSpec[] }[] = [
  { label: "Swing (fixed target)", exits: DEFAULT_EXITS },
  { label: "Trend (trailing 50-day)", exits: TREND_EXITS },
  { label: "Position (trailing 100-day)", exits: POSITION_EXITS },
  { label: "Short dip (about a week)", exits: SHORT_EXITS },
];

/** A fresh exit of `def`'s type with every parameter at its default. */
export function newExit(def: ExitDefInfo): ExitSpec {
  const params: ExitSpec["params"] = {};
  for (const p of def.params) params[p.name] = p.default;
  if (def.type === "rule_exit") params.rule = emptyRule();
  return { type: def.type, params };
}

export const DEFAULT_CAPITAL = 1_000_000;

export function defaultConfig(holdoutStart: string, capital = DEFAULT_CAPITAL): Omit<BacktestConfig, "entry_rule"> {
  return {
    initial_capital: capital,
    exits: DEFAULT_EXITS.map((e) => ({ type: e.type, params: { ...e.params } })),
    max_positions: 10,
    sizing: "equal",
    risk_pct: 0.5,
    start: "2012-01-01",
    end: null,
    oos_start: holdoutStart,
    universe: "liquid500",
    rank_by: { ...RANK_CHOICES[0].rank_by, params: { ...RANK_CHOICES[0].rank_by.params } },
    max_per_industry: null,
    regime_scale: null,
  };
}

export const RANK_CHOICES: { label: string; rank_by: { ind: string; params: Record<string, number> } }[] = [
  { label: "Relative strength (126)", rank_by: { ind: "rel_strength", params: { n: 126 } } },
  { label: "Smooth momentum (126)", rank_by: { ind: "mom_smooth", params: { n: 126 } } },
  { label: "Results reaction %", rank_by: { ind: "results_move", params: { k: 2 } } },
  { label: "52-week closeness", rank_by: { ind: "pct_from_high", params: { n: 252 } } },
];

/** A form config copied from a finished backtest (everything but the entry rule). */
export function configFromBacktest(bt: Backtest, holdoutStart: string): Omit<BacktestConfig, "entry_rule"> {
  const rest: Partial<BacktestConfig> = { ...bt.config };
  delete rest.entry_rule;
  const base = defaultConfig(holdoutStart);
  return {
    ...base,
    ...rest,
    exits: structuredClone(rest.exits ?? base.exits),
    end: rest.end ?? null,
    oos_start: rest.oos_start ?? bt.metrics?.oos_start ?? holdoutStart,
  };
}

/** "Name" -> "Name v2", "Name v2" -> "Name v3". */
export function nextVersionName(name: string | null, id: number): string {
  const n = name || `Backtest ${id}`;
  const m = /^(.*) v(\d+)$/.exec(n);
  return m ? `${m[1]} v${Number(m[2]) + 1}` : `${n} v2`;
}

function sortKeys(v: unknown): unknown {
  if (Array.isArray(v)) return v.map(sortKeys);
  if (v && typeof v === "object") {
    return Object.fromEntries(
      Object.entries(v as Record<string, unknown>)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([k, x]) => [k, sortKeys(x)]),
    );
  }
  return v;
}

/** True when two rules are the same apart from key order. */
export function sameRule(a: unknown, b: unknown): boolean {
  return JSON.stringify(sortKeys(a)) === JSON.stringify(sortKeys(b));
}

const DAY_MS = 86_400_000;
const parseDay = (d: string) => Date.parse(`${d}T00:00:00Z`);
const iso = (ms: number) => new Date(ms).toISOString().slice(0, 10);

/** The API's 400 rules for the period fields; null when they are fine. */
export function periodError(start: string, oosStart: string, end: string | null): string | null {
  if (!start || !oosStart) return "Pick both a training start and a test start.";
  if (start >= oosStart) return "Train from must be earlier than Test from.";
  if (end && end <= oosStart) return "Test until must be later than Test from.";
  return null;
}

/** One-line summary of the training and test windows. `today` is injectable for tests. */
export function periodSummary(start: string, oosStart: string, end: string | null, today = new Date()): string {
  const years = (a: number, b: number) => ((b - a) / DAY_MS / 365.25).toFixed(1);
  const s = parseDay(start);
  const o = parseDay(oosStart);
  const trainEnd = iso(o - DAY_MS);
  const e = end ? parseDay(end) : parseDay(iso(today.getTime()));
  return (
    `Train ${start} → ${trainEnd} (${years(s, o)} years) · ` +
    `Test ${oosStart} → ${end ?? "latest"} (${years(o, e)} years, kept hidden until you run the final test)`
  );
}

export type FormConfig = Omit<BacktestConfig, "entry_rule">;

export interface VaryOption {
  key: string;
  label: string;
  short: string;
  kind: "int" | "float";
  min: number;
  max: number;
  target: { field: "max_positions" | "initial_capital" } | { exit: number; param: string };
}

/** Settings the owner can try several values of. */
export function varyOptions(cfg: FormConfig, defs: ExitDefInfo[]): VaryOption[] {
  const out: VaryOption[] = [
    { key: "max_positions", label: "Max positions", short: "Max positions", kind: "int", min: 1, max: 100,
      target: { field: "max_positions" } },
    { key: "initial_capital", label: "Starting money (₹)", short: "Starting money", kind: "int", min: 10000,
      max: 1_000_000_000, target: { field: "initial_capital" } },
  ];
  cfg.exits.forEach((e, i) => {
    const def = defs.find((d) => d.type === e.type);
    if (!def) return;
    for (const p of def.params) {
      if (typeof e.params[p.name] !== "number") continue;
      out.push({
        key: `exit:${i}:${p.name}`, label: `${def.label}: ${p.label}`, short: `${def.label} ${p.label}`,
        kind: p.kind, min: p.min, max: p.max, target: { exit: i, param: p.name },
      });
    }
  });
  return out;
}

export const MAX_VALUES = 10;

export type ParsedValues = { values: number[]; error: null } | { values: null; error: string };

/** The numbers typed in the values box, or an error message. */
export function parseValues(text: string, option: VaryOption): ParsedValues {
  const bad = (error: string): ParsedValues => ({ values: null, error });
  const parts = text.split(",").map((t) => t.trim()).filter((t) => t !== "");
  if (parts.length < 2) return bad("Enter at least 2 values, separated by commas.");
  if (parts.length > MAX_VALUES) return bad(`Enter at most ${MAX_VALUES} values.`);
  const values: number[] = [];
  for (const t of parts) {
    const n = Number(t);
    if (!Number.isFinite(n)) return bad(`"${t}" is not a number.`);
    if (n < option.min || n > option.max) return bad(`${t} is outside ${option.min} to ${option.max}.`);
    if (option.kind === "int" && !Number.isInteger(n)) return bad(`${t} must be a whole number.`);
    values.push(n);
  }
  if (new Set(values).size !== values.length) return bad("Each value must be different.");
  return { values, error: null };
}

/** One config per value, deep-copied, with only the chosen field changed. */
export function buildVariations(
  base: BacktestConfig,
  option: VaryOption,
  values: number[],
  name = "",
): { configs: BacktestConfig[]; names: string[] } {
  const configs = values.map((v) => {
    const c = structuredClone(base);
    if ("field" in option.target) c[option.target.field] = v;
    else c.exits[option.target.exit].params[option.target.param] = v;
    return c;
  });
  return { configs, names: values.map((v) => `${name || "Backtest"} · ${option.short} ${v}`) };
}

/** One config per screen: its rule as the entry rule, everything else from the form. */
export function buildScreenBatch(
  base: FormConfig,
  screens: Pick<Screen, "name" | "rule">[],
  exitSet = "custom exits",
): { configs: BacktestConfig[]; names: string[] } {
  return {
    configs: screens.map((s) => ({ ...structuredClone(base), entry_rule: structuredClone(s.rule) })),
    names: screens.map((s) => `${s.name} · ${exitSet}`),
  };
}

/** The label of the exit set the exits exactly match, or "custom exits". */
export function exitSetLabel(exits: ExitSpec[]): string {
  return EXIT_SETS.find((s) => sameRule(s.exits, exits))?.label ?? "custom exits";
}

export type TradeKey = keyof BacktestTrade;

export function sortTrades(rows: BacktestTrade[], key: TradeKey, dir: 1 | -1): BacktestTrade[] {
  return [...rows].sort((a, b) => {
    const x = a[key];
    const y = b[key];
    const c = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y));
    return c * dir || a.symbol.localeCompare(b.symbol);
  });
}
