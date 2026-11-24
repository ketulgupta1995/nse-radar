import type { FundField, IndicatorDef } from "../../api/types";
import type { Operand } from "../../lib/rules";
import Explain from "../Explain";
import { useIsPhone } from "@/lib/useIsPhone";
import { cn } from "@/lib/utils";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";

export const PRICE_NAMES = ["close", "open", "high", "low", "volume"];

export interface RuleMeta {
  catalogue: IndicatorDef[];
  fields: FundField[];
  ops: { name: string; words: string }[];
}

/** "ind:sma" | "fund:roce_pct" | "number" */
export function operandKey(o: Operand): string {
  if ("ind" in o) return `ind:${o.ind}`;
  if ("fund" in o) return `fund:${o.fund}`;
  return "number";
}

function fresh(key: string, meta: RuleMeta): Operand {
  if (key === "number") return { value: 0 };
  if (key.startsWith("fund:")) return { fund: key.slice(5) };
  const def = meta.catalogue.find((d) => d.name === key.slice(4));
  const params = Object.fromEntries((def?.params ?? []).map((p) => [p.name, p.default]));
  return Object.keys(params).length ? { ind: key.slice(4), params } : { ind: key.slice(4) };
}

function clamp(v: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, v));
}

interface Props {
  value: Operand;
  onChange: (o: Operand) => void;
  meta: RuleMeta;
  label: string;
}

export default function OperandPicker({ value, onChange, meta, label }: Props) {
  const phone = useIsPhone();
  const full = phone ? "h-10 w-full" : undefined;
  const small = phone ? "h-10 w-24" : undefined;
  const key = operandKey(value);
  const prices = meta.catalogue.filter((d) => PRICE_NAMES.includes(d.name));
  const others = meta.catalogue.filter((d) => !PRICE_NAMES.includes(d.name));
  const def = "ind" in value ? meta.catalogue.find((d) => d.name === value.ind) : undefined;
  const field = "fund" in value ? meta.fields.find((f) => f.field === value.fund) : undefined;
  const times = "ind" in value || "fund" in value ? value.times : undefined;

  const setTimes = (raw: string) => {
    if (!("ind" in value || "fund" in value)) return;
    const next = { ...value } as Record<string, unknown>;
    const v = Number(raw);
    if (raw === "" || !Number.isFinite(v) || v <= 0) delete next.times;
    else next.times = v;
    onChange(next as unknown as Operand);
  };
  const setOffset = (raw: string) => {
    if (!("ind" in value)) return;
    const next = { ...value } as Record<string, unknown>;
    const v = Math.floor(Number(raw));
    if (raw === "" || !Number.isFinite(v) || v <= 0) delete next.offset;
    else next.offset = v;
    onChange(next as unknown as Operand);
  };

  return (
    <span className={cn("operand", phone && "flex w-full flex-col items-stretch gap-2")}>
      <Select className={full} aria-label={label} value={key} onChange={(e) => onChange(fresh(e.target.value, meta))}>
        <optgroup label="Price">
          {prices.map((d) => (
            <option key={d.name} value={`ind:${d.name}`}>{d.label}</option>
          ))}
        </optgroup>
        <optgroup label="Indicators">
          {others.map((d) => (
            <option key={d.name} value={`ind:${d.name}`}>{d.label}</option>
          ))}
        </optgroup>
        <optgroup label="Fundamentals">
          {meta.fields.filter((f) => f.numeric).map((f) => (
            <option key={f.field} value={`fund:${f.field}`}>{f.label}</option>
          ))}
        </optgroup>
        <optgroup label="Number">
          <option value="number">A number</option>
        </optgroup>
      </Select>
      {"value" in value && (
        <Input
          className={full}
          type="number"
          inputMode="decimal"
          step="any"
          aria-label={`${label} number`}
          value={value.value}
          onChange={(e) => {
            const v = Number(e.target.value);
            if (e.target.value !== "" && Number.isFinite(v)) onChange({ value: v });
          }}
        />
      )}
      {def && <Explain text={def.explain_default} />}
      {field && <Explain text={field.explain} />}
      {"ind" in value &&
        def?.params.map((p) => (
          <label key={p.name} className="param">
            {p.label}{" "}
            <Input
              className={small}
              type="number"
              inputMode="decimal"
              aria-label={`${label} ${p.label}`}
              min={p.min}
              max={p.max}
              step={p.kind === "int" ? 1 : "any"}
              value={value.params?.[p.name] ?? p.default}
              onChange={(e) => {
                const v = Number(e.target.value);
                if (e.target.value === "" || !Number.isFinite(v)) return;
                const c = clamp(p.kind === "int" ? Math.round(v) : v, p.min, p.max);
                onChange({ ...value, params: { ...value.params, [p.name]: c } });
              }}
            />
          </label>
        ))}
      {"ind" in value && (
        <label className="param">
          <input
            type="checkbox"
            aria-label={`${label} rank`}
            checked={value.rank === true}
            onChange={(e) => {
              const next = { ...value } as Record<string, unknown>;
              if (e.target.checked) next.rank = true;
              else delete next.rank;
              onChange(next as unknown as Operand);
            }}
          />{" "}
          Rank
          <Explain text="Use the stock's place among all stocks today instead of the raw number: 100 = the best, 90 = better than 90% of stocks. 'Rank is at least 90' means the top 10%." />
        </label>
      )}
      {!("value" in value) && (
        <label className="param">
          × times{" "}
          <Input
            className={small}
            type="number"
            inputMode="decimal"
            aria-label={`${label} times`}
            min={0}
            step="any"
            placeholder="1"
            value={times ?? ""}
            onChange={(e) => setTimes(e.target.value)}
          />
        </label>
      )}
      {"ind" in value && (
        <details className="advanced">
          <summary>advanced</summary>
          <label className="param">
            Value from N days ago{" "}
            <Input
              className={small}
              type="number"
              inputMode="decimal"
              aria-label={`${label} days ago`}
              min={0}
              step={1}
              placeholder="0"
              value={value.offset ?? ""}
              onChange={(e) => setOffset(e.target.value)}
            />
          </label>
        </details>
      )}
    </span>
  );
}
