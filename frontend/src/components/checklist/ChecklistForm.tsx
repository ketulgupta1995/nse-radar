import type { ChecklistQuestion } from "../../api/types";
import Explain from "../Explain";

export type FormValues = Record<string, string | boolean>;

/** Has the owner answered this question well enough to move on? */
export function isFilled(q: ChecklistQuestion, v: string | boolean | undefined): boolean {
  if (q.type === "bool") return q.must_be_true ? v === true : !q.required || v !== undefined;
  if (!q.required) return true;
  if (q.type === "number") return v !== undefined && v !== "" && Number(v) > 0;
  return typeof v === "string" && v.trim() !== "";
}

/** Convert form values into the answers object the API expects. */
export function toAnswers(questions: ChecklistQuestion[], values: FormValues): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const q of questions) {
    const v = values[q.id];
    if (v === undefined || v === "") continue;
    out[q.id] = q.type === "number" ? Number(v) : v;
  }
  return out;
}

interface Props {
  questions: ChecklistQuestion[];
  values: FormValues;
  onChange: (id: string, value: string | boolean) => void;
}

export default function ChecklistForm({ questions, values, onChange }: Props) {
  return (
    <div className="checklist-form">
      {questions.map((q) => {
        const v = values[q.id];
        const label = (
          <span>
            {q.label}
            {q.required && <span className="req"> *</span>}
            {q.help && <Explain text={q.help} />}
          </span>
        );
        if (q.type === "bool") {
          return (
            <label key={q.id} className="check">
              <input type="checkbox" checked={v === true} onChange={(e) => onChange(q.id, e.target.checked)} />
              {label}
            </label>
          );
        }
        return (
          <label key={q.id} className="field stacked">
            {label}
            {q.type === "text" && (
              <textarea rows={2} value={(v as string) ?? ""} onChange={(e) => onChange(q.id, e.target.value)} />
            )}
            {q.type === "number" && (
              <input type="number" step="any" value={(v as string) ?? ""} onChange={(e) => onChange(q.id, e.target.value)} />
            )}
            {q.type === "choice" && (
              <select value={(v as string) ?? ""} onChange={(e) => onChange(q.id, e.target.value)}>
                <option value="">Choose…</option>
                {q.choices?.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            )}
          </label>
        );
      })}
    </div>
  );
}
