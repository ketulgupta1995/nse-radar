import { Copy, ExternalLink } from "lucide-react";
import { useState } from "react";
import { ApiError, api } from "../../api/client";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { toast } from "@/components/ui/toaster";

export const CLAUDE_URL = "https://claude.ai/new";

interface Props<T> {
  /** The AI request waiting for its answer. */
  requestId: number;
  prompt: string;
  /** Called with the request after the answer is saved (status "done" or "failed"). */
  onSaved: (req: T) => void;
  onClose: () => void;
}

const msg = (e: unknown) => (e instanceof ApiError ? e.message : String(e));

/** SPEC §17.7: copy the prompt into Claude, paste the answer back. */
export default function PasteAnswerDialog<T>({ requestId, prompt, onSaved, onClose }: Props<T>) {
  const [answer, setAnswer] = useState("");
  const [copied, setCopied] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(prompt);
      setCopied(true);
    } catch (e) {
      setError(`Could not copy. Select the text and copy it by hand. (${msg(e)})`);
    }
  };

  const save = async () => {
    setError(null);
    setSaving(true);
    try {
      const r = await api.post<T>(`/ai/requests/${requestId}/answer`, { text: answer });
      toast.success("Claude's answer saved");
      onSaved(r);
    } catch (e) {
      setError(msg(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="top-[6%] flex max-h-[88vh] flex-col gap-3 overflow-y-auto p-4">
        <DialogTitle className="text-base font-semibold">Ask Claude yourself</DialogTitle>
        <DialogDescription className="text-sm text-muted-foreground">
          1. Copy the prompt. 2. Open Claude and paste it. 3. Copy Claude's whole answer and paste it below.
        </DialogDescription>
        <label className="flex flex-col gap-1 text-sm">
          The prompt
          <textarea
            readOnly
            rows={6}
            value={prompt}
            aria-label="The prompt"
            className="rounded-control border border-border bg-muted p-2 font-mono text-xs"
          />
        </label>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => void copy()}>
            <Copy size={14} aria-hidden="true" /> Copy
          </Button>
          <Button variant="outline" size="sm" asChild>
            <a href={CLAUDE_URL} target="_blank" rel="noopener noreferrer">
              <ExternalLink size={14} aria-hidden="true" /> Open Claude
            </a>
          </Button>
          {copied && <span className="text-sm text-muted-foreground" role="status">Copied</span>}
        </div>
        <label className="flex flex-col gap-1 text-sm">
          Paste Claude's answer
          <textarea
            rows={8}
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            aria-label="Paste Claude's answer"
            className="rounded-control border border-border bg-card p-2 text-sm"
          />
        </label>
        {error && <p className="text-sm text-danger" role="alert">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
          <Button size="sm" disabled={saving || !answer.trim()} onClick={() => void save()}>
            {saving ? "Saving…" : "Save"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
