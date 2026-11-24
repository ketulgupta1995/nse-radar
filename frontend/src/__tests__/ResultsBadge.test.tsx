import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import ResultsBadge from "../components/ResultsBadge";

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test("shows the date with a warning tone when the results are close", () => {
  render(<ResultsBadge next={{ date: "2026-11-12", days: 3 }} />);
  const badge = screen.getByText("Results 12 Nov");
  expect(badge.className).toContain("text-warning");
  expect(screen.getByRole("button", { name: "Explain" })).toBeTruthy();
});

test("is muted when the results are far away", () => {
  render(<ResultsBadge next={{ date: "2026-12-05", days: 20 }} />);
  const badge = screen.getByText("Results 5 Dec");
  expect(badge.className).toContain("text-muted-foreground");
  expect(badge.className).not.toContain("text-warning");
});

test("says today and tomorrow", () => {
  const { rerender } = render(<ResultsBadge next={{ date: "2026-11-11", days: 0 }} />);
  expect(screen.getByText(/Results 11 Nov \(today\)/)).toBeTruthy();
  rerender(<ResultsBadge next={{ date: "2026-11-12", days: 1 }} />);
  expect(screen.getByText(/Results 12 Nov \(tomorrow\)/)).toBeTruthy();
});

test("withinDays moves the tone boundary", () => {
  render(<ResultsBadge next={{ date: "2026-11-20", days: 9 }} withinDays={7} />);
  expect(screen.getByText("Results 20 Nov").className).not.toContain("text-warning");
});

test("renders nothing for null", () => {
  const { container } = render(<ResultsBadge next={null} />);
  expect(container.innerHTML).toBe("");
});
