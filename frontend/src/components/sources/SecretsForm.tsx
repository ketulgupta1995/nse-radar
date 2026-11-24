import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface Props {
  secrets: Record<string, boolean>;
  onSave: (values: Record<string, string | null>) => void;
}

/** Password inputs for a source's keys. Stored values are never shown, only "set / not set". */
export default function SecretsForm({ secrets, onSave }: Props) {
  const [values, setValues] = useState<Record<string, string>>({});
  const keys = Object.keys(secrets);
  if (keys.length === 0) return null;

  function save() {
    const out: Record<string, string | null> = {};
    for (const k of keys) if (values[k]?.trim()) out[k] = values[k];
    if (Object.keys(out).length === 0) return;
    onSave(out);
    setValues({});
  }

  return (
    <div className="secrets">
      <strong>Keys</strong>
      {keys.map((k) => (
        <div key={k}>
          <label>
            {k}{" "}
            <Input
              type="password"
              autoComplete="off"
              value={values[k] ?? ""}
              placeholder={secrets[k] ? "set (type to replace)" : "paste key"}
              onChange={(e) => setValues({ ...values, [k]: e.target.value })}
            />
          </label>{" "}
          <span className={secrets[k] ? "pos" : "muted"}>{secrets[k] ? "set" : "not set"}</span>
          {secrets[k] && (
            <>
              {" "}
              <button type="button" className="link" onClick={() => onSave({ [k]: null })}>
                remove
              </button>
            </>
          )}
        </div>
      ))}
      <Button variant="outline" size="sm" type="button" onClick={save}>
        Save keys
      </Button>
    </div>
  );
}
