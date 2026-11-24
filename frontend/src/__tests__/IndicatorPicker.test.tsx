import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, expect, test } from "vitest";

import type { IndicatorDef } from "../api/types";
import IndicatorPicker, { DEFAULT_INDICATORS, chipLabel, loadSelection, saveSelection } from "../components/chart/IndicatorPicker";

afterEach(() => {
  cleanup();
  localStorage.clear();
});

const catalogue: IndicatorDef[] = [
  { name: "sma", label: "Simple average", explain: "e {n}", explain_default: "Average of 20 days.", pane: "price", custom: false,
    params: [{ name: "n", kind: "int", default: 20, min: 2, max: 400, label: "Number of days" }] },
  { name: "rsi", label: "RSI", explain: "r", explain_default: "Momentum.", pane: "separate", custom: false,
    params: [{ name: "n", kind: "int", default: 14, min: 2, max: 50, label: "Number of days" }] },
];

function Harness({ onChange }: { onChange: (v: string[]) => void }) {
  const [v, setV] = useState(["sma:50"]);
  return <IndicatorPicker catalogue={catalogue} value={v} onChange={(n) => { setV(n); onChange(n); }} />;
}

test("adds and removes chips", () => {
  let last: string[] = [];
  render(<Harness onChange={(v) => (last = v)} />);
  expect(screen.getByText("Simple average (50)")).toBeTruthy();
  fireEvent.click(screen.getByText("+ add"));
  fireEvent.change(screen.getByLabelText("Indicator"), { target: { value: "rsi" } });
  expect(screen.getByText("Momentum.")).toBeTruthy();
  fireEvent.click(screen.getByText("Add to chart"));
  expect(last).toEqual(["sma:50", "rsi:14"]);
  expect(screen.getByText("RSI (14)")).toBeTruthy();
  fireEvent.click(screen.getByLabelText("Remove Simple average (50)"));
  expect(last).toEqual(["rsi:14"]);
});

test("selection persists in localStorage, with defaults", () => {
  expect(loadSelection()).toEqual(DEFAULT_INDICATORS);
  saveSelection(["ema:10"]);
  expect(loadSelection()).toEqual(["ema:10"]);
  expect(chipLabel("sma_slope:50:20", catalogue)).toBe("sma_slope (50, 20)");
});
