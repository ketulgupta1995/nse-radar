import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import Explain from "../components/Explain";
import Num from "../components/Num";
import { StatusChip, statusVariant } from "../components/ui/badge";
import { EmptyState } from "../components/ui/empty-state";

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test("Explain shows its text on focus and on click, and hides on Escape", async () => {
  render(<Explain text="What this means" />);
  const btn = screen.getByRole("button", { name: "Explain" });
  expect(screen.queryByText("What this means")).toBeNull();
  fireEvent.focus(btn);
  expect((await screen.findAllByText("What this means")).length).toBeGreaterThan(0);
  fireEvent.keyDown(btn, { key: "Escape" });
  await vi.waitFor(() => expect(screen.queryByText("What this means")).toBeNull());
  fireEvent.click(btn);
  expect((await screen.findAllByText("What this means")).length).toBeGreaterThan(0);
});

test("Num colours by the delta sign, not the value", () => {
  const { rerender } = render(<Num value={100} kind="inr" delta={-2} />);
  expect(screen.getByText("₹100").className).toContain("neg");
  rerender(<Num value={100} kind="inr" delta={3} />);
  expect(screen.getByText("₹100").className).toContain("pos");
  rerender(<Num value={100} kind="inr" />);
  expect(screen.getByText("₹100").className).not.toMatch(/pos|neg/);
});

test("StatusChip maps each status to a tone", () => {
  expect(statusVariant("running")).toBe("info");
  expect(statusVariant("done")).toBe("success");
  expect(statusVariant("failed")).toBe("danger");
  expect(statusVariant("cancelled")).toBe("warning");
  expect(statusVariant("interrupted")).toBe("warning");
  expect(statusVariant("queued")).toBe("neutral");
  render(<StatusChip status="failed" />);
  expect(screen.getByText("failed").className).toContain("text-danger");
});

test("EmptyState shows title and hint", () => {
  render(<EmptyState title="Nothing yet">Come back later</EmptyState>);
  expect(screen.getByText("Nothing yet")).toBeTruthy();
  expect(screen.getByText("Come back later")).toBeTruthy();
});
