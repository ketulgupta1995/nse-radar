import { useState } from "react";
import type { PriorityResponse } from "../../api/types";
import Explain from "../Explain";
import { Button } from "@/components/ui/button";

interface Props {
  priority: PriorityResponse;
  labels: Record<string, string>;
  onSave: (capability: string, names: string[]) => void;
}

/** Saved order first (only sources that still have the capability), then any others by name. */
export function currentOrder(priority: PriorityResponse, cap: string): string[] {
  const all = priority.capabilities[cap] ?? [];
  const saved = priority[cap];
  const listed = (Array.isArray(saved) ? saved : []).filter((n) => all.includes(n));
  return [...listed, ...all.filter((n) => !listed.includes(n)).sort()];
}

function Row({ cap, priority, labels, onSave }: Props & { cap: string }) {
  const start = currentOrder(priority, cap);
  const [order, setOrder] = useState(start);
  const dirty = order.join() !== start.join();

  function move(i: number, delta: number) {
    const next = [...order];
    const j = i + delta;
    if (j < 0 || j >= next.length) return;
    [next[i], next[j]] = [next[j], next[i]];
    setOrder(next);
  }

  return (
    <div className="priority-row">
      <h3>{cap}</h3>
      <ol>
        {order.map((name, i) => (
          <li key={name}>
            <span>{labels[name] ?? name}</span>{" "}
            <Button variant="outline" size="sm" type="button" aria-label={`Move ${labels[name] ?? name} up in ${cap}`} disabled={i === 0} onClick={() => move(i, -1)}>
              ↑
            </Button>{" "}
            <Button variant="outline" size="sm"
              type="button"
              aria-label={`Move ${labels[name] ?? name} down in ${cap}`}
              disabled={i === order.length - 1}
              onClick={() => move(i, 1)}
            >
              ↓
            </Button>
          </li>
        ))}
      </ol>
      <Button variant="outline" size="sm" type="button" disabled={!dirty} onClick={() => onSave(cap, order)}>
        Save {cap} order
      </Button>
    </div>
  );
}

export default function PriorityPanel({ priority, labels, onSave }: Props) {
  const caps = Object.keys(priority.capabilities).sort();
  return (
    <section>
      <h2>
        Priority
        <Explain text="For each stock, the app uses the first source in this list that has data. A source that is switched off is skipped." />
      </h2>
      <p className="muted">For each stock, the app uses the first source in this list that has data.</p>
      {caps.map((cap) => (
        <Row
          key={`${cap}:${currentOrder(priority, cap).join()}`}
          cap={cap}
          priority={priority}
          labels={labels}
          onSave={onSave}
        />
      ))}
    </section>
  );
}
