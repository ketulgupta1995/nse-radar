import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ApiError, api } from "../../api/client";
import type { Backtest, BacktestConfig, BatchIn, BatchOut, ExitDefInfo, Screen, Settings } from "../../api/types";
import {
  EXIT_SETS, RANK_CHOICES, configFromBacktest, defaultConfig, nextVersionName, periodError, periodSummary, sameRule,
} from "../../lib/backtests";
import { type Rule, emptyRule } from "../../lib/rules";
import Explain from "../Explain";
import RuleBuilder from "../rules/RuleBuilder";
import BatchOptions from "./BatchOptions";
import ExitEditor from "./ExitEditor";
import { toast } from "@/components/ui/toaster";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";

interface Props {
  onStarted: (id: number) => void;
  onBatchStarted?: (ids: number[]) => void;
  onCancel: () => void;
}

const CUSTOM = "custom";
const FALLBACK_HOLDOUT = "2022-01-01";

export default function BacktestForm({ onStarted, onBatchStarted, onCancel }: Props) {
  const [screens, setScreens] = useState<Screen[]>([]);
  const [defs, setDefs] = useState<ExitDefInfo[]>([]);
  const [entry, setEntry] = useState<string>(CUSTOM);
  const [rule, setRule] = useState<Rule>(emptyRule());
  const [name, setName] = useState("");
  const [cfg, setCfg] = useState(defaultConfig(FALLBACK_HOLDOUT));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  const [params] = useSearchParams();
  const screenParam = params.get("screen");
  const fromParam = params.get("from");

  useEffect(() => {
    const settings = api.get<Settings>("/settings").catch(() => null);
    const from = fromParam ? api.get<Backtest>(`/backtests/${fromParam}`) : Promise.resolve(null);
    Promise.all([api.get<Screen[]>("/screens"), api.get<ExitDefInfo[]>("/backtests/exits"), settings, from])
      .then(([s, d, st, bt]) => {
        const holdout = st?.holdout_start || FALLBACK_HOLDOUT;
        setScreens(s);
        setDefs(d);
        if (bt) {
          setCfg(configFromBacktest(bt, holdout));
          setName(nextVersionName(bt.name, bt.id));
          const match = s.find((x) => sameRule(x.rule, bt.config.entry_rule));
          if (match) setEntry(String(match.id));
          else {
            setEntry(CUSTOM);
            setRule(bt.config.entry_rule);
          }
        } else {
          setCfg(defaultConfig(holdout, st?.capital_inr || undefined));
          const wanted = s.find((x) => String(x.id) === screenParam);
          if (wanted) setEntry(String(wanted.id));
          else if (s.length) setEntry(String(s[0].id));
        }
        setReady(true);
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : String(e)));
  }, [screenParam, fromParam]);

  const patch = (p: Partial<typeof cfg>) => setCfg((c) => ({ ...c, ...p }));
  const entryRule = entry === CUSTOM ? rule : (screens.find((s) => String(s.id) === entry)?.rule ?? rule);
  const periodProblem =periodError(cfg.start, cfg.oos_start ?? "", cfg.end || null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    const config: Omit<BacktestConfig, "entry_rule"> = {
      ...cfg,
      end: cfg.end || null,
      oos_start: cfg.oos_start || null,
    };
    try {
      const made =
        entry === CUSTOM
          ? await api.post<{ id: number }>("/backtests", { name: name || null, config: { ...config, entry_rule: rule } })
          : await api.post<{ id: number }>(`/screens/${entry}/backtest`, { name: name || null, config });
      onStarted(made.id);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
      setBusy(false);
    }
  };

  const submitBatch = async (configs: BacktestConfig[], names: string[]) => {
    setBusy(true);
    setError(null);
    const norm = configs.map((c) => ({ ...c, end: c.end || null, oos_start: c.oos_start || null }));
    try {
      const made = await api.post<BatchOut>("/backtests/batch", { name: null, configs: norm, names } satisfies BatchIn);
      toast.success(
        `Started ${made.ids.length} backtests — they share one setup, so they finish faster than one by one`,
      );
      onBatchStarted?.(made.ids);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
      setBusy(false);
    }
  };

  if (!ready && !error) return <Skeleton className="h-48" />;
  return (
    <form
      className="backtest-form"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <h2>New backtest</h2>
      {error && <p className="neg" role="alert">{error}</p>}
      <label>
        Name (optional) <Input value={name} onChange={(e) => setName(e.target.value)} />
      </label>

      <h3>When to buy</h3>
      <label>
        Entry rule
        <Explain text="The buy signal. Pick a screen you saved, or build a rule here. A stock is bought the morning after its rule turns true." />{" "}
        <Select value={entry} onChange={(e) => setEntry(e.target.value)}>
          {screens.map((s) => (
            <option key={s.id} value={s.id}>{s.name}</option>
          ))}
          <option value={CUSTOM}>Build my own rule…</option>
        </Select>
      </label>
      {entry === CUSTOM && <RuleBuilder value={rule} onChange={setRule} />}

      <h3>When to sell</h3>
      <p>
        Exit set:{" "}
        {EXIT_SETS.map((s) => (
          <Button key={s.label} type="button" variant="ghost"
            onClick={() => patch({ exits: structuredClone(s.exits) })}>
            {s.label}
          </Button>
        ))}
        <Explain text="Swing takes profit at a fixed level. Trend lets winners run and sells when the price falls below its 50-day average; in tests it did better, with bigger swings. Position is slower still (100-day average, held up to 120 days): fewer trades and the best results on the quality screens. Short dip sells as soon as the price closes back above its 5-day average, or after 10 days. Only for the Short dip screen." />
      </p>
      <ExitEditor defs={defs} value={cfg.exits} onChange={(exits) => patch({ exits })} />

      <h3>Settings</h3>
      <label>
        Starting money (₹)
        <Explain text="How much money the test starts with. It is split across your max positions, so with less money each buy is smaller and fixed costs like DP charges eat a bigger share. Filled from your capital in Settings." />{" "}
        <Input type="number" aria-label="Starting money" min={10000} step={10000} value={cfg.initial_capital ?? ""}
          onChange={(e) => patch({ initial_capital: e.target.value === "" ? undefined : Number(e.target.value) })} />
      </label>
      <label>
        Max positions
        <Explain text="Max positions: how many stocks held at once." />{" "}
        <Input type="number" min={1} max={100} value={cfg.max_positions}
          onChange={(e) => patch({ max_positions: Number(e.target.value) })} />
      </label>
      <label>
        How to buy
        <Explain text="Daily: buy whenever the rule fires and a slot is free. Monthly: on the last trading day of each month, hold the best-ranked stocks that pass the rule and sell the ones that fell out. Far fewer trades. Stops still work in between." />{" "}
        <Select
          value={cfg.mode ?? "signals"}
          onChange={(e) =>
            patch(e.target.value === "rotate_monthly"
              ? { mode: "rotate_monthly", hold_buffer: cfg.hold_buffer ?? 1.5 }
              : { mode: "signals" })}
        >
          <option value="signals">When the rule fires (daily)</option>
          <option value="rotate_monthly">Monthly: hold the best N</option>
        </Select>
      </label>
      {cfg.mode === "rotate_monthly" && (
        <label>
          Keep while in the top ×
          <Explain text="A held stock is sold at month end only if it drops out of the top (max positions × this). 1.5 with 20 slots keeps anything still in the top 30, which avoids selling on small rank changes." />{" "}
          <Input type="number" min={1} max={3} step={0.1} value={cfg.hold_buffer ?? 1.5}
            onChange={(e) => patch({ hold_buffer: Number(e.target.value) })} />
        </label>
      )}
      <label>
        Pick first by
        <Explain text="When more stocks signal than you have free slots, which ones are bought first." />{" "}
        <Select
          value={cfg.rank_by?.ind ?? "rel_strength"}
          onChange={(e) => {
            const c = RANK_CHOICES.find((r) => r.rank_by.ind === e.target.value);
            if (c) patch({ rank_by: { ind: c.rank_by.ind, params: { ...c.rank_by.params } } });
          }}
        >
          {RANK_CHOICES.map((r) => (
            <option key={r.rank_by.ind} value={r.rank_by.ind}>{r.label}</option>
          ))}
        </Select>
      </label>
      <label>
        Max per industry
        <Explain text="Stops the test from filling up with one industry. 2018's big drop hit finance stocks together." />{" "}
        <Input type="number" min={1} max={50} placeholder="No cap" value={cfg.max_per_industry ?? ""}
          onChange={(e) => patch({ max_per_industry: e.target.value === "" ? null : Number(e.target.value) })} />
      </label>
      <label>
        Fewer slots in weak markets
        <Explain text="When fewer than this % of stocks are above their 200-day average, only open this % of your slots. Softer than stopping entirely." />{" "}
        <input type="checkbox" aria-label="Use fewer slots in weak markets" checked={cfg.regime_scale != null}
          onChange={(e) =>
            patch({ regime_scale: e.target.checked ? { breadth_below: 50, slots_pct: 50 } : null })} />
      </label>
      {cfg.regime_scale && (
        <>
          <label>
            Breadth below (%)
            <Input type="number" min={10} max={90} value={cfg.regime_scale.breadth_below}
              onChange={(e) =>
                patch({ regime_scale: { ...cfg.regime_scale!, breadth_below: Number(e.target.value) } })} />
          </label>
          <label>
            Slots to use (%)
            <Input type="number" min={0} max={100} value={cfg.regime_scale.slots_pct}
              onChange={(e) =>
                patch({ regime_scale: { ...cfg.regime_scale!, slots_pct: Number(e.target.value) } })} />
          </label>
        </>
      )}
      <label>
        Position size
        <Explain text="Equal: split money evenly across the max positions. Risk: size each buy so that hitting the stop loses only the risk % below (never more than an equal share). Needs a stop-loss exit." />{" "}
        <Select value={cfg.sizing} onChange={(e) => patch({ sizing: e.target.value as "equal" | "risk" })}>
          <option value="equal">Equal amounts</option>
          <option value="risk">Risk-based</option>
        </Select>
      </label>
      {cfg.sizing === "risk" && (
        <label>
          Risk per trade (%)
          <Explain text="How much of your account you accept losing if the stop-loss is hit. At 1% with 20 slots this rarely changes anything; 0.5% shrinks the volatile stocks and cut the worst drawdown in tests." />{" "}
          <Input type="number" min={0.1} max={10} step={0.1} value={cfg.risk_pct}
            onChange={(e) => patch({ risk_pct: Number(e.target.value) })} />
        </label>
      )}
      <label>
        Stocks tested
        <Explain text="Which stocks the test may buy. 'Most-traded 500 at the time' uses the 500 busiest stocks each month, including ones that later fell out of the index or were delisted, so it is closer to what you could really have done. 'Today's Nifty 500' only contains companies that survived, which flatters the results." />{" "}
        <Select value={cfg.universe ?? "liquid500"}
          onChange={(e) => patch({ universe: e.target.value as "current" | "liquid500" })}>
          <option value="liquid500">Most-traded 500 at the time (fairer)</option>
          <option value="current">Today's Nifty 500 (flatters results)</option>
        </Select>
      </label>
      <h3>
        Period
        <Explain text="The app tests your rule only on the training years. The test years stay hidden so you can't tune the rule to them by accident. When you're happy, run the final test once to see how it does on years it never saw." />
      </h3>
      <label>
        Train from
        <Input type="date" value={cfg.start} onChange={(e) => patch({ start: e.target.value })} />
      </label>
      <label>
        Test from
        <Input type="date" value={cfg.oos_start ?? ""} onChange={(e) => patch({ oos_start: e.target.value })} />
      </label>
      <label>
        Test until (optional)
        <Input type="date" value={cfg.end ?? ""} onChange={(e) => patch({ end: e.target.value })} />
      </label>
      {periodProblem ? (
        <p className="neg" role="alert">{periodProblem}</p>
      ) : (
        <p className="text-muted-foreground">{periodSummary(cfg.start, cfg.oos_start ?? "", cfg.end || null)}</p>
      )}

      <BatchOptions
        cfg={cfg}
        entryRule={entryRule}
        defs={defs}
        screens={screens}
        name={name}
        busy={busy || periodProblem !== null}
        onRun={(configs, names) => void submitBatch(configs, names)}
      />

      <p>
        <Button type="submit" disabled={busy || periodProblem !== null}>Run on training period</Button>{" "}
        <Button type="button" variant="ghost" onClick={onCancel}>Cancel</Button>
      </p>
    </form>
  );
}
