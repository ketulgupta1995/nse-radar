import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api } from "../../api/client";
import type { ScreenPreview, ScreenPreviewStart } from "../../api/types";
import { runOkItems, runWaitText, waitForRun } from "../../lib/runs";
import type { Rule } from "../../lib/rules";
import type { ColumnDef } from "@tanstack/react-table";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
import Num from "../Num";
import DescribeScreen, { type Accepted } from "./DescribeScreen";
import RuleBuilder from "../rules/RuleBuilder";
import type { RuleMeta } from "../rules/OperandPicker";

export interface Draft {
  name: string;
  description: string;
  rule: Rule;
}

const PREVIEW_ROWS = 50;
type PreviewValues = ScreenPreview["rows"][number]["values"];

interface Props {
  initial: Draft;
  onSave: (d: Draft) => Promise<void>;
  onCancel: () => void;
  /** Slot above the rule builder (T047's "Describe in words" box). */
  aboveBuilder?: ReactNode;
  meta?: RuleMeta;
}

export default function ScreenEditor({ initial, onSave, onCancel, aboveBuilder, meta }: Props) {
  const [draft, setDraft] = useState<Draft>(initial);
  const [preview, setPreview] = useState<ScreenPreview | null>(null);
  const [busy, setBusy] = useState<"preview" | "save" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [waiting, setWaiting] = useState<string | null>(null);
  const alive = useRef(true);
  useEffect(() => () => void (alive.current = false), []);
  const msg = (e: unknown) => (e instanceof ApiError || e instanceof Error ? e.message : String(e));

  // The preview scans every stock, so it runs as a job in the worker; we poll it (SPEC §17.5).
  const doPreview = async () => {
    setBusy("preview");
    setError(null);
    setPreview(null);
    try {
      const { run_id } = await api.post<ScreenPreviewStart>("/screens/preview", { rule: draft.rule });
      const run = await waitForRun(run_id, (r) => setWaiting(runWaitText(r)), () => !alive.current);
      if (!run) return;
      if (run.status !== "done") throw new Error(run.message ?? `The preview was ${run.status}.`);
      const items = await runOkItems(run_id);
      setPreview({
        count: run.ok,
        rows: items.map((i) => ({ symbol: i.key, values: JSON.parse(i.detail ?? "{}") as PreviewValues })),
      });
    } catch (e) {
      setError(msg(e));
    } finally {
      if (alive.current) {
        setBusy(null);
        setWaiting(null);
      }
    }
  };
  const doSave = async () => {
    if (!draft.name.trim()) {
      setError("Give the screen a name first.");
      return;
    }
    setBusy("save");
    setError(null);
    try {
      await onSave({ ...draft, name: draft.name.trim() });
    } catch (e) {
      setError(msg(e));
    } finally {
      setBusy(null);
    }
  };
  const builderRef = useRef<HTMLDivElement>(null);
  const loadAccepted = (a: Accepted, focus: boolean) => {
    setDraft((d) => ({
      name: d.name.trim() ? d.name : a.name,
      description: a.description || d.description,
      rule: a.rule,
    }));
    setPreview(null);
    if (focus) setTimeout(() => builderRef.current?.focus(), 0);
  };
  const columns = preview?.rows[0] ? Object.keys(preview.rows[0].values) : [];
  type PreviewRow = ScreenPreview["rows"][number];
  const previewCols = useMemo<ColumnDef<PreviewRow>[]>(
    () => [
      { id: "symbol", header: "Symbol", accessorFn: (r) => r.symbol },
      ...columns.map<ColumnDef<PreviewRow>>((c) => ({
        id: `v:${c}`,
        header: c,
        meta: { right: true },
        sortUndefined: "last",
        accessorFn: (r) => r.values[c] ?? undefined,
        cell: ({ row }) => <Num value={row.original.values[c]} digits={2} />,
      })),
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [columns.join("|")],
  );

  return (
    <Card className="flex flex-col gap-3">
      <label className="flex items-center gap-2">
        Name <Input className="flex-1" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
      </label>
      <label className="flex items-center gap-2">
        What it looks for{" "}
        <Input
          className="flex-1"
          value={draft.description}
          onChange={(e) => setDraft({ ...draft, description: e.target.value })}
        />
      </label>
      <DescribeScreen onAccept={loadAccepted} />
      {aboveBuilder}
      <div ref={builderRef} tabIndex={-1}>
        <RuleBuilder value={draft.rule} onChange={(rule) => { setDraft({ ...draft, rule }); setPreview(null); }} meta={meta} />
      </div>
      <div className="flex gap-2">
        <Button variant="outline" disabled={busy !== null} onClick={doPreview}>
          {busy === "preview" ? "Checking…" : "Preview"}
        </Button>
        <Button disabled={busy !== null} onClick={doSave}>Save</Button>
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
      </div>
      {busy === "preview" && waiting && (
        <p className="text-muted-foreground" role="status">
          Checking every stock. {waiting}
        </p>
      )}
      {error && <p className="neg" role="alert">{error}</p>}
      {preview && (
        <div>
          <p>
            <strong>{preview.count}</strong> {preview.count === 1 ? "stock matches" : "stocks match"} right now
            {preview.count > PREVIEW_ROWS ? ` (showing the first ${PREVIEW_ROWS})` : ""}.
          </p>
          {preview.rows.length > 0 && (
            <DataTable columns={previewCols} data={preview.rows.slice(0, PREVIEW_ROWS)} getRowId={(r) => r.symbol} />
          )}
        </div>
      )}
    </Card>
  );
}
