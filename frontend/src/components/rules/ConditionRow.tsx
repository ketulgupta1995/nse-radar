import type { Cond } from "../../lib/rules";
import OperandPicker, { type RuleMeta } from "./OperandPicker";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { useIsPhone } from "@/lib/useIsPhone";

interface Props {
  cond: Cond;
  meta: RuleMeta;
  onChange: (c: Cond) => void;
  onRemove: () => void;
}

export default function ConditionRow({ cond, meta, onChange, onRemove }: Props) {
  const phone = useIsPhone();
  if (phone) {
    return (
      <div className="my-2 flex flex-col gap-2 rounded-card border border-border bg-card p-3" data-testid="condition-card">
        <OperandPicker label="Left side" value={cond.left} meta={meta} onChange={(left) => onChange({ ...cond, left })} />
        <Select className="h-10 w-full" aria-label="Comparison" value={cond.op} onChange={(e) => onChange({ ...cond, op: e.target.value })}>
          {meta.ops.map((o) => (
            <option key={o.name} value={o.name}>{o.words}</option>
          ))}
        </Select>
        <OperandPicker label="Right side" value={cond.right} meta={meta} onChange={(right) => onChange({ ...cond, right })} />
        <Button variant="outline" className="h-10 w-full" type="button" aria-label="Remove condition" onClick={onRemove}>
          🗑 Delete condition
        </Button>
      </div>
    );
  }
  return (
    <div className="condition-row">
      <OperandPicker label="Left side" value={cond.left} meta={meta} onChange={(left) => onChange({ ...cond, left })} />
      <Select aria-label="Comparison" value={cond.op} onChange={(e) => onChange({ ...cond, op: e.target.value })}>
        {meta.ops.map((o) => (
          <option key={o.name} value={o.name}>{o.words}</option>
        ))}
      </Select>
      <OperandPicker label="Right side" value={cond.right} meta={meta} onChange={(right) => onChange({ ...cond, right })} />
      <Button variant="outline" size="sm" type="button" aria-label="Remove condition" onClick={onRemove}>🗑</Button>
    </div>
  );
}
