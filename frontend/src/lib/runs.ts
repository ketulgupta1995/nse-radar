import { api } from "../api/client";
import type { RunItem, RunSummary, Runtime } from "../api/types";

/** How often a page asks about a job it started (SPEC §17.5: heavy work runs as a job). */
export const RUN_POLL_MS = 2000;

export const runFinished = (r: RunSummary): boolean => r.status !== "queued" && r.status !== "running";

/** Plain words for a run that hasn't finished yet. Only on Vercel does a job wait for the cloud worker. */
export function runWaitText(r: RunSummary | null, runtime: Runtime | null): string {
  if (runtime !== "vercel") return "Running…";
  if (r?.status === "running") return "Running in the cloud worker…";
  return "Waiting for the cloud worker (usually 1–2 min to start)…";
}

/**
 * Poll `GET /jobs/runs/{id}` until the run ends and return its final summary.
 * `onUpdate` sees every poll (for the waiting text); `isCancelled` stops polling early (unmount).
 */
export async function waitForRun(
  runId: number,
  onUpdate?: (r: RunSummary) => void,
  isCancelled: () => boolean = () => false,
  everyMs: number = RUN_POLL_MS,
): Promise<RunSummary | null> {
  for (;;) {
    if (isCancelled()) return null;
    const r = await api.get<RunSummary>(`/jobs/runs/${runId}`);
    if (isCancelled()) return null;
    onUpdate?.(r);
    if (runFinished(r)) return r;
    await new Promise((resolve) => setTimeout(resolve, everyMs));
  }
}

/** The `ok` items of a finished run (the screen preview stores one per matching stock). */
export function runOkItems(runId: number): Promise<RunItem[]> {
  return api.get<RunItem[]>(`/jobs/runs/${runId}/items?status=ok&limit=1000`);
}
