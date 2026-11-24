import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";

import { api } from "../api/client";
import type { SourceInfo } from "../api/types";
import FirstRunPanel, { barDays, pickJob } from "../components/FirstRunPanel";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const src = (name: string, capability: string, jobs: string[], enabled = true): SourceInfo =>
  ({ name, enabled, capabilities: [{ capability, mode: "x", adjusted: false, jobs }] }) as unknown as SourceInfo;
const priority = { universe: ["u1"], bars: ["b1", "b2"], capabilities: {} };
const sources = [
  src("u1", "universe", ["universe.u1"]),
  src("b1", "bars", ["bars.b1.backfill", "bars.b1.daily"]),
  src("b2", "bars", ["bars.b2"]),
];

test("pickJob prefers .daily, skips disabled sources, never hard-codes names", () => {
  expect(pickJob("bars", priority, sources)).toBe("bars.b1.daily");
  expect(pickJob("universe", priority, sources)).toBe("universe.u1");
  const off = [sources[0], src("b1", "bars", ["bars.b1.daily"], false), sources[2]];
  expect(pickJob("bars", priority, off)).toBe("bars.b2");
  expect(pickJob("bars", { bars: [] }, sources)).toBeNull();
});

test("barDays counts weekdays across the primary source's range", () => {
  const cov = [{ source: "b1", symbols: 5, first_date: "2026-11-02", last_date: "2026-11-06", rows: 25 }];
  expect(barDays(priority, cov)).toBe(5);
  expect(barDays(priority, [])).toBe(0);
});

function install(days: { first: string; last: string } | null, universe = 0) {
  vi.spyOn(api, "get").mockImplementation((p: string) => {
    if (p === "/data/health") return Promise.resolve({ universe });
    if (p === "/sources/priority") return Promise.resolve(priority);
    if (p === "/sources") return Promise.resolve(sources);
    return Promise.resolve(days ? [{ source: "b1", symbols: 1, first_date: days.first, last_date: days.last, rows: 1 }] : []);
  });
}
const panel = (onStarted = () => undefined) =>
  render(<MemoryRouter><FirstRunPanel reloadKey={0} onStarted={onStarted} /></MemoryRouter>);

test("shows the checklist on an empty install and runs the picked jobs", async () => {
  install(null);
  const post = vi.spyOn(api, "post").mockResolvedValue({});
  const started = vi.fn();
  panel(started);
  expect(await screen.findByText(/1\. Load the stock list/)).toBeTruthy();
  fireEvent.click(screen.getAllByText("Run")[0]);
  await waitFor(() => expect(post).toHaveBeenCalledWith("/jobs/universe.u1/run"));
  fireEvent.click(screen.getAllByText("Run")[0]);
  await waitFor(() => expect(post).toHaveBeenCalledWith("/jobs/bars.b1.daily/run"));
  expect(started).toHaveBeenCalledTimes(2);
});

test("hidden once the primary source covers 20 trading days", async () => {
  install({ first: "2026-10-01", last: "2026-11-06" }, 500);
  const { container } = panel();
  await waitFor(() => expect(vi.mocked(api.get)).toHaveBeenCalledTimes(4));
  await new Promise((r) => setTimeout(r, 20));
  expect(container.querySelector(".first-run")).toBeNull();
});

test("marks finished steps as done", async () => {
  install({ first: "2026-11-02", last: "2026-11-06" }, 500);
  panel();
  expect(await screen.findByText(/5 of 20 days so far/)).toBeTruthy();
  expect(screen.getAllByText("done")).toHaveLength(1);
});
