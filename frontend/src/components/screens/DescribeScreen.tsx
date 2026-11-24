import { useEffect, useState } from "react";
import { ApiError, api } from "../../api/client";
import type { AiCreated, CustomIndicator } from "../../api/types";
import type { Rule } from "../../lib/rules";
import Explain from "../Explain";
import PasteAnswerDialog from "../ai/PasteAnswerDialog";
import CustomIndicatorReview from "./CustomIndicatorReview";
import { Button } from "@/components/ui/button";
import { useIsPhone } from "@/lib/useIsPhone";

export interface DescribeResult {
  ok: boolean;
  error?: string;
  rule?: Rule;
  name?: string;
  description?: string;
  describe?: string;
  need_custom_indicator?: { name?: string; description?: string };
}

interface AiRequest {
  id: number;
  status: string;
  error: string | null;
  run_id: number | null;
  result: DescribeResult | null;
}

export interface Accepted {
  name: string;
  description: string;
  rule: Rule;
}

interface Props {
  /** Load the proposed screen into the editor; `focus` is true for "Edit". */
  onAccept: (a: Accepted, focus: boolean) => void;
}

interface CodeResult {
  ok: boolean;
  error?: string;
  name?: string;
  explain?: string;
  params_schema?: unknown[];
  code?: string;
}

interface CodeRequest {
  id: number;
  status: string;
  error: string | null;
  run_id: number | null;
  result: CodeResult | null;
}

const POLL_MS = 2000;
const msg = (e: unknown) => (e instanceof ApiError ? e.message : String(e));

export default function DescribeScreen({ onAccept }: Props) {
  const phone = useIsPhone();
  const [text, setText] = useState("");
  const [req, setReq] = useState<AiRequest | null>(null);
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [rejected, setRejected] = useState(false);
  const [codeReq, setCodeReq] = useState<CodeRequest | null>(null);
  const [codeBusy, setCodeBusy] = useState(false);
  const [codeElapsed, setCodeElapsed] = useState(0);
  const [codeError, setCodeError] = useState<string | null>(null);
  const [codePrompt, setCodePrompt] = useState<string | null>(null);
  const [review, setReview] = useState<CustomIndicator | null>(null);
  const [rerun, setRerun] = useState(false);
  // copy_prompt provider (SPEC §17.7): a request waiting for the owner to paste Claude's answer.
  const [pending, setPending] = useState<{ id: number; prompt: string; what: "rule" | "code" } | null>(null);

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

  const finishCode = async (r: CodeRequest) => {
    if (r.status !== "done") {
      setCodeError(r.error ?? `Request ${r.status}`);
      return;
    }
    const res = r.result;
    if (!res?.ok || !res.code || !res.name) {
      setCodeError(res?.error ?? "Claude could not write the indicator.");
      return;
    }
    try {
      const created = await api.post<CustomIndicator>("/custom-indicators", {
        name: res.name,
        explain: res.explain,
        params_schema: res.params_schema ?? [],
        code: res.code,
      });
      setReview(created);
    } catch (e) {
      setCodeError(msg(e));
    }
  };

  const codeId = codeReq?.id;
  useEffect(() => {
    if (!codeBusy || codeId === undefined) return;
    const started = Date.now();
    const tick = setInterval(() => setCodeElapsed(Math.round((Date.now() - started) / 1000)), 1000);
    const poll = setInterval(() => {
      api
        .get<CodeRequest>(`/ai/requests/${codeId}`)
        .then((r) => {
          if (r.status === "queued" || r.status === "running") return;
          setCodeBusy(false);
          void finishCode(r);
        })
        .catch((e) => {
          setCodeError(msg(e));
          setCodeBusy(false);
        });
    }, POLL_MS);
    return () => {
      clearInterval(tick);
      clearInterval(poll);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [codeBusy, codeId]);

  const startCode = async () => {
    const need = req?.result?.need_custom_indicator;
    if (!need) return;
    setCodeError(null);
    setCodePrompt(null);
    setCodeElapsed(0);
    setCodeReq(null);
    setCodeBusy(true);
    try {
      const r = await api.post<AiCreated>("/ai/requests", {
        kind: "indicator_code",
        payload: need,
      });
      if (r.status === "awaiting_answer") {
        setCodeBusy(false);
        setPending({ id: r.id, prompt: r.prompt ?? "", what: "code" });
        return;
      }
      setCodeReq({ id: r.id, run_id: r.run_id, status: "queued", error: null, result: null });
    } catch (e) {
      setCodeError(msg(e));
      setCodeBusy(false);
    }
  };

  const stopCode = async () => {
    if (codeReq?.run_id == null) return;
    try {
      await api.post(`/jobs/runs/${codeReq.run_id}/stop`);
    } catch (e) {
      setCodeError(msg(e));
    }
  };

  const copyCodePrompt = async () => {
    try {
      const r = await api.post<{ prompt: string }>("/ai/prompt", {
        kind: "indicator_code",
        payload: req?.result?.need_custom_indicator ?? {},
      });
      setCodePrompt(r.prompt);
      await navigator.clipboard?.writeText(r.prompt);
    } catch (e) {
      setCodeError(msg(e));
    }
  };

  const start = async () => {
    setError(null);
    setRejected(false);
    setElapsed(0);
    setReq(null);
    setBusy(true);
    try {
      const r = await api.post<AiCreated>("/ai/requests", {
        kind: "rule_from_text",
        payload: { text: text.trim() },
      });
      if (r.status === "awaiting_answer") {
        setBusy(false);
        setPending({ id: r.id, prompt: r.prompt ?? "", what: "rule" });
        return;
      }
      setReq({ id: r.id, run_id: r.run_id, status: "queued", error: null, result: null });
    } catch (e) {
      setError(msg(e));
      setBusy(false);
    }
  };

  // After approval, re-run the original text request so the rule can use the new indicator.
  useEffect(() => {
    if (!rerun) return;
    setRerun(false);
    void start();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rerun]);

  const stop = async () => {
    if (req?.run_id == null) return;
    try {
      await api.post(`/jobs/runs/${req.run_id}/stop`);
    } catch (e) {
      setError(msg(e));
    }
  };

  const result = req?.status === "done" && !rejected ? req.result : null;
  const failed = req && (req.status === "failed" || req.status === "cancelled");
  const accept = (focus: boolean) => {
    if (!result?.rule) return;
    onAccept(
      { name: result.name ?? "AI screen", description: result.description ?? "", rule: result.rule },
      focus,
    );
    setRejected(true);
  };

  return (
    <div className="describe-screen">
      <label>
        Describe the stocks you want, in your own words{" "}
        <Explain text="Claude turns your sentence into a screen rule. You can review and change it before anything is saved." />
        <textarea
          rows={3}
          className={phone ? "block w-full" : undefined}
          value={text}
          placeholder="e.g. stocks near 52-week highs with rising profits and low debt"
          onChange={(e) => setText(e.target.value)}
        />
      </label>
      <p>
        <Button variant="outline" size="sm" className={phone ? "h-10 w-full" : undefined} disabled={busy || !text.trim()} onClick={() => void start()}>
          Make screen
        </Button>
      </p>
      {busy && (
        <p role="status">
          <span aria-hidden="true">⏳</span> Claude is thinking… {elapsed}s{" "}
          <Button variant="outline" size="sm" onClick={() => void stop()}>Stop</Button>
        </p>
      )}
      {error && <p className="neg" role="alert">{error}</p>}
      {failed && <p className="neg" role="alert">{req.error ?? `Request ${req.status}`}</p>}
      {result && !result.ok && <p className="neg" role="alert">{result.error ?? "Claude could not make a rule."}</p>}
      {result?.ok && result.need_custom_indicator && (
        <div role="status">
          <p>
            <strong>Needs a new indicator.</strong>{" "}
            {result.need_custom_indicator.description ?? result.need_custom_indicator.name}
          </p>
          <Button variant="outline" size="sm" disabled={codeBusy} onClick={() => void startCode()}>Review code</Button>
          {codeBusy && (
            <p role="status">
              <span aria-hidden="true">⏳</span> Claude is writing the indicator… {codeElapsed}s{" "}
              <Button variant="outline" size="sm" onClick={() => void stopCode()}>Stop</Button>
            </p>
          )}
          {codeError && (
            <div>
              <p className="neg" role="alert">{codeError}</p>
              <Button variant="outline" size="sm" onClick={() => void copyCodePrompt()}>Copy prompt</Button>
              {codePrompt && <p className="muted">Prompt copied. You can paste it into Claude yourself.</p>}
            </div>
          )}
        </div>
      )}
      {pending && (
        <PasteAnswerDialog<AiRequest & CodeRequest>
          requestId={pending.id}
          prompt={pending.prompt}
          onClose={() => setPending(null)}
          onSaved={(r) => {
            const what = pending.what;
            setPending(null);
            if (what === "rule") setReq(r);
            else {
              setCodeReq(r);
              void finishCode(r);
            }
          }}
        />
      )}
      {review && (
        <CustomIndicatorReview
          indicator={review}
          onClose={() => setReview(null)}
          onApproved={() => setRerun(true)}
        />
      )}
      {result?.ok && result.rule && (
        <div>
          <p>
            <strong>{result.name}</strong>
          </p>
          <p className="rule-describe">{result.describe}</p>
          <p>
            <Button variant="outline" size="sm" onClick={() => accept(false)}>Accept</Button>{" "}
            <Button variant="outline" size="sm" onClick={() => accept(true)}>Edit</Button>{" "}
            <Button variant="outline" size="sm" onClick={() => setRejected(true)}>Reject</Button>
          </p>
        </div>
      )}
    </div>
  );
}
