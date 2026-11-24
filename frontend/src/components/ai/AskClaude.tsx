import { useEffect, useRef, useState } from "react";
import { ApiError, api } from "../../api/client";
import type { AiCreated } from "../../api/types";
import { Button } from "@/components/ui/button";
import { useIsPhone } from "@/lib/useIsPhone";
import Markdown from "./Markdown";
import PasteAnswerDialog from "./PasteAnswerDialog";

interface AiRequest {
  id: number;
  status: string;
  response: string | null;
  error: string | null;
  run_id: number | null;
}

interface AiStatus {
  available: boolean;
  detail: string | null;
}

interface Props {
  kind: string;
  symbol: string;
  payload?: Record<string, unknown>;
  label: string;
  /** Called once with the finished response text. */
  onDone?: (response: string) => void;
}

const POLL_MS = 2000;
const msg = (e: unknown) => (e instanceof ApiError ? e.message : String(e));

export default function AskClaude({ kind, symbol, payload, label, onDone }: Props) {
  const [status, setStatus] = useState<AiStatus | null>(null);
  const [req, setReq] = useState<AiRequest | null>(null);
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [pending, setPending] = useState<{ id: number; prompt: string } | null>(null);
  const phone = useIsPhone();
  const doneRef = useRef(onDone);
  doneRef.current = onDone;

  useEffect(() => {
    api.get<AiStatus>("/ai/status").then(setStatus).catch(() => undefined);
  }, []);

  const id = req?.id;
  useEffect(() => {
    if (!busy || id === undefined) return;
    const started = Date.now();
    const tick = setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 1000);
    const poll = setInterval(() => {
      api
        .get<AiRequest>(`/ai/requests/${id}`)
        .then((r) => {
          if (r.status === "queued" || r.status === "running") return;
          setReq(r);
          setBusy(false);
          if (r.status === "done" && r.response) doneRef.current?.(r.response);
        })
        .catch((e) => {
          setError(msg(e));
          setBusy(false);
        });
    }, POLL_MS);
    return () => {
      clearInterval(tick);
      clearInterval(poll);
    };
  }, [busy, id]);

  const start = async () => {
    setError(null);
    setCopied(false);
    setElapsed(0);
    setReq(null);
    setBusy(true);
    try {
      const r = await api.post<AiCreated>("/ai/requests", { kind, symbol, payload });
      if (r.status === "awaiting_answer") {
        // copy_prompt provider (SPEC §17.7): no job, the owner pastes Claude's answer.
        setBusy(false);
        setPending({ id: r.id, prompt: r.prompt ?? "" });
        return;
      }
      setReq({ id: r.id, run_id: r.run_id, status: "queued", response: null, error: null });
    } catch (e) {
      setError(msg(e));
      setBusy(false);
    }
  };

  const stop = async () => {
    if (req?.run_id == null) return;
    try {
      await api.post(`/jobs/runs/${req.run_id}/stop`);
    } catch (e) {
      setError(msg(e));
    }
  };

  const copyPrompt = async () => {
    try {
      const r = payload
        ? await api.post<{ prompt: string }>("/ai/prompt", { kind, payload: { ...payload, symbol } })
        : await api.get<{ prompt: string }>(`/ai/prompt?kind=${encodeURIComponent(kind)}&symbol=${encodeURIComponent(symbol)}`);
      await navigator.clipboard.writeText(r.prompt);
      setCopied(true);
    } catch (e) {
      setError(msg(e));
    }
  };

  const saved = (r: AiRequest) => {
    setPending(null);
    setReq(r);
    if (r.status === "done" && r.response) doneRef.current?.(r.response);
  };

  const failed = req && (req.status === "failed" || req.status === "cancelled");
  const unavailable = status !== null && !status.available;

  return (
    <div className="ask-claude">
      {phone && unavailable ? (
        <div className="flex flex-col gap-2">
          <Button className="h-10 w-full" onClick={() => void copyPrompt()}>Copy prompt</Button>
          <p className="muted">Claude Code can't run on this device. Copy the prompt and paste it into claude.ai.</p>
        </div>
      ) : (
        <div className="card-head">
          <button type="button" disabled={busy || unavailable} onClick={() => void start()}>{label}</button>
          <button type="button" onClick={() => void copyPrompt()}>Copy prompt</button>
        </div>
      )}
      {unavailable && !phone && (
        <p className="muted">
          Claude isn't set up yet. Install Claude Code and log in: <code>npm i -g @anthropic-ai/claude-code</code>, then
          run <code>claude</code> once. You can still copy the prompt.
        </p>
      )}
      {busy && (
        <p role="status">
          <span aria-hidden="true">⏳</span> Claude is thinking… {elapsed}s{" "}
          <button type="button" onClick={() => void stop()}>Stop</button>
        </p>
      )}
      {copied && <p className="muted">Copied, paste into claude.ai</p>}
      {error && <p className="neg" role="alert">{error}</p>}
      {failed && (
        <div role="alert">
          <p className="neg">{req.error ?? `Request ${req.status}`}</p>
          <button type="button" onClick={() => void copyPrompt()}>Copy prompt instead</button>
        </div>
      )}
      {pending && (
        <PasteAnswerDialog<AiRequest>
          requestId={pending.id}
          prompt={pending.prompt}
          onSaved={saved}
          onClose={() => setPending(null)}
        />
      )}
      {req?.status === "done" && req.response && <Markdown text={req.response} />}
      <p className="muted">Uses your Claude Pro plan limits.</p>
    </div>
  );
}
