import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import Num, { formatNum } from "../components/Num";

test("inr uses Indian grouping", () => {
  expect(formatNum(123456, "inr")).toBe("₹1,23,456");
});
test("pct has sign and digits", () => {
  expect(formatNum(12.345, "pct", 1)).toBe("+12.3%");
  expect(formatNum(-2, "pct", 1)).toBe("-2.0%");
});
test("cr", () => {
  expect(formatNum(12345, "cr")).toBe("₹12,345 Cr");
});
test("null shows dash", () => {
  expect(formatNum(null, "inr")).toBe("—");
});
test("colored", () => {
  render(<Num value={5} kind="pct" colored />);
  expect(screen.getByText("+5.0%").className).toContain("pos");
});
