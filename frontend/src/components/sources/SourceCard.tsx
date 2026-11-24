import { Link } from "react-router-dom";
import type { SourceInfo } from "../../api/types";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import SecretsForm from "./SecretsForm";
import { Button } from "@/components/ui/button";

interface Props {
  source: SourceInfo;
  onToggle: (enabled: boolean) => void;
  onSecrets: (values: Record<string, string | null>) => void;
}

function chipText(c: SourceInfo["capabilities"][number]): string {
  if (c.capability !== "bars") return c.capability;
  return `bars (${c.adjusted ? "already adjusted" : "raw + we adjust"})`;
}

export default function SourceCard({ source: s, onToggle, onSecrets }: Props) {
  const paused = !s.enabled && !!s.paused_reason;
  return (
    <Card className={cn("flex flex-col gap-1", !s.enabled && "opacity-75")}>
      <header className="flex items-center justify-between gap-2">
        <h3>
          {s.label}{" "}
          <a href={s.homepage} target="_blank" rel="noreferrer">
            website ↗
          </a>
        </h3>
        <label>
          <input type="checkbox" checked={s.enabled} onChange={(e) => onToggle(e.target.checked)} /> Enabled
        </label>
      </header>
      <p>{s.description}</p>
      {paused && (
        <p className="text-warning">
          Paused: {s.paused_reason}{" "}
          <Button variant="outline" size="sm" type="button" onClick={() => onToggle(true)}>
            Re-enable
          </Button>
        </p>
      )}
      <p>
        {s.capabilities.map((c) => (
          <Badge key={c.capability} variant="info" className="mr-1">
            {chipText(c)}
          </Badge>
        ))}
      </p>
      <p>
        Jobs:{" "}
        {s.capabilities
          .flatMap((c) => c.jobs)
          .map((j) => (
            <span key={j}>
              <Link to={`/jobs?job=${encodeURIComponent(j)}`}>{j}</Link>{" "}
            </span>
          ))}
      </p>
      <p className="muted">
        Last 7 days: {s.stats.ok_7d} ok · {s.stats.failed_7d} failed · {s.stats.not_found_7d} not found
        {s.last_ok_at && <> · last success {s.last_ok_at.slice(0, 16).replace("T", " ")}</>}
      </p>
      {s.last_error && (
        <details>
          <summary>Last error{s.last_error_at ? ` (${s.last_error_at.slice(0, 16).replace("T", " ")})` : ""}</summary>
          <pre className="log">{s.last_error}</pre>
        </details>
      )}
      <SecretsForm secrets={s.secrets} onSave={onSecrets} />
    </Card>
  );
}
