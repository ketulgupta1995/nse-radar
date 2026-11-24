import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import type { ChecklistRecord, Position } from "../../api/types";
import { Card } from "@/components/ui/card";
import Num from "../Num";

function Answer({ label, value }: { label: string; value: unknown }) {
  if (value === undefined || value === "") return null;
  return (
    <>
      <dt>{label}</dt>
      <dd>{String(value)}</dd>
    </>
  );
}

export default function TradeCard({ position: p }: { position: Position }) {
  const [open, setOpen] = useState(false);
  const [lists, setLists] = useState<ChecklistRecord[] | null>(null);
  const [failed, setFailed] = useState(false);

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next && !lists) {
      api
        .get<ChecklistRecord[]>(`/positions/${p.id}/checklists`)
        .then(setLists)
        .catch(() => setFailed(true));
    }
  };
  const entry = lists?.find((c) => c.kind === "entry")?.answers ?? {};
  const exit = lists?.find((c) => c.kind === "exit")?.answers ?? {};

  return (
    <Card className="p-3">
      <button type="button" className="flex min-h-11 w-full cursor-pointer flex-wrap items-center gap-x-4 gap-y-1 border-0 bg-transparent p-0 text-left text-inherit" style={{ font: "inherit" }} aria-expanded={open} onClick={toggle}>
        <strong>{p.symbol}</strong>
        <span className="muted">{p.entry_date} → {p.exit_date}</span>
        <Num value={p.pnl_pct} kind="pct" colored />
        {p.r_multiple !== null && <span>{p.r_multiple > 0 ? "+" : ""}{p.r_multiple}R</span>}
        <span className="muted">{p.exit_reason}</span>
      </button>
      {open && (
        <div className="mt-3">
          {failed && <p className="neg">Couldn't load this trade's checklists.</p>}
          {!lists && !failed && <p className="muted">Loading…</p>}
          {lists && (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div>
                <h3>Why I bought</h3>
                <dl className="summary">
                  <Answer label="Thesis" value={entry.thesis} />
                  <Answer label="Wrong if" value={entry.wrong_if} />
                  <Answer label="Catalyst" value={entry.catalyst} />
                  <Answer label="Idea from" value={entry.source} />
                  <Answer label="Feeling" value={entry.emotion} />
                </dl>
              </div>
              <div>
                <h3>How it ended</h3>
                <dl className="summary">
                  <Answer label="Reason" value={exit.exit_reason} />
                  <Answer label="Thesis right?" value={exit.thesis_right} />
                  <Answer label="Lesson" value={exit.lesson} />
                </dl>
              </div>
            </div>
          )}
          <p><Link to={`/stock/${p.symbol}`}>Open {p.symbol}</Link></p>
        </div>
      )}
    </Card>
  );
}
