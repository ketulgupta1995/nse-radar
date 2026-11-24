import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Runtime } from "../api/types";

export interface CloudInfo {
  runtime: Runtime;
  dispatch_configured?: boolean;
  last_dispatch_at?: string | null;
  queued?: number;
  running?: number;
  oldest_queued_at?: string | null;
}

const LOCAL: CloudInfo = { runtime: "local" };

/** `/api/cloud/status` (SPEC §17.4), fetched once per mount; `{runtime: "local"}` until it answers or if it fails. */
export function useCloud(): CloudInfo {
  const [info, setInfo] = useState<CloudInfo>(LOCAL);
  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const s = await api.get<Partial<CloudInfo>>("/cloud/status");
        if (alive && s && s.runtime) setInfo({ ...s, runtime: s.runtime });
      } catch {
        /* stay on the local default */
      }
    })();
    return () => {
      alive = false;
    };
  }, []);
  return info;
}
