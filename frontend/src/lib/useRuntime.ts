import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Health, Runtime } from "../api/types";

// Where the backend runs (SPEC §17.2), read once from `/api/health` and shared by every caller.
let known: Runtime | null = null;
let pending: Promise<Runtime | null> | null = null;

/** Fetch the runtime once; a failed request is retried by the next caller. */
export function loadRuntime(): Promise<Runtime | null> {
  if (known) return Promise.resolve(known);
  pending ??= api
    .get<Health>("/health")
    .then((h) => (known = h.runtime ?? null))
    .catch(() => null)
    .finally(() => {
      pending = null;
    });
  return pending;
}

/** Tests only: forget the cached runtime. */
export function resetRuntime(): void {
  known = null;
  pending = null;
}

/** `"local"`, `"vercel"` or `"actions"`; null until `/api/health` answers (or if it can't). */
export function useRuntime(): Runtime | null {
  const [runtime, setRuntime] = useState<Runtime | null>(known);
  useEffect(() => {
    let alive = true;
    void loadRuntime().then((r) => {
      if (alive) setRuntime(r);
    });
    return () => {
      alive = false;
    };
  }, []);
  return runtime;
}
