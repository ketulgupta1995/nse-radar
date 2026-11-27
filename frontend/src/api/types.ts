export interface CustomIndicatorParam {
  name: string;
  kind: "int" | "float";
  default: number;
  min?: number;
  max?: number;
  label: string;
}

export interface CustomIndicator {
  id: number;
  name: string;
  params_schema: CustomIndicatorParam[];
  explain: string;
  code: string;
  status: "pending" | "approved" | "rejected";
  created_at: string;
  approved_at: string | null;
  /** Static-check problems; empty when the code passes. */
  problems: string[];
  /** The `indicator_approve` job, only present on the approve response (the trial runs there). */
  run_id?: number;
}

/** Where the backend runs (SPEC §17.2). */
export type Runtime = "local" | "vercel" | "actions";

export interface Health {
  ok: boolean;
  time: string;
  version: string;
  runtime?: Runtime;
  schema?: "ok" | "update pending";
}

export type ScheduleKind = "interval" | "daily" | "weekly" | "manual";

export interface Schedule {
  kind: ScheduleKind;
  interval_min: number | null;
  at_time: string | null;
  weekday: number | null;
  weekdays_only: number | boolean;
  enabled: boolean;
  next_run_at: string | null;
}

export type SchedulePatch = Partial<Omit<Schedule, "next_run_at">>;

export type RunStatus = "queued" | "running" | "done" | "failed" | "cancelled" | "interrupted";

export interface RunSummary {
  id: number;
  job: string;
  trigger: string;
  status: RunStatus;
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_s: number | null;
  total: number | null;
  done: number;
  ok: number;
  skipped: number;
  failed: number;
  message: string | null;
  retry_of: number | null;
}

export interface RunDetail extends RunSummary {
  items_failed: { key: string; detail: string | null }[];
}

export interface RunItem {
  key: string;
  status: "ok" | "skipped" | "failed";
  detail: string | null;
  at: string;
}

export interface LogLine {
  id: number;
  at: string;
  level: "info" | "warn" | "error";
  msg: string;
}

export interface JobInfo {
  name: string;
  title: string;
  description: string;
  group: string;
  source_enabled: boolean | null;
  schedule: Schedule;
  last_run: RunSummary | null;
  running: RunSummary | null;
}

export interface JobsResponse {
  paused: boolean;
  jobs: JobInfo[];
}

export interface SourceCapability {
  capability: string;
  mode: "by_symbol" | "by_date" | "whole";
  adjusted: boolean | null;
  jobs: string[];
}

export interface SourceInfo {
  name: string;
  label: string;
  description: string;
  homepage: string;
  enabled: boolean;
  paused_reason: string | null;
  last_ok_at: string | null;
  last_error_at: string | null;
  last_error: string | null;
  capabilities: SourceCapability[];
  secrets: Record<string, boolean>;
  stats: { ok_7d: number; failed_7d: number; not_found_7d: number };
}

/** source_priority setting (capability -> ordered names) plus every source that has each capability. */
export type Priority = { [capability: string]: string[] } & { capabilities?: never };
export interface PriorityResponse {
  [capability: string]: string[] | Record<string, string[]>;
  capabilities: Record<string, string[]>;
}

export interface Coverage {
  source: string;
  symbols: number;
  first_date: string | null;
  last_date: string | null;
  rows: number;
}

export interface DataHealth {
  last_trading_date: string | null;
  symbols: number;
  universe: number;
  checks_open: number;
  unparsed_actions: number;
  bars: Record<string, { symbols: number; last_date: string | null }>;
  fundamentals: Record<string, number>;
  quarters: Record<string, number>;
  news: { announcements_7d: number; news_7d: number };
}

export interface PriceCheck {
  id: number;
  symbol: string;
  date: string;
  kind: "mismatch" | "unexplained_gap" | "adjustment_jump";
  primary_source: string | null;
  other_source: string | null;
  detail: {
    suggested_factor?: number | null;
    ratio?: number;
    ex_date?: string | null;
    change_pct?: number;
    applied_factor?: number;
    open_move_pct?: number;
    close_move_pct?: number;
  };
  status: "open" | "ignored" | "fixed";
}

export interface UnparsedAction {
  source: string;
  symbol: string;
  ex_date: string;
  subject: string;
}

/** Next quarterly-results board meeting (T095). */
export interface NextResults {
  date: string;
  days: number;
}

export interface SymbolInfo {
  symbol: string;
  name: string | null;
  industry: string | null;
  in_universe: boolean;
  last_date?: string | null;
  last_close?: number | null;
  change_pct?: number | null;
  bars_source?: string | null;
  series?: string | null;
  trade_for_trade?: boolean;
  in_watchlist?: boolean;
  open_position_id?: number | null;
  next_results?: NextResults | null;
}

export interface WatchItem {
  symbol: string;
  name: string | null;
  added_at: string;
  note: string | null;
  last_close: number | null;
  /** Close on the day it was added (last trading day on or before it). */
  added_close: number | null;
}

export interface Feed {
  name: string;
  url: string;
}

export interface CostModel {
  brokerage_pct: number;
  brokerage_cap_inr: number;
  stt_pct: number;
  exchange_pct: number;
  sebi_pct: number;
  stamp_buy_pct: number;
  gst_pct: number;
  dp_charge_inr: number;
  slippage_pct: number;
}

export interface Settings {
  capital_inr: number;
  risk_per_trade_pct: number;
  default_time_stop_weeks: number;
  atr_stop_multiple: number;
  signal_target_atr_multiple: number;
  position_exit_sma: number;
  trail_atr_multiple: number;
  source_priority: Record<string, string[]>;
  fundamentals_field_priority: Record<string, string[]>;
  ai_provider: string;
  ai_model: string;
  ai_timeout_s: number;
  score_weights: Record<string, number>;
  rss_feeds: Feed[];
  jobs_paused: boolean;
  last_visit_at: string | null;
  holdout_start: string;
  cost_model: CostModel;
}

export interface AiStatus {
  provider: string;
  available: boolean;
  detail: string;
  model: string;
  providers: { name: string; label: string }[];
}

/** POST /api/ai/requests. With the copy_prompt provider there is no job: run_id is null,
 * status is "awaiting_answer" and `prompt` is what to paste into Claude (SPEC §17.7). */
export interface AiCreated {
  id: number;
  run_id: number | null;
  status?: "awaiting_answer";
  prompt?: string;
}

/** GET /api/me (password gate, SPEC §17.5). */
export interface Me {
  auth_required: boolean;
  logged_in: boolean;
}

export interface PriceBar {
  t: string;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
}

export interface CorpAction {
  ex_date: string;
  subject: string;
  factor: number | null;
  source: string;
}

export interface PriceSeries {
  symbol: string;
  source: string;
  bars: PriceBar[];
  indicators: Record<string, { t: string; v: number }[]>;
  actions: CorpAction[];
}

export interface IndicatorParam {
  name: string;
  kind: "int" | "float";
  default: number;
  min: number;
  max: number;
  label: string;
}

export interface IndicatorDef {
  name: string;
  label: string;
  explain: string;
  explain_default: string;
  params: IndicatorParam[];
  pane: "price" | "separate" | "none";
  custom: boolean;
}

export interface ChecklistQuestion {
  id: string;
  label: string;
  type: "text" | "number" | "bool" | "choice";
  required: boolean;
  must_be_true?: boolean;
  choices?: string[];
  help?: string;
}

export interface ChecklistQuestions {
  entry: ChecklistQuestion[];
  exit: ChecklistQuestion[];
}

export interface Suggest {
  last_close: number | null;
  atr14: number | null;
  suggested_stop: number | null;
  suggested_target: number | null;
  risk_per_share: number | null;
  qty: number;
  capital: number;
  risk_pct: number;
  rr: number | null;
  next_results?: NextResults | null;
}

export interface Position {
  id: number;
  symbol: string;
  qty: number;
  entry_date: string;
  entry_price: number;
  stop: number | null;
  target: number | null;
  time_stop_date: string | null;
  status: "open" | "closed";
  exit_date: string | null;
  exit_price: number | null;
  exit_reason: string | null;
  last_close: number | null;
  pnl_inr: number | null;
  pnl_pct: number | null;
  r_multiple: number | null;
  to_stop_pct: number | null;
  to_target_pct: number | null;
  days_held: number;
  days_to_time_stop: number | null;
  next_results?: NextResults | null;
}

export interface GroupStats {
  n: number;
  win_rate: number;
  avg_r: number | null;
}

export interface JournalStats {
  closed: number;
  win_rate: number | null;
  avg_r: number | null;
  avg_win_pct: number | null;
  avg_loss_pct: number | null;
  thesis_right_pct: number | null;
  by_exit_reason: Record<string, GroupStats>;
  by_emotion: Record<string, GroupStats>;
}

export interface ChecklistRecord {
  id: number;
  kind: "entry" | "exit";
  symbol: string;
  answers: Record<string, string | number | boolean>;
  ai_review: string | null;
  created_at: string;
}

export interface FundField {
  field: string;
  label: string;
  explain: string;
  unit: string;
  numeric: boolean;
}

export interface QuarterRow {
  source: string;
  symbol: string;
  period_end: string;
  consolidated: number;
  revenue: number | null;
  net_profit: number | null;
  eps: number | null;
  parse_error: string | null;
}

export interface TableData {
  periods: string[];
  rows: Record<string, (number | null)[]>;
}

export interface Fundamentals {
  data: Record<string, number | string | null>;
  sources: Record<string, string>;
  updated_at: string | null;
  quarters: QuarterRow[];
  snapshots: Record<string, { fetched_at: string; detail: { quarters?: TableData; shareholding?: TableData } }>;
}

export type { Rule } from "../lib/rules";

export interface RuleOp {
  name: string;
  words: string;
}

export interface Screen {
  id: number;
  name: string;
  description: string | null;
  rule: import("../lib/rules").Rule;
  describe: string;
  is_preset: boolean;
  created_by: string;
  last_run_as_of: string | null;
  count: number;
}

export interface ScreenResult {
  symbol: string;
  name: string | null;
  values: Record<string, number | null>;
  first_seen: string;
  score: number | null;
  reasons: string[] | null;
}

/** What the editor shows: built from the `screen_preview` run's ok items (key = symbol, detail = values JSON). */
export interface ScreenPreview {
  count: number;
  rows: { symbol: string; values: Record<string, number | null> }[];
}

/** `POST /screens/preview` answer: the preview runs as a job (SPEC §17.5). */
export interface ScreenPreviewStart {
  run_id: number;
}

export interface Announcement {
  id: number;
  source: string;
  symbol: string;
  ts: string;
  category: string;
  headline: string;
  body: string | null;
  url: string | null;
}

export interface AnnouncementCategory {
  category: string;
  alert: boolean;
  severity?: string;
  hidden?: boolean;
}

export interface NewsItem {
  id: number;
  source: string;
  feed: string;
  ts: string;
  title: string;
  url: string;
  summary: string | null;
  symbols: string[];
}

export interface Alert {
  id: number;
  kind: string;
  symbol: string | null;
  message: string;
  link: string | null;
  severity: "info" | "warn" | "critical";
  dedupe_key: string;
  created_at: string;
  seen_at: string | null;
}

export interface AlertKind {
  kind: string;
  label: string;
}

export interface ExitParamDef {
  name: string;
  kind: "int" | "float";
  default: number;
  min: number;
  max: number;
  label: string;
}

export interface ExitDefInfo {
  type: string;
  label: string;
  explain: string;
  when: "intraday" | "close";
  params: ExitParamDef[];
}

export interface ExitSpec {
  type: string;
  params: Record<string, number | import("../lib/rules").Rule>;
}

export interface BatchIn {
  name: string | null;
  configs: BacktestConfig[];
  names?: string[];
}

export interface BatchOut {
  ids: number[];
  run_id: number;
}

export interface BacktestConfig {
  entry_rule: import("../lib/rules").Rule;
  exits: ExitSpec[];
  max_positions: number;
  sizing: "equal" | "risk";
  risk_pct: number;
  start: string;
  end?: string | null;
  oos_start?: string | null;
  initial_capital?: number;
  universe?: "current" | "liquid500";
  rank_by?: { ind: string; params: Record<string, number> };
  max_per_industry?: number | null;
  regime_scale?: { breadth_below: number; slots_pct: number } | null;
  mode?: "signals" | "rotate_monthly";
  hold_buffer?: number;
}

export interface MetricSet {
  cagr: number | null;
  bench_cagr: number | null;
  excess: number | null;
  max_drawdown: number | null;
  volatility: number | null;
  trades: number;
  win_rate: number | null;
  avg_win: number | null;
  avg_loss: number | null;
  profit_factor: number | null;
  avg_days: number | null;
  exposure: number | null;
  best: { symbol: string; pnl_pct: number } | null;
  worst: { symbol: string; pnl_pct: number } | null;
}

export interface Metrics {
  all: MetricSet | null;
  is: MetricSet;
  oos: MetricSet | null;
  oos_start: string | null;
  attempt?: number | null;
}

export interface EquityPoint {
  t: string;
  v: number;
  bench?: number;
}

export interface BacktestTrade {
  symbol: string;
  entry_date: string;
  entry: number;
  exit_date: string;
  exit: number;
  qty: number;
  pnl: number;
  pnl_pct: number;
  reason: string;
  days: number;
}

export interface BacktestListItem {
  id: number;
  name: string | null;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  created_at: string;
  finished_at: string | null;
  kind: "explore" | "final" | "legacy";
  parent_id: number | null;
  metrics: {
    is?: { cagr: number | null; excess: number | null; max_drawdown?: number | null; trades?: number | null } | null;
    oos?: { cagr: number | null; excess: number | null; max_drawdown?: number | null; trades?: number | null } | null;
  } | null;
}

export interface Backtest extends Omit<BacktestListItem, "metrics"> {
  run_id: number | null;
  explore_runs: number;
  attempt: number | null;
  config: BacktestConfig;
  metrics: Metrics | null;
  equity: EquityPoint[] | null;
  trades: BacktestTrade[] | null;
  warnings: string[] | null;
}

export interface ShortlistItem {
  symbol: string;
  name: string | null;
  score: number;
  components: Record<string, number>;
  reasons: string[];
  screens: string[];
  last_close: number | null;
  next_results?: NextResults | null;
}

export interface DashboardSince {
  last_visit_at: string;
  alerts: Alert[];
  new_in_screens: { screen: string; symbols: string[] }[];
  positions: { symbol: string; change_pct_since_visit: number }[];
  announcements: { id: number; symbol: string; ts: string; category: string; headline: string; url: string | null }[];
}

export interface Dashboard {
  shortlist: ShortlistItem[];
  alerts: Alert[];
  positions: { open: number; invested: number; pnl: number; pnl_pct: number | null; open_risk: number };
  data: { last_trading_date: string | null; stale: boolean; updating: boolean; checks_open: number };
  since: DashboardSince | null;
}

export interface JobsStatus {
  updating: boolean;
  last_trading_date: string | null;
  background: { running: RunSummary | null; queued: number };
  interactive: { running: RunSummary | null; queued: number };
}

export interface SourceCoverage {
  source: string;
  symbols: number;
  first_date: string | null;
  last_date: string | null;
  rows: number;
}

export interface SignalOutcome {
  status: string;
  entry_date: string | null;
  entry_fill: number | null;
  gap_pct: number | null;
  exit_date: string | null;
  exit_fill: number | null;
  exit_reason: string | null;
  days_held: number | null;
  return_pct: number | null;
  r_multiple: number | null;
  mfe_r: number | null;
  mae_r: number | null;
  excess_pct: number | null;
}

export interface Signal {
  id: number;
  source: string;
  screen_id: number | null;
  screen_name: string | null;
  symbol: string;
  name: string | null;
  as_of: string;
  rank: number | null;
  score: number | null;
  reasons: unknown[];
  planned_entry: number | null;
  planned_stop: number | null;
  planned_target: number | null;
  app_version: string | null;
  current_price?: number | null;
  outcome: SignalOutcome | null;
}

export interface SignalsPage {
  total: number;
  rows: Signal[];
}

export interface SignalGroup {
  key: string;
  label: string;
  kind: string;
  n_closed: number;
  n_open: number;
  n_pending: number;
  hit_rate_pct: number | null;
  avg_return_pct: number | null;
  avg_r: number | null;
  avg_excess_pct: number | null;
  avg_days: number | null;
  enough: boolean;
}

/** One logging of a stock inside an idea (SPEC §16.7). */
export interface IdeaSeen {
  signal_id: number;
  as_of: string;
  source: string;
  screen_id: number | null;
  screen_name: string | null;
  rank: number | null;
  score: number | null;
}

/** A stock's loggings grouped while the first one is being followed; graded on that first one. */
export interface Idea {
  id: number;
  symbol: string;
  name: string | null;
  first_as_of: string;
  last_as_of: string;
  score: number | null;
  reasons: unknown[];
  planned_entry: number | null;
  planned_stop: number | null;
  planned_target: number | null;
  current_price?: number | null;
  seen: IdeaSeen[];
  outcome: SignalOutcome | null;
}

export interface IdeasPage {
  total: number;
  counts: { open: number; pending: number; closed: number; no_data: number };
  rows: Idea[];
}

export interface SignalsSummary {
  groups: SignalGroup[];
  coverage: { first_day: string | null; last_day: string | null; days_logged: number; trading_days: number };
  min_closed: number;
  n_signals: number;
  n_ideas: number;
}

/** One broker Buy or Sell call (GET /research/reports). */
export interface ResearchReport {
  source: string;
  report_id: string;
  date: string;
  symbol: string | null;
  stock: string;
  author: string;
  type: "Buy" | "Sell";
  ltp: number | null;
  target: number | null;
  reco_price: number | null;
  change_pct: number | null;
  upside_pct: number | null;
  url: string | null;
  fetched_at: string;
  /** The stock has its own page in this app. */
  tracked: boolean;
}
