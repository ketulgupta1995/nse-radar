import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { RunSummary, Screen, ScreenResult } from "../api/types";
import ScreenEditor, { type Draft } from "../components/screens/ScreenEditor";
import ScreenList from "../components/screens/ScreenList";
import ScreenResults from "../components/screens/ScreenResults";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toaster";
import { emptyRule } from "../lib/rules";

const POLL_MS = 1500;

type Mode = { kind: "view" } | { kind: "edit"; id: number | null; draft: Draft };

export default function Screener() {
  const [screens, setScreens] = useState<Screen[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [results, setResults] = useState<ScreenResult[]>([]);
  const [mode, setMode] = useState<Mode>({ kind: "view" });
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [runText, setRunText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const msg = (e: unknown) => (e instanceof ApiError ? e.message : String(e));

  const loadScreens = useCallback(async () => {
    const list = await api.get<Screen[]>("/screens");
    setScreens(list);
    setLoaded(true);
    return list;
  }, []);

  useEffect(() => {
    loadScreens()
      .then((list) => setSelectedId((cur) => cur ?? list[0]?.id ?? null))
      .catch((e) => setError(msg(e)));
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [loadScreens]);

  const loadResults = useCallback(async (id: number) => {
    setResults(await api.get<ScreenResult[]>(`/screens/${id}/results`));
  }, []);

  useEffect(() => {
    setConfirmDelete(false);
    setRunText(null);
    if (selectedId === null) {
      setResults([]);
      return;
    }
    loadResults(selectedId).catch((e) => setError(msg(e)));
  }, [selectedId, loadResults]);

  const selected = screens.find((s) => s.id === selectedId) ?? null;

  const poll = (runId: number, screenId: number) => {
    api
      .get<RunSummary>(`/jobs/runs/${runId}`)
      .then(async (r) => {
        if (r.status === "queued" || r.status === "running") {
          setRunText(r.status === "queued" ? "Waiting in the queue…" : "Running…");
          timer.current = setTimeout(() => poll(runId, screenId), POLL_MS);
          return;
        }
        const done = r.status === "done";
        setRunText(done ? "Finished." : `Run ${r.status}${r.message ? `: ${r.message}` : ""}`);
        if (done) toast.success("Screen run finished.");
        else toast.error(`Run ${r.status}${r.message ? `: ${r.message}` : ""}`);
        await loadScreens();
        await loadResults(screenId);
      })
      .catch((e) => setRunText(`Couldn't read the run: ${msg(e)}`));
  };

  const runNow = async () => {
    if (!selected) return;
    setError(null);
    try {
      const { run_id } = await api.post<{ run_id: number }>(`/screens/${selected.id}/run`);
      setRunText("Waiting in the queue…");
      poll(run_id, selected.id);
    } catch (e) {
      setError(msg(e));
    }
  };

  const backtestThis = () => {
    if (selected) navigate(`/backtests/new?screen=${selected.id}`);
  };

  const doDelete = async () => {
    if (!selected) return;
    try {
      await api.del(`/screens/${selected.id}`);
      const list = await loadScreens();
      setSelectedId(list[0]?.id ?? null);
      setConfirmDelete(false);
      toast.success(`Deleted "${selected.name}".`);
    } catch (e) {
      setError(msg(e));
    }
  };

  const save = async (d: Draft) => {
    const body = { name: d.name, description: d.description || null, rule: d.rule };
    const editingId = mode.kind === "edit" ? mode.id : null;
    const saved =
      editingId === null
        ? await api.post<Screen>("/screens", body)
        : await api.put<Screen>(`/screens/${editingId}`, body);
    await loadScreens();
    setSelectedId(saved.id);
    await loadResults(saved.id);
    setMode({ kind: "view" });
    toast.success(`Saved "${saved.name}".`);
  };

  return (
    <div className="screener">
      <h1>Screener</h1>
      {error && <p className="neg" role="alert">{error}</p>}
      <div className="grid grid-cols-[260px_minmax(0,1fr)] items-start gap-6">
        {!loaded ? <Skeleton className="h-40" /> : <ScreenList
          screens={screens}
          selectedId={selectedId}
          onSelect={(id) => {
            setSelectedId(id);
            setMode({ kind: "view" });
          }}
          onNew={() => setMode({ kind: "edit", id: null, draft: { name: "", description: "", rule: emptyRule() } })}
          onDuplicate={(s) =>
            setMode({
              kind: "edit",
              id: null,
              draft: { name: `${s.name} (copy)`, description: s.description ?? "", rule: s.rule },
            })
          }
        />}
        <main>
          {mode.kind === "edit" ? (
            <ScreenEditor
              key={`${mode.id}-${mode.draft.name}`}
              initial={mode.draft}
              onSave={save}
              onCancel={() => setMode({ kind: "view" })}
            />
          ) : selected ? (
            <Card>
              <h2>{selected.name}</h2>
              {selected.description && <p>{selected.description}</p>}
              <p className="rule-describe">{selected.describe}</p>
              <p className="flex flex-wrap items-center gap-2">
                {!selected.is_preset && (
                  <Button
                    variant="outline"
                    onClick={() =>
                      setMode({
                        kind: "edit",
                        id: selected.id,
                        draft: { name: selected.name, description: selected.description ?? "", rule: selected.rule },
                      })
                    }
                  >
                    Edit
                  </Button>
                )}
                <Button onClick={runNow}>Run now</Button>
                <Button variant="outline" onClick={backtestThis}>Backtest this</Button>
                {!selected.is_preset &&
                  (confirmDelete ? (
                    <span role="group" aria-label="Confirm delete">
                      Delete "{selected.name}"?{" "}
                      <Button variant="danger" size="sm" onClick={doDelete}>Yes, delete</Button>{" "}
                      <Button variant="outline" size="sm" onClick={() => setConfirmDelete(false)}>Keep it</Button>
                    </span>
                  ) : (
                    <Button variant="outline" onClick={() => setConfirmDelete(true)}>Delete</Button>
                  ))}
              </p>
              {runText && <p className="muted" role="status">{runText}</p>}
              <ScreenResults results={results} />
            </Card>
          ) : (
            <EmptyState title="Pick a screen on the left, or start a new one." />
          )}
        </main>
      </div>
    </div>
  );
}
