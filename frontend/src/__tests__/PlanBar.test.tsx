import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";

import PlanBar, { planPositions } from "../components/positions/PlanBar";

afterEach(cleanup);

test("marker positions for entry 100, stop 90, target 120, last 110", () => {
  const p = planPositions(90, 100, 120, 110);
  expect(p.entry).toBeCloseTo(33.33, 1);
  expect(p.last).toBeCloseTo(66.67, 1);
});

test("markers are clamped to the bar", () => {
  expect(planPositions(90, 100, 120, 80).last).toBe(0);
  expect(planPositions(90, 100, 120, 150).last).toBe(100);
  expect(planPositions(90, 100, 120, null).last).toBeNull();
});

test("renders the marker and a tooltip with the numbers", () => {
  render(<PlanBar stop={90} entry={100} target={120} last={110} />);
  expect((screen.getByTestId("last-marker") as HTMLElement).style.left).toMatch(/^66\.6/);
  expect(screen.getByRole("img").getAttribute("title")).toContain("Target ₹120.00");
});
