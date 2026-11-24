import type { Screen } from "../../api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { todayIso } from "../../lib/dates";

export function ranText(asOf: string | null, today: string = todayIso()): string {
  if (!asOf) return "not run yet";
  const days = Math.round((Date.parse(today) - Date.parse(asOf)) / 864e5);
  if (days <= 0) return "ran today";
  if (days === 1) return "ran yesterday";
  return `ran ${days} days ago`;
}

interface Props {
  screens: Screen[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  onNew: () => void;
  onDuplicate: (s: Screen) => void;
}

export default function ScreenList({ screens, selectedId, onSelect, onNew, onDuplicate }: Props) {
  return (
    <nav className="flex flex-col gap-3" aria-label="Screens">
      <Button onClick={onNew}>+ New screen</Button>
      <ul className="m-0 flex list-none flex-col gap-2 p-0">
        {screens.map((s) => (
          <li
            key={s.id}
            className={cn(
              "rounded-card border bg-card p-2",
              s.id === selectedId ? "border-accent" : "border-border",
            )}
          >
            <button
              type="button"
              aria-pressed={s.id === selectedId}
              onClick={() => onSelect(s.id)}
              className="block w-full cursor-pointer border-0 bg-transparent p-0 text-left text-inherit"
              style={{ font: "inherit" }}
            >
              <strong>{s.name}</strong>
              {s.is_preset && <Badge className="ml-1">preset</Badge>}
              <br />
              <span className="muted">
                {s.count} {s.count === 1 ? "match" : "matches"} · {ranText(s.last_run_as_of)}
              </span>
            </button>
            {s.is_preset && (
              <Button variant="link" size="sm" className="mt-1" aria-label={`Duplicate ${s.name}`} onClick={() => onDuplicate(s)}>
                Duplicate
              </Button>
            )}
          </li>
        ))}
      </ul>
    </nav>
  );
}
