import {
  type Cond,
  type Group,
  type Node,
  emptyCondition,
  isCond,
} from "../../lib/rules";
import ConditionRow from "./ConditionRow";
import type { RuleMeta } from "./OperandPicker";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";

interface Props {
  node: Group;
  meta: RuleMeta;
  /** Replace this box with `n`, or remove it with null. */
  onChange: (n: Node | null) => void;
  /** Would the whole rule stay within the depth and size limits if this box became `n`? */
  fits: (n: Node) => boolean;
  root?: boolean;
}

function items(g: Group): Node[] {
  return "all" in g ? g.all : "any" in g ? g.any : [];
}

function Child({ node, ...rest }: { node: Node } & Omit<Props, "node" | "root">) {
  if (isCond(node)) {
    const c: Cond = node;
    return (
      <ConditionRow
        cond={c}
        meta={rest.meta}
        onChange={(n) => rest.onChange(n)}
        onRemove={() => rest.onChange(null)}
      />
    );
  }
  return <GroupBox node={node} {...rest} />;
}

export default function GroupBox({ node, meta, onChange, fits, root }: Props) {
  if ("not" in node) {
    const inner = node.not;
    const unwrap = () => onChange(isCond(inner) ? (root ? { all: [inner] } : inner) : inner);
    return (
      <div className="group-box not-box">
        <label>
          <input type="checkbox" checked onChange={unwrap} /> NOT (the opposite of the following)
        </label>
        <div className="group-body">
          <Child
            node={inner}
            meta={meta}
            fits={(n) => fits({ not: n })}
            onChange={(n) => onChange(n === null ? null : { not: n })}
          />
        </div>
      </div>
    );
  }

  const kind = "all" in node ? "all" : "any";
  const list = items(node);
  const make = (next: Node[]): Group => (kind === "all" ? { all: next } : { any: next });
  const set = (next: Node[]) => {
    if (next.length === 0 && !root) onChange(null);
    else onChange(make(next));
  };
  const canAdd = (n: Node) => fits(make([...list, n]));
  const wrapNot = () => (fits({ not: node }) ? onChange({ not: node }) : undefined);

  return (
    <div className="group-box">
      <div className="group-head">
        <Select
          aria-label="Match mode"
          value={kind}
          onChange={(e) => onChange(e.target.value === "all" ? { all: list } : { any: list })}
        >
          <option value="all">all of these must be true</option>
          <option value="any">any of these</option>
        </Select>
        <label>
          <input type="checkbox" checked={false} disabled={!fits({ not: node })} onChange={wrapNot} /> NOT
        </label>
        {!root && (
          <Button variant="outline" size="sm" type="button" aria-label="Remove group" onClick={() => onChange(null)}>
            Remove group
          </Button>
        )}
      </div>
      <div className="group-body">
        {list.map((child, i) => (
          <Child
            key={i}
            node={child}
            meta={meta}
            fits={(n) => fits(make(list.map((c, j) => (j === i ? n : c))))}
            onChange={(n) => set(n === null ? list.filter((_, j) => j !== i) : list.map((c, j) => (j === i ? n : c)))}
          />
        ))}
        {list.length === 0 && <p className="neg">Add at least one condition.</p>}
      </div>
      <div className="group-foot">
        <Button variant="outline" size="sm" type="button" disabled={!canAdd(emptyCondition())} onClick={() => set([...list, emptyCondition()])}>
          + condition
        </Button>
        <Button variant="outline" size="sm"
          type="button"
          disabled={!canAdd({ all: [emptyCondition()] })}
          onClick={() => set([...list, { all: [emptyCondition()] }])}
        >
          + group
        </Button>
      </div>
    </div>
  );
}
