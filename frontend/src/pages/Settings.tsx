import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { AiStatus, CostModel, CustomIndicator, Feed, Settings as S } from "../api/types";
import Explain from "../components/Explain";
import CustomIndicatorReview from "../components/screens/CustomIndicatorReview";
import SettingsSection from "../components/SettingsSection";
import { useTheme } from "../lib/theme";
import type { ThemeChoice } from "../lib/theme";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";

const WEIGHTS: [string, string, string][] = [
  ["rs", "Relative strength", "How much the stock has outperformed the market lately. Higher weight favours recent leaders."],
  ["trend", "Trend", "Whether the price is in a healthy uptrend (above its long-term averages)."],
  ["fundamentals", "Company health", "Growth and profitability from the company's results."],
  ["backtest", "Past performance", "How well this kind of setup worked historically in the app's backtests."],
];

const COSTS: [keyof CostModel, string, string][] = [
  ["brokerage_pct", "Brokerage %", "Broker fee as a % of trade value."],
  ["brokerage_cap_inr", "Brokerage cap (₹)", "Most brokers cap the fee per order at this amount."],
  ["stt_pct", "STT %", "Securities Transaction Tax, charged by the government on delivery trades."],
  ["exchange_pct", "Exchange charges %", "Fee charged by the stock exchange."],
  ["sebi_pct", "SEBI charges %", "Small regulator fee."],
  ["stamp_buy_pct", "Stamp duty % (buy)", "Charged on the buy side only."],
  ["gst_pct", "GST %", "Tax on brokerage and exchange fees."],
  ["dp_charge_inr", "Demat charge (₹)", "Flat fee your broker takes each time you sell shares."],
  ["slippage_pct", "Slippage %", "Allowance for getting a slightly worse price than the one you saw."],
];

function Field({ label, help, children }: { label: string; help?: string; children: ReactNode }) {
  return (
    <label className="field">
      <span>
        {label}
        {help && <Explain text={help} />}
      </span>
      {children}
    </label>
  );
}

const num = (v: string) => (v === "" ? NaN : Number(v));

export default function Settings() {
  const [s, setS] = useState<S | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ai, setAi] = useState<AiStatus | null | "missing">(null);
  const [backup, setBackup] = useState<string | null>(null);
  const { theme, setTheme } = useTheme();
  const [indicators, setIndicators] = useState<CustomIndicator[]>([]);
  const [reviewing, setReviewing] = useState<CustomIndicator | null>(null);
  const [indError, setIndError] = useState<string | null>(null);

  const loadIndicators = useCallback(() => {
    api
      .get<CustomIndicator[]>("/custom-indicators")
      .then(setIndicators)
      .catch(() => setIndicators([]));
  }, []);
  const removeIndicator = (c: CustomIndicator) => {
    setIndError(null);
    api
      .del(`/custom-indicators/${c.id}`)
      .then(loadIndicators)
      .catch((e) => setIndError(e instanceof ApiError ? e.message : String(e)));
  };

  const load = useCallback(async () => {
    try {
      setS(await api.get<S>("/settings"));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }, []);
  useEffect(() => {
    void load();
    loadIndicators();
    api
      .get<AiStatus>("/ai/status")
      .then(setAi)
      .catch(() => setAi("missing"));
  }, [load, loadIndicators]);

  if (error) return <p className="neg">{error}</p>;
  if (!s) return <p className="muted">Loading…</p>;
  const set = <K extends keyof S>(k: K, v: S[K]) => setS({ ...s, [k]: v });
  const save = (keys: (keyof S)[]) => async () => {
    const body: Record<string, unknown> = {};
    keys.forEach((k) => (body[k] = s[k]));
    setS(await api.put<S>("/settings", body));
  };
  const total = Object.values(s.score_weights).reduce((a, b) => a + b, 0);
  const providers = ai && ai !== "missing" ? ai.providers : [];

  return (
    <div className="settings">
      <h1>Settings</h1>
      <p className="muted">
        Data sources and their priority are on the <Link to="/sources">Sources page</Link>.
      </p>

      <SettingsSection title="Money & risk" onSave={save(["capital_inr", "risk_per_trade_pct", "atr_stop_multiple", "signal_target_atr_multiple", "position_exit_sma", "trail_atr_multiple", "default_time_stop_weeks"])}>
        <Field label="Capital (₹)" help="The money you plan to invest. Position sizes are worked out from this.">
          <Input type="number" value={s.capital_inr} onChange={(e) => set("capital_inr", num(e.target.value))} />
        </Field>
        <Field label="Risk per trade (%)" help="If the stop-loss is hit, you lose at most this % of your capital on one trade. 1% is a common choice.">
          <Input type="number" step="0.1" value={s.risk_per_trade_pct} onChange={(e) => set("risk_per_trade_pct", num(e.target.value))} />
        </Field>
        <Field label="ATR stop multiple" help="ATR is how much the stock typically moves in a day. A stop 2× ATR below entry gives normal wiggles room.">
          <Input type="number" step="0.5" value={s.atr_stop_multiple} onChange={(e) => set("atr_stop_multiple", num(e.target.value))} />
        </Field>
        <Field label="Forward-test target (ATRs above entry)" help="Used only to grade logged ideas on the Track record page.">
          <Input type="number" step="0.5" min={0.5} max={20} value={s.signal_target_atr_multiple} onChange={(e) => set("signal_target_atr_multiple", num(e.target.value))} />
        </Field>
        <Field label="Trend-exit average (days)" help="Warn when an open position closes below this many days' average. 100 matched the best exit in tests. 0 turns it off.">
          <Input type="number" step="10" min={0} max={300} value={s.position_exit_sma} onChange={(e) => set("position_exit_sma", num(e.target.value))} />
        </Field>
        <Field label="Trailing stop (ATRs)" help="Warn when the price falls this many ATRs (typical daily moves) under its highest close since you bought. 5 matched tests; 3 whipsawed. 0 turns it off.">
          <Input type="number" step="0.5" min={0} max={15} value={s.trail_atr_multiple} onChange={(e) => set("trail_atr_multiple", num(e.target.value))} />
        </Field>
        <Field label="Default time stop (weeks)" help="If the idea hasn't worked after this many weeks, exit and free the money.">
          <Input type="number" value={s.default_time_stop_weeks} onChange={(e) => set("default_time_stop_weeks", num(e.target.value))} />
        </Field>
      </SettingsSection>

      <SettingsSection title="Ranking weights" onSave={save(["score_weights"])}>
        <p className="muted">How much each factor counts when the shortlist is ranked. Only the proportions matter.</p>
        {WEIGHTS.map(([key, label, help]) => {
          const w = s.score_weights[key] ?? 0;
          return (
            <Field key={key} label={label} help={help}>
              <span className="slider">
                <input
                  type="range" min={0} max={100} value={w}
                  aria-label={label}
                  onChange={(e) => set("score_weights", { ...s.score_weights, [key]: Number(e.target.value) })}
                />
                <span className="num">{total ? Math.round((w / total) * 100) : 0}%</span>
              </span>
            </Field>
          );
        })}
      </SettingsSection>

      <SettingsSection title="News feeds" onSave={save(["rss_feeds"])}>
        {s.rss_feeds.map((f: Feed, i) => (
          <div className="feed-row" key={i}>
            <Input placeholder="Name" value={f.name} onChange={(e) => set("rss_feeds", s.rss_feeds.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} />
            <Input placeholder="https://…" value={f.url} onChange={(e) => set("rss_feeds", s.rss_feeds.map((x, j) => (j === i ? { ...x, url: e.target.value } : x)))} />
            <Button variant="outline" size="sm" type="button" onClick={() => set("rss_feeds", s.rss_feeds.filter((_, j) => j !== i))}>Remove</Button>
          </div>
        ))}
        <Button variant="outline" size="sm" type="button" onClick={() => set("rss_feeds", [...s.rss_feeds, { name: "", url: "" }])}>Add feed</Button>
      </SettingsSection>

      <SettingsSection title="AI" onSave={save(["ai_provider", "ai_model", "ai_timeout_s"])}>
        {ai === "missing" && <p className="muted">AI is not set up yet.</p>}
        {ai && ai !== "missing" && (
          <p className={ai.available ? "pos" : "neg"}>{ai.available ? "Available" : "Not available"}: {ai.detail}</p>
        )}
        <Field label="Provider" help="Which tool answers AI requests. The default uses your Claude Pro plan through the local claude command.">
          {providers.length ? (
            <Select value={s.ai_provider} onChange={(e) => set("ai_provider", e.target.value)}>
              {providers.map((p) => <option key={p.name} value={p.name}>{p.label}</option>)}
            </Select>
          ) : (
            <Input value={s.ai_provider} onChange={(e) => set("ai_provider", e.target.value)} />
          )}
        </Field>
        <Field label="Model" help="Model name passed to the provider, e.g. sonnet or opus.">
          <Input value={s.ai_model} onChange={(e) => set("ai_model", e.target.value)} />
        </Field>
        <Field label="Timeout (seconds)" help="How long to wait for an answer before giving up.">
          <Input type="number" value={s.ai_timeout_s} onChange={(e) => set("ai_timeout_s", num(e.target.value))} />
        </Field>
      </SettingsSection>

      <SettingsSection title="Costs" onSave={save(["cost_model"])}>
        <p className="muted">Used by backtests so results include realistic trading costs on Indian delivery trades.</p>
        {COSTS.map(([key, label, help]) => (
          <Field key={key} label={label} help={help}>
            <Input type="number" step="any" value={s.cost_model[key]} onChange={(e) => set("cost_model", { ...s.cost_model, [key]: num(e.target.value) })} />
          </Field>
        ))}
      </SettingsSection>

      <SettingsSection title="Backtest periods" onSave={save(["holdout_start"])}>
        <Field label="Test period starts" help="Backtests are tuned on the years before this date. The years from here on stay hidden until you run the final test, so you can't fit your rule to them by accident. New backtests use this as their default.">
          <Input type="date" value={s.holdout_start ?? ""} onChange={(e) => set("holdout_start", e.target.value)} />
        </Field>
      </SettingsSection>

      <section className="card settings-section">
        <h2>
          Custom indicators{" "}
          <Explain text="Indicators Claude wrote for you. Each one only runs after you have read its code and approved it." />
        </h2>
        {indicators.length === 0 && <p className="muted">None yet. Ask Claude for a screen that needs one.</p>}
        <ul>
          {indicators.map((c) => (
            <li key={c.id}>
              <strong>{c.name}</strong> ({c.status}): {c.explain}{" "}
              <Button variant="outline" size="sm" type="button" onClick={() => setReviewing(c)}>
                {c.status === "pending" ? "Review code" : "View code"}
              </Button>{" "}
              <Button variant="outline" size="sm" type="button" onClick={() => removeIndicator(c)}>Delete</Button>
            </li>
          ))}
        </ul>
        {indError && <p className="neg" role="alert">{indError}</p>}
      </section>
      {reviewing && (
        <CustomIndicatorReview
          indicator={reviewing}
          onClose={() => {
            setReviewing(null);
            loadIndicators();
          }}
          onApproved={loadIndicators}
          onRejected={loadIndicators}
        />
      )}

      <section className="card settings-section">
        <h2>Appearance</h2>
        <Field label="Theme">
          <Select value={theme} onChange={(e) => setTheme(e.target.value as ThemeChoice)}>
            <option value="system">Follow system</option>
            <option value="light">Light</option>
            <option value="dark">Dark</option>
          </Select>
        </Field>
      </section>

      <section className="card settings-section">
        <h2>Backup</h2>
        <p className="muted">Saves a copy of the whole database into the data/backups folder.</p>
        <Button variant="outline" size="sm"
          type="button"
          onClick={() =>
            api
              .post<{ path: string; size_bytes: number }>("/backup")
              .then((r) => setBackup(`Saved to ${r.path}`))
              .catch((e) => setBackup(e instanceof ApiError ? e.message : String(e)))
          }
        >
          Back up now
        </Button>
        {backup && <p role="status">{backup}</p>}
      </section>
    </div>
  );
}
