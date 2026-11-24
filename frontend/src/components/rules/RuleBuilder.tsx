import { useEffect, useState } from "react";
import { ApiError, api } from "../../api/client";
import type { FundField, IndicatorDef, RuleOp } from "../../api/types";
import { type Rule, withinLimits } from "../../lib/rules";
import GroupBox from "./GroupBox";
import type { RuleMeta } from "./OperandPicker";

const DESCRIBE_DELAY_MS = 400;

interface Props {
  value: Rule;
  onChange: (r: Rule) => void;
  /** Supply the dropdown contents (tests, or a parent that already loaded them); otherwise they're fetched. */
  meta?: RuleMeta;
}

function useMeta(given?: RuleMeta): RuleMeta | null {
  const [meta, setMeta] = useState<RuleMeta | null>(given ?? null);
  useEffect(() => {
    if (given) return;
    let live = true;
    Promise.all([
      api.get<IndicatorDef[]>("/indicators"),
      api.get<FundField[]>("/fundamentals/fields"),
      api.get<RuleOp[]>("/rules/ops"),
    ])
      .then(([catalogue, fields, ops]) => live && setMeta({ catalogue, fields, ops }))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [given]);
  return given ?? meta;
}

export default function RuleBuilder({ value, onChange, meta: given }: Props) {
  const meta = useMeta(given);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let stale = false;
    const t = setTimeout(() => {
      api
        .post<{ text: string }>("/rules/describe", value)
        .then((r) => {
          if (!stale) {
            setText(r.text);
            setError(null);
          }
        })
        .catch((e) => {
          if (!stale) {
            setText("");
            setError(e instanceof ApiError ? e.message : null);
          }
        });
    }, DESCRIBE_DELAY_MS);
    return () => {
      stale = true;
      clearTimeout(t);
    };
  }, [value]);

  if (!meta) return <p className="muted">Loading…</p>;
  return (
    <div className="rule-builder">
      <GroupBox
        root
        node={value}
        meta={meta}
        fits={withinLimits}
        onChange={(n) => {
          if (n !== null) onChange(n as Rule);
        }}
      />
      <p className="rule-describe" aria-live="polite">
        {error ? <span className="neg">{error}</span> : text ? <>In words: {text}</> : null}
      </p>
    </div>
  );
}
