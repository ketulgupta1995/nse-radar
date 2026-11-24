import { useMemo, useState } from "react";
import type { BacktestConfig, ExitDefInfo, Screen } from "../../api/types";
import {
  type FormConfig, buildScreenBatch, buildVariations, exitSetLabel, parseValues, varyOptions,
} from "../../lib/backtests";
import Explain from "../Explain";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";

interface Props {
  cfg: FormConfig;
  entryRule: BacktestConfig["entry_rule"];
  defs: ExitDefInfo[];
  screens: Screen[];
  name: string;
  busy: boolean;
  onRun: (configs: BacktestConfig[], names: string[]) => void;
}

const MIN_SCREENS = 2;
const MAX_SCREENS = 20;

type Mode = "values" | "screens";

export default function BatchOptions({ cfg, entryRule, defs, screens, name, busy, onRun }: Props) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<Mode>("values");
  const [vary, setVary] = useState("max_positions");
  const [text, setText] = useState("");
  const [ticked, setTicked] = useState<number[]>([]);

  const options = useMemo(() => varyOptions(cfg, defs), [cfg, defs]);
  const option = options.find((o) => o.key === vary) ?? options[0];
  const parsed = parseValues(text, option);
  const showError = text.trim() !== "" && parsed.error !== null;

  const plan = useMemo(() => {
    if (mode === "values") {
      if (parsed.values === null) return null;
      return buildVariations({ ...cfg, entry_rule: entryRule }, option, parsed.values, name);
    }
    const chosen = screens.filter((s) => ticked.includes(s.id));
    if (chosen.length < MIN_SCREENS || chosen.length > MAX_SCREENS) return null;
    return buildScreenBatch(cfg, chosen, exitSetLabel(cfg.exits));
  }, [mode, parsed.values, cfg, entryRule, option, name, screens, ticked]);

  const toggle = (id: number) =>
    setTicked((t) => (t.includes(id) ? t.filter((x) => x !== id) : [...t, id]));

  return (
    <div className="my-3">
      <Button type="button" variant="ghost" aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? "▾" : "▸"} Run several at once
      </Button>
      {open && (
        <div className="mt-2 space-y-3 rounded-control border border-border p-3">
          <p>
            <label>
              <input type="radio" name="batch-mode" checked={mode === "values"} onChange={() => setMode("values")} />{" "}
              Try several values
            </label>{" "}
            <label>
              <input type="radio" name="batch-mode" checked={mode === "screens"} onChange={() => setMode("screens")} />{" "}
              Compare screens
            </label>
          </p>
          {mode === "values" ? (
            <>
              <p>
                <Explain text="Runs the same backtest once per value, changing only this setting, so you can see which value works best on the training period. Every run counts towards your training-run total." />
              </p>
              <label>
                Setting to vary{" "}
                <Select value={option.key} onChange={(e) => setVary(e.target.value)}>
                  {options.map((o) => (
                    <option key={o.key} value={o.key}>{o.label}</option>
                  ))}
                </Select>
              </label>
              <label className="block">
                Values, separated by commas{" "}
                <Input value={text} placeholder="5, 8, 10" onChange={(e) => setText(e.target.value)} />
              </label>
              {showError && <p className="text-danger" role="alert">{parsed.error}</p>}
            </>
          ) : (
            <>
              <p>
                <Explain text="Runs every ticked screen with the same exits and settings." />
              </p>
              <p className="text-muted-foreground">
                The "Entry rule" choice above is ignored here: each ticked screen supplies its own rule.
              </p>
              {screens.map((s) => (
                <label key={s.id} className="block">
                  <input type="checkbox" checked={ticked.includes(s.id)} onChange={() => toggle(s.id)} /> {s.name}
                </label>
              ))}
              <p className="text-muted-foreground">Tick {MIN_SCREENS} to {MAX_SCREENS} screens.</p>
            </>
          )}
          <Button type="button" disabled={busy || plan === null} onClick={() => plan && onRun(plan.configs, plan.names)}>
            Run {plan ? plan.configs.length : 0} backtests on training period
          </Button>
        </div>
      )}
    </div>
  );
}
