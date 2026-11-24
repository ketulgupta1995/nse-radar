import { expect, test } from "vitest";

import type { BacktestConfig, ExitDefInfo, Screen } from "../api/types";
import { buildScreenBatch, buildVariations, defaultConfig, parseValues, varyOptions } from "../lib/backtests";

const defs: ExitDefInfo[] = [
  { type: "stop_atr", label: "Stop-loss (ATR)", explain: "e", when: "intraday",
    params: [{ name: "k", kind: "float", default: 2, min: 0.1, max: 20, label: "ATRs below entry" }] },
  { type: "target_atr", label: "Target (ATR)", explain: "e", when: "intraday",
    params: [{ name: "k", kind: "float", default: 4, min: 0.1, max: 40, label: "ATRs above entry" }] },
  { type: "time_stop", label: "Time stop", explain: "e", when: "close",
    params: [{ name: "days", kind: "int", default: 40, min: 1, max: 500, label: "Trading days" }] },
  { type: "rule_exit", label: "Rule exit", explain: "e", when: "close", params: [] },
];
const rule = { all: [{ left: { ind: "close" }, op: ">", right: { value: 1 } }] } as Screen["rule"];
const base = (): BacktestConfig => ({ ...defaultConfig("2022-01-01"), entry_rule: rule });
const opts = () => varyOptions(base(), defs);
const byKey = (k: string) => opts().find((o) => o.key === k)!;

test("parseValues accepts comma separated numbers", () => {
  expect(parseValues("5, 8, 10", byKey("max_positions"))).toEqual({ values: [5, 8, 10], error: null });
});

test("parseValues rejects bad input", () => {
  const o = byKey("max_positions");
  for (const t of ["5", "1,2,3,4,5,6,7,8,9,10,11", "5, 5", "5, x", "5, 500", "5, 2.5", ""]) {
    expect(parseValues(t, o).error).toBeTruthy();
  }
  expect(parseValues("2.5, 3", byKey("exit:0:k")).error).toBeNull();
});

test("varyOptions lists settings and numeric exit params", () => {
  expect(opts().map((o) => o.label)).toEqual([
    "Max positions", "Starting money (₹)", "Stop-loss (ATR): ATRs below entry",
    "Target (ATR): ATRs above entry", "Time stop: Trading days",
  ]);
  const ruleOnly = { ...base(), exits: [{ type: "rule_exit", params: { rule } }] };
  expect(varyOptions(ruleOnly, defs)).toHaveLength(2);
});

test("buildVariations changes one field and leaves base alone", () => {
  const b = base();
  const copy = structuredClone(b);
  const out = buildVariations(b, byKey("max_positions"), [5, 8], "Swing test");
  expect(b).toEqual(copy);
  expect(out.configs.map((c) => c.max_positions)).toEqual([5, 8]);
  expect(out.configs[1]).toEqual({ ...copy, max_positions: 8 });
  expect(out.names[1]).toBe("Swing test · Max positions 8");
  const stop = buildVariations(b, byKey("exit:0:k"), [3, 4]);
  expect(stop.configs[0].exits[0].params.k).toBe(3);
  expect(stop.configs[0].exits[1]).toEqual(copy.exits[1]);
  expect(stop.names[0]).toMatch(/^Backtest · /);
});

test("buildScreenBatch sets each entry rule", () => {
  const other = { all: [{ left: { ind: "close" }, op: "<", right: { value: 9 } }] } as Screen["rule"];
  const { entry_rule: _drop, ...form } = base();
  void _drop;
  const out = buildScreenBatch(form, [{ name: "A", rule }, { name: "B", rule: other }]);
  expect(out.configs.map((c) => c.entry_rule)).toEqual([rule, other]);
  expect(out.names).toEqual(["A · custom exits", "B · custom exits"]);
});
