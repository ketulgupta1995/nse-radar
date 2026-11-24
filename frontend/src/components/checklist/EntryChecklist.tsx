import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { ApiError, api } from "../../api/client";
import type { ChecklistQuestion, ChecklistQuestions, NextResults, Position, Settings, Suggest } from "../../api/types";
import { formatNum } from "../Num";
import { shortDate } from "../ResultsBadge";
import AskClaude from "../ai/AskClaude";
import ChecklistForm, { isFilled, toAnswers } from "./ChecklistForm";
import type { FormValues } from "./ChecklistForm";
import Modal from "./Modal";

const STEPS = [
  { title: "Idea", ids: ["thesis", "wrong_if", "catalyst", "source"] },
  { title: "Plan", ids: ["entry_price", "stop", "target", "time_stop_weeks"] },
  { title: "Honesty check", ids: ["read_announcements", "checked_results", "emotion"] },
  { title: "Confirm", ids: [] },
];

interface Props {
  symbol: string;
  onClose: () => void;
  onSaved: (p: Position) => void;
  /** Slot for the "Challenge me" button (T046). */
  challenge?: ReactNode;
}

const today = () => new Date().toISOString().slice(0, 10);
const inr = (v: number) => formatNum(v, "inr", 2);

export default function EntryChecklist({ symbol, onClose, onSaved, challenge }: Props) {
  const [questions, setQuestions] = useState<ChecklistQuestion[] | null>(null);
  const [values, setValues] = useState<FormValues>({});
  const [qty, setQty] = useState("");
  const [capital, setCapital] = useState(0);
  const [step, setStep] = useState(0);
  const [entryDate, setEntryDate] = useState(today());
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [aiReview, setAiReview] = useState<string | null>(null);
  const [nextResults, setNextResults] = useState<NextResults | null>(null);
  const touched = useRef(new Set<string>());

  const apply = (s: Suggest, first: boolean) => {
    setCapital(s.capital);
    setNextResults(s.next_results ?? null);
    setValues((v) => {
      const next = { ...v };
      const set = (k: string, x: number | null) => {
        if (x !== null && (first || !touched.current.has(k))) next[k] = String(x);
      };
      if (first) set("entry_price", s.last_close);
      set("stop", s.suggested_stop);
      set("target", s.suggested_target);
      return next;
    });
    if (first || !touched.current.has("qty")) setQty(String(s.qty));
  };

  useEffect(() => {
    api
      .get<ChecklistQuestions>("/positions/checklist/questions")
      .then((q) => setQuestions(q.entry))
      .catch((e) => setError(e instanceof ApiError ? e.message : String(e)));
    api
      .get<Suggest>(`/positions/suggest?symbol=${encodeURIComponent(symbol)}`)
      .then((s) => apply(s, true))
      .catch(() => undefined); // no prices yet: the owner types the plan in by hand
    api
      .get<Settings>("/settings")
      .then((s) => setValues((v) => ({ time_stop_weeks: String(s.default_time_stop_weeks), ...v })))
      .catch(() => setValues((v) => ({ time_stop_weeks: "8", ...v })));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol]);

  const entry = Number(values.entry_price);
  const stop = Number(values.stop);
  const target = Number(values.target);

  // re-suggest when the entry or stop is edited
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    if (!(entry > 0)) return;
    const t = setTimeout(() => {
      const q = new URLSearchParams({ symbol, entry: String(entry) });
      if (touched.current.has("stop") && stop > 0) q.set("stop", String(stop));
      api.get<Suggest>(`/positions/suggest?${q}`).then((s) => apply(s, false)).catch(() => undefined);
    }, 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entry, touched.current.has("stop") ? stop : 0]);

  const byId = useMemo(() => Object.fromEntries((questions ?? []).map((q) => [q.id, q])), [questions]);
  const stepQs = (ids: string[]) => ids.map((id) => byId[id]).filter(Boolean);
  const change = (id: string, v: string | boolean) => {
    touched.current.add(id);
    setValues((x) => ({ ...x, [id]: v }));
  };

  const q = Number(qty);
  const risk = entry - stop;
  const planOk = entry > 0 && stop > 0 && stop < entry && target > entry && q > 0 && Number(values.time_stop_weeks) > 0;
  const loss = q * risk;
  const lossPct = capital ? (loss / capital) * 100 : 0;
  const rr = risk > 0 ? (target - entry) / risk : null;

  const stepOk =
    step === 1
      ? planOk
      : stepQs(STEPS[step].ids).every((qq) => isFilled(qq, values[qq.id]));
  const emotion = values.emotion as string | undefined;
  const weeks = Number(values.time_stop_weeks);
  const holdEnd = new Date(`${entryDate}T00:00:00Z`);
  holdEnd.setUTCDate(holdEnd.getUTCDate() + Math.round(weeks * 7));
  const resultsInWindow =
    nextResults !== null && weeks > 0 && !Number.isNaN(holdEnd.getTime()) &&
    nextResults.date <= holdEnd.toISOString().slice(0, 10);

  const answers = () => ({
    ...toAnswers(questions ?? [], values),
    risk_pct: Math.round(lossPct * 100) / 100,
  });

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const p = await api.post<Position>("/positions", { symbol, qty: q, entry_date: entryDate, answers: answers(), ai_review: aiReview });
      onSaved(p);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title={`Before you buy ${symbol}`} onClose={onClose}>
      {!questions ? (
        error ? <p className="neg">{error}</p> : <p className="muted">Loading…</p>
      ) : (
        <>
          <ol className="steps">
            {STEPS.map((s, i) => (
              <li key={s.title} className={i === step ? "active" : ""}>{s.title}</li>
            ))}
          </ol>

          {step === 0 && (
            <ChecklistForm questions={stepQs(STEPS[0].ids)} values={values} onChange={change} />
          )}

          {step === 1 && (
            <>
              <ChecklistForm questions={stepQs(STEPS[1].ids)} values={values} onChange={change} />
              <label className="field stacked">
                <span>Quantity (shares)</span>
                <input type="number" inputMode="numeric" value={qty} onChange={(e) => { touched.current.add("qty"); setQty(e.target.value); }} />
              </label>
              <div className="sizing card" aria-label="Position sizing">
                {risk > 0 ? (
                  <>
                    <div>Risk per share {inr(risk)}</div>
                    <div>Quantity {q.toLocaleString("en-IN")} shares ({inr(q * entry)})</div>
                    <div>
                      If stopped out you lose {inr(loss)} = {lossPct.toFixed(2)}% of capital
                    </div>
                    {rr !== null && <div className={rr < 1.5 ? "neg" : ""}>Reward/risk {rr.toFixed(1)}</div>}
                  </>
                ) : (
                  <div className="neg">The stop-loss must be below the entry price.</div>
                )}
              </div>
            </>
          )}

          {step === 2 && (
            <>
              <ChecklistForm questions={stepQs(STEPS[2].ids)} values={values} onChange={change} />
              {(emotion === "FOMO" || emotion === "revenge") && (
                <div className="banner warn" role="alert">Consider waiting a day. Decisions made in {emotion} mode are usually worse.</div>
              )}
            </>
          )}

          {step === 3 && (
            <>
              <dl className="summary">
                <dt>Idea</dt><dd>{String(values.thesis ?? "")}</dd>
                <dt>Wrong if</dt><dd>{String(values.wrong_if ?? "")}</dd>
                <dt>Buy</dt><dd>{q.toLocaleString("en-IN")} × {inr(entry)} = {inr(q * entry)}</dd>
                <dt>Stop / Target</dt><dd>{inr(stop)} / {inr(target)}</dd>
                <dt>Max loss</dt><dd>{inr(loss)} ({lossPct.toFixed(2)}% of capital)</dd>
                <dt>Time stop</dt><dd>{String(values.time_stop_weeks)} weeks</dd>
              </dl>
              <label className="field">
                <span>Entry date</span>
                <input type="date" value={entryDate} onChange={(e) => setEntryDate(e.target.value)} />
              </label>
              <div id="ai-challenge-slot">
                {challenge ?? (
                  <AskClaude kind="checklist_challenge" symbol={symbol} payload={{ answers: answers() }} label="Challenge me" onDone={setAiReview} />
                )}
              </div>
              {error && <p className="neg" role="alert">{error}</p>}
              {resultsInWindow && nextResults && (
                <div className="rounded-md border border-warning/40 bg-warning/15 px-3 py-2 text-sm text-warning" role="status">
                  Results on {shortDate(nextResults.date)} fall inside your {weeks}-week holding window. Decide now whether you'll hold through them.
                </div>
              )}
            </>
          )}

          <div className="modal-foot">
            {step > 0 && <button type="button" onClick={() => setStep(step - 1)}>Back</button>}
            {step < STEPS.length - 1 ? (
              <button type="button" disabled={!stepOk} onClick={() => setStep(step + 1)}>Next</button>
            ) : (
              <button type="button" disabled={saving || !planOk} onClick={() => void save()}>Save position</button>
            )}
          </div>
        </>
      )}
    </Modal>
  );
}
