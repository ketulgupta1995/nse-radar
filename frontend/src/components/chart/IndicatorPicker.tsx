import { useState } from "react";
import type { IndicatorDef } from "../../api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Select } from "@/components/ui/select";
import { useIsPhone } from "@/lib/useIsPhone";

export const DEFAULT_INDICATORS = ["sma:50", "sma:200", "rsi:14"];
const KEY = "chart.indicators";

export function loadSelection(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? "null");
    if (Array.isArray(v) && v.every((x) => typeof x === "string")) return v;
  } catch {
    /* ignore */
  }
  return DEFAULT_INDICATORS;
}

export function saveSelection(v: string[]): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(v));
  } catch {
    /* ignore */
  }
}

/** "sma:50" -> "Simple average (50)" */
export function chipLabel(spec: string, catalogue: IndicatorDef[]): string {
  const [name, ...vals] = spec.split(":");
  const d = catalogue.find((c) => c.name === name);
  return `${d?.label ?? name}${vals.length ? ` (${vals.join(", ")})` : ""}`;
}

interface Props {
  catalogue: IndicatorDef[];
  value: string[];
  onChange: (v: string[]) => void;
}

export default function IndicatorPicker({ catalogue, value, onChange }: Props) {
  const phone = useIsPhone();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [vals, setVals] = useState<number[]>([]);
  const def = catalogue.find((c) => c.name === name);

  const pick = (n: string) => {
    setName(n);
    setVals(catalogue.find((c) => c.name === n)?.params.map((p) => p.default) ?? []);
  };
  const add = () => {
    if (!def) return;
    const spec = [def.name, ...vals].join(":");
    if (!value.includes(spec)) onChange([...value, spec]);
    setOpen(false);
    setName("");
  };

  const panel = (
    <>
      <Select aria-label="Indicator" value={name} onChange={(e) => pick(e.target.value)}>
        <option value="">Choose an indicator…</option>
        {catalogue.map((c) => (
          <option key={c.name} value={c.name}>{c.label}</option>
        ))}
      </Select>
      {def && (
        <>
          <p className="muted">{def.explain_default}</p>
          {def.params.map((p, i) => (
            <label key={p.name} className="flex items-center justify-between gap-2">
              <span>{p.label}</span>
              <Input className="w-24"
                type="number" min={p.min} max={p.max} value={vals[i] ?? p.default}
                onChange={(e) => setVals(vals.map((v, j) => (j === i ? Number(e.target.value) : v)))}
              />
            </label>
          ))}
          <Button onClick={add}>Add to chart</Button>
        </>
      )}
    </>
  );

  return (
    <div className="relative mb-2 flex flex-wrap items-center gap-1.5">
      {value.map((spec) => (
        <Badge key={spec} variant="info" className="gap-1 py-0.5">
          {chipLabel(spec, catalogue)}
          <button
            type="button"
            aria-label={`Remove ${chipLabel(spec, catalogue)}`}
            className="cursor-pointer border-0 bg-transparent p-0 text-inherit"
            onClick={() => onChange(value.filter((s) => s !== spec))}
          >
            ×
          </button>
        </Badge>
      ))}
      <Button variant="outline" size="sm" onClick={() => setOpen((o) => !o)}>
        + add
      </Button>
      {open && !phone && (
        <Card className="absolute left-0 top-9 z-20 flex w-[300px] flex-col gap-2 p-3 shadow-lg">
          {panel}
        </Card>
      )}
      {phone && (
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogContent
            aria-describedby={undefined}
            className="bottom-0 left-0 top-auto flex max-h-[85vh] w-full translate-x-0 flex-col gap-2 overflow-y-auto rounded-b-none border-x-0 border-b-0 p-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))]"
          >
            <DialogTitle className="text-base font-semibold">Add an indicator</DialogTitle>
            {panel}
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}
