import { useState } from "react";
import type { ExitDefInfo, ExitSpec } from "../../api/types";
import { newExit } from "../../lib/backtests";
import type { Rule } from "../../lib/rules";
import Explain from "../Explain";
import RuleBuilder from "../rules/RuleBuilder";

interface Props {
  defs: ExitDefInfo[];
  value: ExitSpec[];
  onChange: (v: ExitSpec[]) => void;
}

export default function ExitEditor({ defs, value, onChange }: Props) {
  const [adding, setAdding] = useState("");
  const byType = (t: string) => defs.find((d) => d.type === t);
  const setParam = (i: number, name: string, v: number | Rule) =>
    onChange(value.map((e, j) => (j === i ? { ...e, params: { ...e.params, [name]: v } } : e)));
  const add = () => {
    const def = byType(adding);
    if (!def) return;
    onChange([...value, newExit(def)]);
    setAdding("");
  };

  return (
    <div className="exit-editor">
      {value.length === 0 && <p className="muted">No exits yet. Without any, a stock is only sold at the end of the test.</p>}
      {value.map((e, i) => {
        const def = byType(e.type);
        return (
          <div key={`${e.type}-${i}`} className="exit-row card flex flex-col gap-2">
            <strong>{def?.label ?? e.type}</strong>
            {def && <Explain text={def.explain} />}{" "}
            <button type="button" onClick={() => onChange(value.filter((_, j) => j !== i))}>Remove</button>
            {def?.params.map((p) => (
              <label key={p.name}>
                {p.label}{" "}
                <input
                  type="number"
                  className="max-md:block max-md:h-10 max-md:w-full"
                  min={p.min}
                  max={p.max}
                  step={p.kind === "int" ? 1 : 0.1}
                  value={Number(e.params[p.name] ?? p.default)}
                  onChange={(ev) => setParam(i, p.name, Number(ev.target.value))}
                />
              </label>
            ))}
            {e.type === "rule_exit" && e.params.rule && typeof e.params.rule === "object" && (
              <RuleBuilder value={e.params.rule as Rule} onChange={(r) => setParam(i, "rule", r)} />
            )}
          </div>
        );
      })}
      <p>
        <select aria-label="Exit type to add" value={adding} onChange={(ev) => setAdding(ev.target.value)}>
          <option value="">Add an exit…</option>
          {defs.map((d) => (
            <option key={d.type} value={d.type}>{d.label}</option>
          ))}
        </select>{" "}
        <button type="button" disabled={!adding} onClick={add}>Add exit</button>
      </p>
    </div>
  );
}
