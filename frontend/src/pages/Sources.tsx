import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "../api/client";
import type { PriorityResponse, SourceInfo } from "../api/types";
import CoveragePanel from "../components/sources/CoveragePanel";
import PriorityPanel from "../components/sources/PriorityPanel";
import SourceCard from "../components/sources/SourceCard";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toaster";

export default function Sources() {
  const [sources, setSources] = useState<SourceInfo[]>([]);
  const [priority, setPriority] = useState<PriorityResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [coverageKey, setCoverageKey] = useState(0);

  const load = useCallback(async () => {
    try {
      const [s, p] = await Promise.all([
        api.get<SourceInfo[]>("/sources"),
        api.get<PriorityResponse>("/sources/priority"),
      ]);
      setSources(s);
      setPriority(p);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  async function act(fn: () => Promise<unknown>, done?: string) {
    try {
      await fn();
      setError(null);
      if (done) toast.success(done);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
    setCoverageKey((k) => k + 1);
    await load();
  }

  const labels = Object.fromEntries(sources.map((s) => [s.name, s.label]));

  return (
    <div>
      <h1>Sources</h1>
      <p className="muted">
        Where the data comes from. Switch a source off to stop using it; set the order below to choose which one wins.
      </p>
      {error && <p className="neg">{error}</p>}
      <div className="my-4 grid grid-cols-[repeat(auto-fill,minmax(320px,1fr))] gap-4">
        {sources.length === 0 && !error && <Skeleton className="h-32" />}
        {sources.map((s) => (
          <SourceCard
            key={s.name}
            source={s}
            onToggle={(enabled) => act(() => api.put(`/sources/${s.name}`, { enabled }), `${s.label} ${enabled ? "enabled" : "disabled"}.`)}
            onSecrets={(values) => act(() => api.put(`/sources/${s.name}/secrets`, values), `Saved settings for ${s.label}.`)}
          />
        ))}
      </div>
      {priority && (
        <PriorityPanel
          priority={priority}
          labels={labels}
          onSave={(cap, names) => act(() => api.put("/sources/priority", { [cap]: names }), "Source order saved.")}
        />
      )}
      <CoveragePanel labels={labels} refreshKey={coverageKey} />
    </div>
  );
}
