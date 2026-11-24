import type { Cond } from "../../lib/rules";
import OperandPicker, { type RuleMeta } from "./OperandPicker";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";

interface Props {
  cond: Cond;
  meta: RuleMeta;
  onChange: (c: Cond) => void;
  onRemove: () => void;
}

export default function ConditionRow({ cond, meta, onChange, onRemove }: Props) {
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
