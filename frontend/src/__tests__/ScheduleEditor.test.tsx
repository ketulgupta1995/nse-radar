import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import ScheduleEditor, { scheduleWords } from "../components/jobs/ScheduleEditor";
import type { Schedule } from "../api/types";

afterEach(cleanup);

const base: Schedule = {
  kind: "manual", interval_min: null, at_time: null, weekday: null, weekdays_only: 0, enabled: true, next_run_at: null,
};

test("daily 19:30 weekdays only emits a valid patch", () => {
  const onSave = vi.fn();
  render(<ScheduleEditor schedule={base} onSave={onSave} onCancel={() => {}} />);
  fireEvent.change(screen.getByLabelText("Kind"), { target: { value: "daily" } });
  fireEvent.change(screen.getByLabelText("Time"), { target: { value: "19:30" } });
  fireEvent.click(screen.getByLabelText("Weekdays only"));
  fireEvent.click(screen.getByText("Save"));
  expect(onSave).toHaveBeenCalledWith({ kind: "daily", at_time: "19:30", weekdays_only: true });
});

test("inputs depend on kind", () => {
  render(<ScheduleEditor schedule={base} onSave={() => {}} onCancel={() => {}} />);
  expect(screen.queryByLabelText("Time")).toBeNull();
  fireEvent.change(screen.getByLabelText("Kind"), { target: { value: "interval" } });
  expect(screen.getByLabelText("Minutes")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Kind"), { target: { value: "weekly" } });
  expect(screen.getByLabelText("Weekday")).toBeTruthy();
  expect(screen.getByLabelText("Time")).toBeTruthy();
});

test("schedule in words", () => {
  expect(scheduleWords({ ...base, kind: "daily", at_time: "19:30", weekdays_only: 1 })).toBe("Weekdays at 19:30");
  expect(scheduleWords({ ...base, kind: "interval", interval_min: 120 })).toBe("Every 2 h");
  expect(scheduleWords({ ...base, kind: "weekly", weekday: 0, at_time: "08:00" })).toBe("Mondays 08:00");
});
