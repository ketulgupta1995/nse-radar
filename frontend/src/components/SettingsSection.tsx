import { useState } from "react";
import type { ReactNode } from "react";
import { ApiError } from "../api/client";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { toast } from "@/components/ui/toaster";
import { Button } from "@/components/ui/button";

interface Props {
  title: string;
  onSave: () => Promise<void>;
  children: ReactNode;
}

/** A settings card with its own Save button; shows the server's validation message. */
export default function SettingsSection({ title, onSave, children }: Props) {
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const save = async () => {
    try {
      await onSave();
      setMsg({ ok: true, text: "Saved." });
      toast.success(`${title} saved.`);
    } catch (e) {
      setMsg({ ok: false, text: e instanceof ApiError ? e.message : String(e) });
    }
  };
  return (
    <Card className="settings-section mb-4">
      <CardHeader><CardTitle>{title}</CardTitle></CardHeader>
      {children}
      <div className="mt-3 flex items-center gap-3">
        <Button variant="outline" size="sm" type="button" onClick={() => void save()}>
          Save
        </Button>
        {msg && <span className={msg.ok ? "pos" : "neg"} role="status">{msg.text}</span>}
      </div>
    </Card>
  );
}
