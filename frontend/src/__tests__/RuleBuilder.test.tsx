import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import type { IndicatorDef } from "../api/types";
import RuleBuilder from "../components/rules/RuleBuilder";
import type { RuleMeta } from "../components/rules/OperandPicker";
import { type Rule, countConditions, depthOf, emptyCondition, withinLimits } from "../lib/rules";

const price = (name: string): IndicatorDef => ({
  name, label: name[0].toUpperCase() + name.slice(1), explain: "p", explain_default: `The ${name}.`,
  params: [], pane: "price", custom: false,
});
const meta: RuleMeta = {
  catalogue: [
    price("close"), price("volume"),
    { name: "sma", label: "Simple average", explain: "s", explain_default: "Average of 50 days.", pane: "price",
      custom: false, params: [{ name: "n", kind: "int", default: 50, min: 2, max: 400, label: "Days" }] },
  ],
  fields: [
    { field: "roce_pct", label: "ROCE %", explain: "Profit on capital.", unit: "%", numeric: true },
    { field: "sector", label: "Sector", explain: "text", unit: "text", numeric: false },
  ],
  ops: [
    { name: ">", words: "is above" }, { name: ">=", words: "is at least" }, { name: "<", words: "is below" },
    { name: "<=", words: "is at most" }, { name: "crosses_above", words: "crosses above" },
    { name: "crosses_below", words: "crosses below" },
  ],
};

let latest: Rule;
function Harness({ start }: { start: Rule }) {
  const [rule, setRule] = useState<Rule>(start);
  latest = rule;
  return <RuleBuilder value={rule} onChange={setRule} meta={meta} />;
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ text: "Close is above the 50-day average" }), { status: 200 })));
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const one = (): Rule => ({ all: [emptyCondition()] });

test("adding a condition produces valid JSON", () => {
  render(<Harness start={one()} />);
  fireEvent.click(screen.getByText("+ condition"));
  expect(countConditions(latest)).toBe(2);
  expect(latest).toEqual({ all: [emptyCondition(), emptyCondition()] });
  expect(screen.getAllByLabelText("Left side")).toHaveLength(2);
});

test("ticking Rank adds rank: true and unticking removes it", () => {
  render(<Harness start={one()} />);
  const box = screen.getByLabelText("Left side rank");
  fireEvent.click(box);
  expect(JSON.stringify(latest)).toContain('"rank":true');
  fireEvent.click(screen.getByLabelText("Left side rank"));
  expect(JSON.stringify(latest)).not.toContain("rank");
});

test("switching ALL to ANY changes the key", () => {
  render(<Harness start={one()} />);
  fireEvent.change(screen.getByLabelText("Match mode"), { target: { value: "any" } });
  expect("any" in latest && !("all" in latest)).toBe(true);
  expect(countConditions(latest)).toBe(1);
});

test("removing the last condition of a nested group removes the group", () => {
  render(<Harness start={{ all: [emptyCondition(), { any: [emptyCondition()] }] }} />);
  const rows = screen.getAllByLabelText("Remove condition");
  fireEvent.click(rows[1]);
  expect(latest).toEqual({ all: [emptyCondition()] });
});

test("removing the last condition at the top shows a message", () => {
  render(<Harness start={one()} />);
  fireEvent.click(screen.getByLabelText("Remove condition"));
  expect(screen.getByText("Add at least one condition.")).toBeTruthy();
  expect(latest).toEqual({ all: [] });
});

test("indicator parameter inputs carry min and max and clamp typed values", () => {
  render(<Harness start={one()} />);
  const days = screen.getByLabelText("Right side Days") as HTMLInputElement;
  expect(days.min).toBe("2");
  expect(days.max).toBe("400");
  fireEvent.change(days, { target: { value: "9999" } });
  expect(JSON.stringify(latest)).toContain('"n":400');
  fireEvent.change(screen.getByLabelText("Right side Days"), { target: { value: "1" } });
  expect(JSON.stringify(latest)).toContain('"n":2');
});

test("operand kinds: fundamentals (numeric only), number, times and days-ago", () => {
  render(<Harness start={one()} />);
  const right = screen.getByLabelText("Right side") as HTMLSelectElement;
  const options = within(right).getAllByRole("option").map((o) => o.textContent);
  expect(options).toContain("ROCE %");
  expect(options).not.toContain("Sector");
  expect(within(right).getAllByRole("group").map((g) => g.getAttribute("label"))).toEqual([
    "Price", "Indicators", "Fundamentals", "Number",
  ]);
  fireEvent.change(right, { target: { value: "fund:roce_pct" } });
  expect(latest).toEqual({ all: [{ ...emptyCondition(), right: { fund: "roce_pct" } }] });
  fireEvent.change(screen.getByLabelText("Right side times"), { target: { value: "2" } });
  expect(JSON.stringify(latest)).toContain('"times":2');
  fireEvent.change(right, { target: { value: "number" } });
  fireEvent.change(screen.getByLabelText("Right side number"), { target: { value: "15" } });
  expect(latest).toEqual({ all: [{ ...emptyCondition(), right: { value: 15 } }] });
  fireEvent.change(screen.getByLabelText("Left side days ago"), { target: { value: "5" } });
  expect(JSON.stringify(latest)).toContain('"offset":5');
});

test("comparison words come from the ops list", () => {
  render(<Harness start={one()} />);
  const ops = within(screen.getByLabelText("Comparison")).getAllByRole("option").map((o) => o.textContent);
  expect(ops).toEqual(["is above", "is at least", "is below", "is at most", "crosses above", "crosses below"]);
  fireEvent.change(screen.getByLabelText("Comparison"), { target: { value: "crosses_above" } });
  expect(JSON.stringify(latest)).toContain('"op":"crosses_above"');
});

test("NOT wraps and unwraps; group depth is limited to 4", () => {
  render(<Harness start={one()} />);
  fireEvent.click(screen.getByLabelText("NOT"));
  expect("not" in latest).toBe(true);
  fireEvent.click(screen.getByLabelText(/NOT \(the opposite/));
  expect(latest).toEqual(one());
  // root + three nested groups = depth 4: the innermost box can't add a group, the root still can
  cleanup();
  const deep: Rule = { all: [{ all: [{ all: [{ all: [emptyCondition()] }] }] }] };
  expect(depthOf(deep)).toBe(4);
  expect(withinLimits(deep)).toBe(true);
  render(<Harness start={deep} />);
  const groupButtons = screen.getAllByText("+ group") as HTMLButtonElement[];
  expect(groupButtons[0].disabled).toBe(true); // innermost: a child group would be level 5
  expect(groupButtons[groupButtons.length - 1].disabled).toBe(false); // root: a sibling group fits
});

test("plain-English description is debounced and errors show inline", async () => {
  vi.useFakeTimers();
  render(<Harness start={one()} />);
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fireEvent.click(screen.getByText("+ condition"));
  fireEvent.click(screen.getByText("+ condition"));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(399);
  });
  expect(fetchMock).not.toHaveBeenCalled();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(2);
  });
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(screen.getByText(/In words: Close is above the 50-day average/)).toBeTruthy();

  fetchMock.mockImplementation(async () => new Response(JSON.stringify({ detail: "all[0].left.ind: unknown indicator 'x'" }), { status: 400 }));
  fireEvent.click(screen.getByText("+ condition"));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(500);
  });
  expect(screen.getByText("all[0].left.ind: unknown indicator 'x'")).toBeTruthy();
});
