import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { ApiError, api } from "../api/client";
import type { ChecklistQuestions, Suggest } from "../api/types";
import EntryChecklist from "../components/checklist/EntryChecklist";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const q = (id: string, label: string, type: string, extra = {}) => ({ id, label, type, required: true, ...extra });
const questions = {
  entry: [
    q("thesis", "Why will this go up?", "text"), q("wrong_if", "What would prove me wrong?", "text"),
    q("catalyst", "Catalyst?", "text", { required: false }), q("source", "Source?", "text", { required: false }),
    q("entry_price", "Entry price", "number"), q("stop", "Stop-loss price", "number"),
    q("target", "Target price", "number"), q("time_stop_weeks", "Weeks", "number"),
    q("read_announcements", "Read announcements", "bool", { must_be_true: true }),
    q("checked_results", "Checked results", "bool", { must_be_true: true }),
    q("emotion", "How am I feeling?", "choice", { choices: ["calm", "FOMO", "revenge", "bored"] }),
  ],
  exit: [],
} as unknown as ChecklistQuestions;
const suggest: Suggest = {
  last_close: 100, atr14: 4, suggested_stop: 92, suggested_target: 116, risk_per_share: 8, qty: 625,
  capital: 500000, risk_pct: 1, rr: 2,
};

function setup() {
  vi.spyOn(api, "get").mockImplementation((path: string) => {
    if (path.startsWith("/positions/checklist")) return Promise.resolve(questions);
    if (path.startsWith("/positions/suggest")) return Promise.resolve(suggest);
    return Promise.reject(new ApiError(404, "no"));
  });
  render(<EntryChecklist symbol="AAA" onClose={() => undefined} onSaved={() => undefined} />);
}

const next = () => screen.getByText("Next") as HTMLButtonElement;

async function toPlan() {
  await waitFor(() => expect(screen.getByText(/Why will this go up/)).toBeTruthy());
  const boxes = screen.getAllByRole("textbox");
  fireEvent.change(boxes[0], { target: { value: "growth" } });
  fireEvent.change(boxes[1], { target: { value: "below 90" } });
  fireEvent.click(next());
}

test("Next is disabled until the required fields in the step are filled", async () => {
  setup();
  await waitFor(() => expect(screen.getByText(/Why will this go up/)).toBeTruthy());
  expect(next().disabled).toBe(true);
  const boxes = screen.getAllByRole("textbox");
  fireEvent.change(boxes[0], { target: { value: "growth" } });
  expect(next().disabled).toBe(true);
  fireEvent.change(boxes[1], { target: { value: "below 90" } });
  expect(next().disabled).toBe(false);
});

test("sizing box shows the suggested quantity and the loss", async () => {
  setup();
  await toPlan();
  await waitFor(() => expect(screen.getByText(/Quantity 625 shares/)).toBeTruthy());
  expect(screen.getByText(/Risk per share ₹8\.00/)).toBeTruthy();
  expect(screen.getByText(/lose ₹5,000\.00 = 1\.00% of capital/)).toBeTruthy();
  expect(screen.getByText("Reward/risk 2.0").className).not.toContain("neg");
  expect(next().disabled).toBe(false);
});

test("FOMO shows the warning", async () => {
  setup();
  await toPlan();
  await waitFor(() => expect(screen.getByText(/Quantity 625 shares/)).toBeTruthy());
  fireEvent.click(next());
  await waitFor(() => expect(screen.getByText("How am I feeling?")).toBeTruthy());
  expect(screen.queryByRole("alert")).toBeNull();
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "FOMO" } });
  expect(screen.getByRole("alert").textContent).toContain("Consider waiting a day");
  expect(next().disabled).toBe(true); // boxes not ticked yet
});

async function toConfirm(next_results: { date: string; days: number } | null) {
  vi.spyOn(api, "get").mockImplementation((path: string) => {
    if (path.startsWith("/positions/checklist")) return Promise.resolve(questions);
    if (path.startsWith("/positions/suggest")) return Promise.resolve({ ...suggest, next_results });
    return Promise.reject(new ApiError(404, "no"));
  });
  const { container } = render(<EntryChecklist symbol="AAA" onClose={() => undefined} onSaved={() => undefined} />);
  await toPlan();
  await waitFor(() => expect(screen.getByText(/Quantity 625 shares/)).toBeTruthy());
  fireEvent.click(next());
  await waitFor(() => expect(screen.getByText("How am I feeling?")).toBeTruthy());
  screen.getAllByRole("checkbox").forEach((b) => fireEvent.click(b));
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "calm" } });
  fireEvent.click(next());
  await waitFor(() => expect(screen.getByText("Save position")).toBeTruthy());
  fireEvent.change(container.ownerDocument.querySelector('input[type="date"]') as HTMLInputElement, {
    target: { value: "2026-11-11" },
  });
}

test("warns when the results fall inside the holding window, but still lets you save", async () => {
  await toConfirm({ date: "2026-12-01", days: 20 });
  expect(screen.getByText(/Results on 1 Dec fall inside your 8-week holding window/)).toBeTruthy();
  expect((screen.getByText("Save position") as HTMLButtonElement).disabled).toBe(false);
});

test("no callout when the results are after the time stop or unknown", async () => {
  await toConfirm({ date: "2027-03-01", days: 110 });
  expect(screen.queryByText(/holding window/)).toBeNull();
  cleanup();
  vi.restoreAllMocks();
  await toConfirm(null);
  expect(screen.queryByText(/holding window/)).toBeNull();
});
