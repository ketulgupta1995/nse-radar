import { useState } from "react";
import type { Schedule, ScheduleKind, SchedulePatch } from "../../api/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

export function scheduleWords(s: Schedule): string {
  switch (s.kind) {
    case "interval": {
      const m = s.interval_min ?? 0;
      return m % 60 === 0 && m >= 60 ? `Every ${m / 60} h` : `Every ${m} min`;
    }
    case "daily":
      return `${s.weekdays_only ? "Weekdays" : "Every day"} at ${s.at_time}`;
    case "weekly":
      return `${DAYS[s.weekday ?? 0]}s ${s.at_time}`;
    default:
      return "Manual";
  }
}

interface Props {
  schedule: Schedule;
  onSave: (patch: SchedulePatch) => void;
  onCancel: () => void;
}

export default function ScheduleEditor({ schedule, onSave, onCancel }: Props) {
  const [kind, setKind] = useState<ScheduleKind>(schedule.kind);
  const [intervalMin, setIntervalMin] = useState(schedule.interval_min ?? 60);
  const [atTime, setAtTime] = useState(schedule.at_time ?? "19:30");
  const [weekday, setWeekday] = useState(schedule.weekday ?? 0);
  const [weekdaysOnly, setWeekdaysOnly] = useState(Boolean(schedule.weekdays_only));

  function save() {
    if (kind === "interval") onSave({ kind, interval_min: intervalMin });
    else if (kind === "daily") onSave({ kind, at_time: atTime, weekdays_only: weekdaysOnly });
    else if (kind === "weekly") onSave({ kind, weekday, at_time: atTime });
    else onSave({ kind });
  }

  return (
    <div className="sched-editor">
      <label>
        How often{" "}
        <Select aria-label="Kind" value={kind} onChange={(e) => setKind(e.target.value as ScheduleKind)}>
          <option value="interval">Every N minutes</option>
          <option value="daily">Daily</option>
          <option value="weekly">Weekly</option>
          <option value="manual">Manual only</option>
        </Select>
      </label>
      {kind === "interval" && (
        <label>
          Minutes between runs{" "}
          <Input
            aria-label="Minutes"
            type="number"
            min={1}
            value={intervalMin}
            onChange={(e) => setIntervalMin(Number(e.target.value))}
          />
        </label>
      )}
      {kind === "weekly" && (
        <label>
          Day{" "}
          <Select aria-label="Weekday" value={weekday} onChange={(e) => setWeekday(Number(e.target.value))}>
            {DAYS.map((d, i) => (
              <option key={d} value={i}>
                {d}
              </option>
            ))}
          </Select>
        </label>
      )}
      {(kind === "daily" || kind === "weekly") && (
        <label>
          At (24-hour){" "}
          <Input aria-label="Time" type="time" value={atTime} onChange={(e) => setAtTime(e.target.value)} />
        </label>
      )}
      {kind === "daily" && (
        <label>
          <input
            aria-label="Weekdays only"
            type="checkbox"
            checked={weekdaysOnly}
            onChange={(e) => setWeekdaysOnly(e.target.checked)}
          />{" "}
          Weekdays only (skip Sat and Sun)
        </label>
      )}
      <div className="sched-actions">
        <Button variant="outline" size="sm" type="button" onClick={save}>
          Save
        </Button>
        <Button variant="outline" size="sm" type="button" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
