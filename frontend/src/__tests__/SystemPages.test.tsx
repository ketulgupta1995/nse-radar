import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { api } from "../api/client";
import SettingsSection from "../components/SettingsSection";
import RunHistory from "../components/jobs/RunHistory";
import { toast } from "../components/ui/toaster";

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

test("run history lists runs with status chips and opens one on click", async () => {
  vi.spyOn(api, "get").mockResolvedValue([
    { id: 7, job: "prices", status: "failed", queued_at: "2026-11-09T10:00:00Z", started_at: null, duration_s: 12, ok: 3, failed: 1, skipped: 0, trigger: "schedule" },
  ] as never);
  const onOpen = vi.fn();
  render(<RunHistory onOpen={onOpen} />);
  expect(await screen.findByText("failed")).toBeTruthy();
  expect(screen.getByText("3 / 1 / 0")).toBeTruthy();
  fireEvent.click(screen.getByText("prices"));
  expect(onOpen).toHaveBeenCalledWith(7);
});

test("run history shows an empty state", async () => {
  vi.spyOn(api, "get").mockResolvedValue([] as never);
  render(<RunHistory onOpen={() => undefined} />);
  expect(await screen.findByText("No runs yet.")).toBeTruthy();
});

test("a settings section shows a toast when saved", async () => {
  const ok = vi.spyOn(toast, "success").mockReturnValue(1);
  render(<SettingsSection title="Money and risk" onSave={async () => undefined}><p>fields</p></SettingsSection>);
  fireEvent.click(screen.getByText("Save"));
  await waitFor(() => expect(ok).toHaveBeenCalledWith("Money and risk saved."));
  expect(screen.getByRole("status").textContent).toBe("Saved.");
});
