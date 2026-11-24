import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { ApiError, api } from "../api/client";
import type { CustomIndicator } from "../api/types";
import CustomIndicatorReview from "../components/screens/CustomIndicatorReview";

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

test("shows escaped code, warning, and trial values after approve", async () => {
  const post = vi.spyOn(api, "post").mockResolvedValue({ ...ind, status: "approved", sample: [1, null, 2.5] });
  render(<CustomIndicatorReview indicator={ind} onClose={() => {}} />);
  expect(screen.getByText(/'<b>'/)).toBeTruthy();
  expect(screen.getByText(/Only approve if you've read it/)).toBeTruthy();
  fireEvent.click(screen.getByText("Approve"));
  await waitFor(() => expect(screen.getByText("1.00, –, 2.50")).toBeTruthy());
  expect(post.mock.calls[0][0]).toBe("/custom-indicators/7/approve");
});

test("trial error keeps it pending", async () => {
  vi.spyOn(api, "post").mockRejectedValue(new ApiError(400, "ValueError: boom"));
  render(<CustomIndicatorReview indicator={ind} onClose={() => {}} />);
  fireEvent.click(screen.getByText("Approve"));
  await waitFor(() => expect(screen.getByText(/ValueError: boom/)).toBeTruthy());
  expect(screen.getByText(/still pending/)).toBeTruthy();
});
