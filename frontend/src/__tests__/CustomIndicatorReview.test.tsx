import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { ApiError, api } from "../api/client";
import type { CustomIndicator, RunSummary } from "../api/types";
import CustomIndicatorReview from "../components/screens/CustomIndicatorReview";
import { RUN_POLL_MS } from "../lib/runs";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const ind: CustomIndicator = {
  id: 7, name: "my_ind", explain: "Close minus open.", status: "pending", created_at: "x", approved_at: null,
  params_schema: [{ name: "n", kind: "int", default: 5, min: 1, max: 20, label: "Window" }],
  code: "def compute(frame, bench, **params):\n    return frame['close'] < 1 and '<b>'",
  problems: [],
};

const run = (over: Partial<RunSummary>): RunSummary => ({
  id: 41, job: "indicator_approve", trigger: "manual", status: "done", queued_at: "x", started_at: null,
  finished_at: null, duration_s: null, total: null, done: 1, ok: 1, skipped: 0, failed: 0, message: null,
  retry_of: null, ...over,
});

/** The approve POST starts a job; GET answers the run polls, then the indicator list. */
function backend(runs: RunSummary[], status: CustomIndicator["status"]) {
  const post = vi.spyOn(api, "post").mockResolvedValue({ ...ind, run_id: 41 });
  const get = vi.spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === "/jobs/runs/41") return runs.length > 1 ? runs.shift() : runs[0];
    if (path === "/custom-indicators") return [{ ...ind, id: 3, name: "other" }, { ...ind, status }];
    throw new Error(`unexpected ${path}`);
  });
  return { post, get };
}

test("shows escaped code, warning, then waits for the worker's trial run", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const msg = "Approved. Trial run on made-up prices, last 5 values: 1.00, –, 2.50, 3.00, 4.00";
  const { post } = backend([run({ status: "queued" }), run({ status: "done", message: msg })], "approved");
  const onApproved = vi.fn();
  render(<CustomIndicatorReview indicator={ind} onClose={() => {}} onApproved={onApproved} />);
  expect(screen.getByText(/'<b>'/)).toBeTruthy();
  expect(screen.getByText(/Only approve if you've read it/)).toBeTruthy();
  fireEvent.click(screen.getByText("Approve"));
  expect(await screen.findByText(/Waiting for the cloud worker/)).toBeTruthy();
  await vi.advanceTimersByTimeAsync(RUN_POLL_MS);
  await waitFor(() => expect(screen.getByText(/1\.00, –, 2\.50, 3\.00, 4\.00/)).toBeTruthy());
  expect(post.mock.calls[0][0]).toBe("/custom-indicators/7/approve");
  expect(onApproved).toHaveBeenCalledWith(expect.objectContaining({ id: 7, status: "approved" }));
  vi.useRealTimers();
});

test("a failed trial run keeps it pending and shows why", async () => {
  backend([run({ failed: 1, ok: 0, message: "Could not approve: The trial run took longer than 10 seconds" })], "pending");
  render(<CustomIndicatorReview indicator={ind} onClose={() => {}} />);
  fireEvent.click(screen.getByText("Approve"));
  await waitFor(() => expect(screen.getByText(/took longer than 10 seconds/)).toBeTruthy());
  expect(screen.queryByText(/Could not approve: Could not/)).toBeNull();
  expect(screen.getByText(/still pending/)).toBeTruthy();
});

test("a refused approval (400) keeps it pending", async () => {
  vi.spyOn(api, "post").mockRejectedValue(new ApiError(400, "ValueError: boom"));
  render(<CustomIndicatorReview indicator={ind} onClose={() => {}} />);
  fireEvent.click(screen.getByText("Approve"));
  await waitFor(() => expect(screen.getByText(/ValueError: boom/)).toBeTruthy());
  expect(screen.getByText(/still pending/)).toBeTruthy();
});
