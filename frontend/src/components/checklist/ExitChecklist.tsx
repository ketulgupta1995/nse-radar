import { useEffect, useState } from "react";
import { ApiError, api } from "../../api/client";
import type { ChecklistQuestion, ChecklistQuestions, Position } from "../../api/types";
import ChecklistForm, { isFilled, toAnswers } from "./ChecklistForm";
import type { FormValues } from "./ChecklistForm";
import Modal from "./Modal";

interface Props {
  position: Position;
  onClose: () => void;
  onClosed: (p: Position) => void;
}

export default function ExitChecklist({ position, onClose, onClosed }: Props) {
  const [questions, setQuestions] = useState<ChecklistQuestion[] | null>(null);
  const [values, setValues] = useState<FormValues>({
    exit_price: position.last_close != null ? String(position.last_close) : "",
  });
  const [exitDate, setExitDate] = useState(new Date().toISOString().slice(0, 10));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api
      .get<ChecklistQuestions>("/positions/checklist/questions")
      .then((q) => setQuestions(q.exit))
      .catch((e) => setError(e instanceof ApiError ? e.message : String(e)));
  }, []);

  const ok = (questions ?? []).every((q) => isFilled(q, values[q.id]));
  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      onClosed(
        await api.post<Position>(`/positions/${position.id}/close`, {
          exit_date: exitDate,
          answers: toAnswers(questions ?? [], values),
        }),
      );
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title={`Close ${position.symbol}`} onClose={onClose}>
      {!questions ? (
        error ? <p className="neg">{error}</p> : <p className="muted">Loading…</p>
      ) : (
        <>
          <ChecklistForm questions={questions} values={values} onChange={(id, v) => setValues((x) => ({ ...x, [id]: v }))} />
          <label className="field">
            <span>Exit date</span>
            <input type="date" value={exitDate} onChange={(e) => setExitDate(e.target.value)} />
          </label>
          {error && <p className="neg" role="alert">{error}</p>}
          <div className="modal-foot">
            <button type="button" disabled={!ok || saving} onClick={() => void save()}>Close position</button>
          </div>
        </>
      )}
    </Modal>
  );
}
