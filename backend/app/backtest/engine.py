"""Daily-bar backtester (SPEC §12.2). Signals use bar t's close; fills use bar t+1's open."""

import json
import logging
import math
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, field_validator

from app import db
from app.analytics import frames as frames_mod
from app.analytics import fundamentals, indicators, rules
from app.backtest import exits as exits_mod
from app.backtest import history as history_mod
from app.backtest import universe as universe_mod
from app.backtest.costs import fill_price, trade_costs

log = logging.getLogger(__name__)

SIGNAL_CACHE = 8  # signal sets a batch keeps; configs sharing signals run next to each other
DEFAULT_EXITS = [
    {"type": "stop_atr", "params": {"k": 2}},
    {"type": "target_atr", "params": {"k": 4}},
    {"type": "time_stop", "params": {"days": 40}},
]


class BacktestConfig(BaseModel):
    entry_rule: dict
    exits: list[dict] = DEFAULT_EXITS
    max_positions: int = 10
    sizing: Literal["equal", "risk"] = "equal"
    risk_pct: float = 0.5
    start: str = "2012-01-01"
    end: str | None = None
    oos_start: str | None = None  # test-period start; None -> holdout_start setting (SPEC §12.6)
    initial_capital: float = 1_000_000
    universe: Literal["current", "liquid500"] = "liquid500"
    rank_by: dict = {"ind": "rel_strength", "params": {"n": 126}}
    max_per_industry: int | None = None
    regime_scale: dict | None = None
    mode: Literal["signals", "rotate_monthly"] = "signals"
    hold_buffer: float = 1.5

    @field_validator("initial_capital")
    @classmethod
    def _capital(cls, v: float) -> float:
        if not 10_000 <= v <= 1_000_000_000:
            raise ValueError("initial_capital must be between 10,000 and 100 crore")
        return v

    @field_validator("hold_buffer")
    @classmethod
    def _buffer(cls, v: float) -> float:
        if not 1.0 <= v <= 3.0:
            raise ValueError("hold_buffer must be between 1.0 and 3.0")
        return v

    @field_validator("rank_by")
    @classmethod
    def _rank_by(cls, v: dict) -> dict:
        if v.get("rank"):
            raise ValueError("rank_by: 'rank' is not allowed here")
        if "ind" not in v:
            raise ValueError("rank_by must be an indicator")
        rules.validate_rule({"all": [{"left": v, "op": ">", "right": {"value": 0}}]})
        return v

    @field_validator("max_per_industry")
    @classmethod
    def _cap(cls, v: int | None) -> int | None:
        if v is not None and not 1 <= v <= 50:
            raise ValueError("max_per_industry must be between 1 and 50")
        return v

    @field_validator("regime_scale")
    @classmethod
    def _regime(cls, v: dict | None) -> dict | None:
        if v is None:
            return v
        if set(v) != {"breadth_below", "slots_pct"}:
            raise ValueError("regime_scale needs breadth_below and slots_pct")
        if not 10 <= v["breadth_below"] <= 90:
            raise ValueError("breadth_below must be between 10 and 90")
        if not 0 <= v["slots_pct"] <= 100:
            raise ValueError("slots_pct must be between 0 and 100")
        return v

    @field_validator("entry_rule")
    @classmethod
    def _entry(cls, v: dict) -> dict:
        rules.validate_rule(v)
        return v

    @field_validator("exits")
    @classmethod
    def _exits(cls, v: list[dict]) -> list[dict]:
        out = []
        for e in v:
            t = e.get("type")
            if t not in exits_mod.EXITS:
                raise ValueError(f"unknown exit type: {t}")
            out.append(
                {"type": t, "params": exits_mod.resolve_params(exits_mod.EXITS[t], e.get("params") or {})}
            )
        return out


def _load_liquid500(cfg: BacktestConfig) -> tuple[dict, dict, int]:
    """Frames for every stock that was among the 500 most traded, plus entry masks and dropped count."""
    ranks = universe_mod.liquidity_ranks()
    today = set(frames_mod.universe())
    frames: dict = {}
    eligible: dict = {}
    repaired = dropped = 0
    for sym in universe_mod.candidate_symbols(ranks, cfg.start):
        f = frames_mod.load_frame(sym)
        if not len(f):
            continue
        if sym not in today:
            f, fixes = history_mod.repair_frame(f)
            if f is None:
                dropped += 1
                continue
            repaired += 1 if fixes else 0
        frames[sym] = f
        eligible[sym] = universe_mod.eligible_mask(ranks, f.index, sym)
    log.info("liquid500 universe: %d loaded, %d repaired, %d dropped", len(frames), repaired, dropped)
    return frames, eligible, dropped


def _rule_list(cfg: BacktestConfig) -> list[dict]:
    return [cfg.entry_rule] + [e["params"]["rule"] for e in cfg.exits if "rule" in e["params"]]


def _used_fund_fields(cfg: BacktestConfig) -> set[str]:
    return set().union(*(rules.fund_fields(r) for r in _rule_list(cfg)))


def _overlay_pit_fields(cfg: BacktestConfig, frames: dict, fund: dict) -> dict:
    """Replace the snapshot's quarter, yearly and holding fields with as-published series."""
    return overlay_fields(_used_fund_fields(cfg), frames, fund)


def overlay_fields(wanted: set[str], frames: dict, fund: dict) -> dict:
    """`_overlay_pit_fields` for an explicit set of field names (a batch passes the union)."""
    groups = [
        (fundamentals.pit_quarter_series, [f for f in fundamentals.QUARTER_FIELDS if f in wanted]),
        (fundamentals.pit_history_series, [f for f in fundamentals.HISTORY_FIELDS if f in wanted]),
    ]
    groups = [(fn, used) for fn, used in groups if used]
    if not groups:
        return fund
    out = dict(fund)
    with db.tx() as c:
        for sym, f in frames.items():
            for fn, used in groups:
                series = fn(sym, f.index, c)
                out[sym] = {**out.get(sym, {}), **{k: series[k] for k in used}}
    return out


def load_fund_snapshot() -> dict:
    with db.tx() as c:
        rows = c.execute("SELECT symbol, data FROM fundamentals").fetchall()
    return {r["symbol"]: json.loads(r["data"]) for r in rows}


def _load_real(cfg: BacktestConfig, frames, bench, fund, eligible=None):
    dropped = 0
    if frames is None:
        if cfg.universe == "liquid500":
            frames, eligible, dropped = _load_liquid500(cfg)
        else:
            frames = {}
            for sym in frames_mod.universe():
                f = frames_mod.load_frame(sym)
                if len(f):
                    frames[sym] = f
    if bench is None:
        bench = frames_mod.load_benchmark()
    if fund is None:
        fund = _overlay_pit_fields(cfg, frames, load_fund_snapshot())
    return frames, bench, fund, eligible, dropped


def _build_ranks(rule_list: list, frames: dict, bench, idx, eligible: dict | None) -> dict[str, dict]:
    """{symbol: {rank_key: percentile Series on idx}}; ranked only among eligible symbols with a bar."""
    seen: dict[tuple, rules.Operand] = {}
    for r in rule_list:
        for o in rules.rank_operands(r):
            seen.setdefault(rules.rank_key(o), o)
    out: dict[str, dict] = {}
    for key, o in seen.items():
        cols = {}
        for sym, f in frames.items():
            v = indicators.compute(o.ind, f, bench, **o.params).reindex(idx).astype(float)
            v[f["close"].reindex(idx).isna()] = np.nan
            mask = (eligible or {}).get(sym)
            if mask is not None:
                v[~mask.reindex(idx, fill_value=False).to_numpy(dtype=bool)] = np.nan
            cols[sym] = v
        pct = rules.cross_rank(pd.DataFrame(cols, index=idx))
        for sym in cols:
            out.setdefault(sym, {})[key] = pct[sym]
    return out


class _Prices:
    """Per-symbol price arrays on the master date index. They depend only on the frames, the dates and
    `rank_by`, so a batch builds them once and shares them. The day loop only reads them."""

    def __init__(self, cfg: BacktestConfig, frames: dict, bench, symbols: list[str], idx) -> None:
        shape = (len(idx), len(symbols))
        nan = lambda: np.full(shape, np.nan)  # noqa: E731
        self.open, self.high, self.low, self.close = nan(), nan(), nan(), nan()
        self.rank_val, self.atr = nan(), nan()
        self.last_t = np.full(len(symbols), -1, dtype=int)
        for j, sym in enumerate(symbols):
            f = frames[sym]
            rs = indicators.compute(cfg.rank_by["ind"], f, bench, **(cfg.rank_by.get("params") or {}))
            atr = indicators.compute("atr", f, bench, n=14)
            cols = {"open": self.open, "high": self.high, "low": self.low, "close": self.close}
            for name, arr in cols.items():
                arr[:, j] = f[name].reindex(idx).to_numpy(dtype=float)
            seen = np.flatnonzero(~np.isnan(self.open[:, j]))
            self.last_t[j] = int(seen[-1]) if len(seen) else -1
            self.rank_val[:, j] = rs.reindex(idx).to_numpy(dtype=float)
            self.atr[:, j] = atr.reindex(idx).to_numpy(dtype=float)
        # latest close up to each day (NaN before a stock's first bar): marks positions to market
        self.close_ff = pd.DataFrame(self.close).ffill().to_numpy()


def _build_prices(cfg: BacktestConfig, frames: dict, bench, symbols: list[str], idx, shared=None) -> _Prices:
    if shared is None or not len(idx):
        return _Prices(cfg, frames, bench, symbols, idx)
    key = (idx[0], idx[-1], len(idx), json.dumps(cfg.rank_by, sort_keys=True))
    if key not in shared.arrays:
        shared.arrays[key] = _Prices(cfg, frames, bench, symbols, idx)
    return shared.arrays[key]


class _Data:
    """Per-symbol series aligned to the master date index, as (days x symbols) arrays."""

    def __init__(
        self,
        cfg: BacktestConfig,
        frames: dict,
        bench,
        fund: dict,
        eligible: dict | None = None,
        industries: dict[str, str] | None = None,
        shared=None,
    ) -> None:
        self.symbols = sorted(frames)
        self.industry = [(industries or {}).get(sym) for sym in self.symbols]
        idx = _date_index(cfg, frames, shared)
        self.dates = idx
        p = _build_prices(cfg, frames, bench, self.symbols, idx, shared)
        self.open, self.high, self.low, self.close = p.open, p.high, p.low, p.close
        self.rank_val, self.atr, self.last_t = p.rank_val, p.atr, p.last_t
        self.close_ff = p.close_ff
        sig = _build_signals(cfg, frames, bench, fund, eligible, self.symbols, idx, shared)
        self.entry, self.exit_sig = sig.entry, sig.exit_sig


def _date_index(cfg: BacktestConfig, frames: dict, shared=None) -> pd.DatetimeIndex:
    """Every trading day any frame has, from `cfg.start` to `cfg.end`; a batch builds it once per span."""
    key = ("dates", cfg.start, cfg.end)
    if shared is not None and key in shared.arrays:
        return shared.arrays[key]
    idx = (
        pd.DatetimeIndex(np.unique(np.concatenate([f.index.to_numpy() for f in frames.values()])))
        if frames
        else pd.DatetimeIndex([])
    )
    idx = idx[idx >= pd.Timestamp(cfg.start)]
    if cfg.end:
        idx = idx[idx <= pd.Timestamp(cfg.end)]
    if shared is not None:
        shared.arrays[key] = idx
    return idx


class _Signals:
    """Entry and exit-rule signals as (days x symbols) bool arrays. They depend only on the rules, the
    dates and the group's data, so a batch builds them once per distinct rule set. Read-only after."""

    def __init__(self, cfg, frames, bench, fund, eligible, symbols: list[str], idx, memo=None) -> None:
        shape = (len(idx), len(symbols))
        self.entry = np.zeros(shape, dtype=bool)
        exit_rules = {i: e["params"]["rule"] for i, e in enumerate(cfg.exits) if "rule" in e["params"]}
        self.exit_sig = {i: np.zeros(shape, dtype=bool) for i in exit_rules}
        all_rules = [cfg.entry_rule, *exit_rules.values()]
        ranks = _build_ranks(all_rules, frames, bench, idx, eligible)
        for j, sym in enumerate(symbols):
            f = frames[sym]
            fd = fund.get(sym)
            sym_ranks = ranks.get(sym)
            ent = rules.evaluate(cfg.entry_rule, f, bench, fd, sym_ranks, memo)
            self.entry[:, j] = ent.reindex(idx, fill_value=False).to_numpy(dtype=bool)
            mask = (eligible or {}).get(sym)
            if mask is not None:
                self.entry[:, j] &= mask.reindex(idx, fill_value=False).to_numpy(dtype=bool)
            for i, rule in exit_rules.items():
                s = rules.evaluate(rule, f, bench, fd, sym_ranks, memo)
                self.exit_sig[i][:, j] = s.reindex(idx, fill_value=False).to_numpy(dtype=bool)


def _build_signals(cfg, frames, bench, fund, eligible, symbols, idx, shared=None) -> _Signals:
    if shared is None or not len(idx):
        return _Signals(cfg, frames, bench, fund, eligible, symbols, idx)
    exit_rules = [[i, e["params"]["rule"]] for i, e in enumerate(cfg.exits) if "rule" in e["params"]]
    key = ("signals", idx[0], idx[-1], len(idx), json.dumps([cfg.entry_rule, exit_rules], sort_keys=True))
    if key in shared.arrays:
        shared.arrays[key] = shared.arrays.pop(key)  # most recently used goes last
        return shared.arrays[key]
    held = [k for k in shared.arrays if k[0] == "signals"]
    for k in held[: max(0, len(held) - SIGNAL_CACHE + 1)]:  # ~4 MB each on 10 years x 1,700 stocks
        del shared.arrays[k]
    shared.arrays[key] = _Signals(cfg, frames, bench, fund, eligible, symbols, idx, shared.memo)
    return shared.arrays[key]


def _warnings(cfg: BacktestConfig) -> list[str]:
    used = _used_fund_fields(cfg)
    out = []
    if used & set(fundamentals.QUARTER_FIELDS):
        out.append(
            "Quarterly growth fields use results as they were published (from the day after filing). "
            "They are only available from 2019, so the rule can't pass on earlier dates."
        )
    if used & set(fundamentals.HISTORY_FIELDS):
        out.append(
            "Yearly figures (ROCE, ROE, debt, 3-year growth) and promoter holding use Screener.in's "
            "history as it was published: a year counts from 60 days after it ends, a shareholding "
            "quarter from 21 days after. Yearly history starts with FY2015 (3-year growth from "
            "mid-2018) and promoter holding covers only the last 3 years, so the rule can't pass "
            "before then. Only stocks in today's Nifty 500 have this history."
        )
    snapshot = sorted(used - set(fundamentals.QUARTER_FIELDS) - set(fundamentals.HISTORY_FIELDS))
    if snapshot:
        labels = ", ".join(fundamentals.FIELD_BY_NAME[f]["label"] for f in snapshot)
        out.append(
            "A rule uses fundamentals. The app only has today's figures, so the test sees numbers "
            "that weren't known back then (look-ahead). Treat those results with caution. "
            f"Fields: {labels}"
        )
    return out


def _bar(d: _Data, t: int, j: int) -> dict:
    """Today's bar as a plain dict (exit checks only index it by column name)."""
    return {"open": d.open[t, j], "high": d.high[t, j], "low": d.low[t, j], "close": d.close[t, j]}


def _industry_map(symbols: list[str], industries: dict[str, str] | None, real: bool) -> dict[str, str]:
    if industries is not None:
        return industries
    if not real:
        return {}
    return {s: i for s in symbols if (i := frames_mod.industry_of(s))}


def _scaled_slots(cfg: BacktestConfig, breadth_t: float) -> int:
    rs = cfg.regime_scale
    if rs and not math.isnan(breadth_t) and breadth_t < rs["breadth_below"]:
        return math.floor(cfg.max_positions * rs["slots_pct"] / 100)
    return cfg.max_positions


def run_backtest(
    cfg: BacktestConfig,
    ctx=None,
    frames=None,
    bench=None,
    fund=None,
    eligible=None,
    industries=None,
    breadth=None,
    shared=None,
) -> dict:
    """With `shared` (a batch.Shared) the real-data setup comes from it and nothing is reloaded."""
    real = frames is None
    if shared is not None:
        frames, bench, fund = shared.frames, shared.bench, shared.fund
        eligible, dropped = shared.eligible, shared.dropped
        industries, breadth = shared.industries, shared.breadth
        real = False  # everything the real path would load is already in `shared`
    else:
        frames, bench, fund, eligible, dropped = _load_real(cfg, frames, bench, fund, eligible)
    model = db.get_setting("cost_model")
    warnings = _warnings(cfg)
    if dropped:
        warnings.append(f"{dropped} stocks with price jumps that could not be explained were left out.")
    defs = [exits_mod.EXITS[e["type"]] for e in cfg.exits]
    order = sorted(
        (i for i, d in enumerate(defs) if d.when == "intraday"),
        key=lambda i: not exits_mod.is_stop(defs[i].type),
    )
    close_exits = [i for i, d in enumerate(defs) if d.when == "close"]
    first_stop = next((i for i, d in enumerate(defs) if exits_mod.is_stop(d.type)), None)
    if cfg.sizing == "risk" and first_stop is None:
        warnings.append("Risk sizing needs a stop-loss exit; none was set, so equal sizing was used.")

    industries = _industry_map(sorted(frames), industries, real) if cfg.max_per_industry else None
    d = _Data(cfg, frames, bench, fund, eligible, industries, shared)
    n_days = len(d.dates)
    breadth_arr = np.full(n_days, np.nan)
    if cfg.regime_scale:
        if breadth is None and real:
            breadth = frames_mod.load_breadth(200)
        if breadth is not None and len(breadth):
            breadth_arr = breadth.astype(float).reindex(d.dates, method="ffill").to_numpy()
    if ctx:
        ctx.set_total(n_days)
    cash = cfg.initial_capital
    positions: dict[int, dict] = {}
    mark = -1  # positions are valued at the latest close up to day `mark` (-1: none yet)
    pending_buy: list[tuple[int, float]] = []
    pending_sell: dict[int, str] = {}
    trades: list[dict] = []
    equity: list[dict] = []

    def date_str(t: int) -> str:
        return d.dates[t].strftime("%Y-%m-%d")

    def sell(j: int, t: int, price: float, reason: str) -> None:
        nonlocal cash
        pos = positions.pop(j)
        px = fill_price("sell", price, model)
        value = px * pos["qty"]
        cost = trade_costs("sell", value, model)
        cash += value - cost
        invested = pos["entry"] * pos["qty"] + pos["buy_cost"]
        pnl = value - cost - invested
        trades.append(
            {
                "symbol": d.symbols[j],
                "entry_date": pos["entry_date"],
                "entry": round(pos["entry"], 4),
                "exit_date": date_str(t),
                "exit": round(px, 4),
                "qty": pos["qty"],
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl / invested * 100, 3),
                "reason": reason,
                "days": t - pos["t"],
            }
        )
        pending_sell.pop(j, None)

    def last_close(j: int, entry: float) -> float:
        px = d.close_ff[mark, j] if mark >= 0 else math.nan
        return entry if math.isnan(px) else float(px)

    def equity_now() -> float:
        return cash + sum(p["qty"] * last_close(j, p["entry"]) for j, p in positions.items())

    def buy(j: int, t: int, atr: float) -> None:
        nonlocal cash
        entry = fill_price("buy", d.open[t, j], model)
        pos0 = {"entry_fill": entry, "atr14": atr}
        states = [
            dict(defs[i].setup({**pos0, "exit_idx": i}, cfg.exits[i]["params"])) for i in range(len(defs))
        ]
        eq = equity_now()
        qty = int(eq / cfg.max_positions / entry)
        if cfg.sizing == "risk" and first_stop is not None:
            risk_per_share = entry - states[first_stop]["level"]
            if risk_per_share <= 0:
                return
            qty = min(qty, int(eq * cfg.risk_pct / 100 / risk_per_share))
        qty = min(qty, int(cash / (entry * 1.005)))
        while qty > 0 and entry * qty + trade_costs("buy", entry * qty, model) > cash:
            qty -= 1
        if qty <= 0:
            return
        cost = trade_costs("buy", entry * qty, model)
        cash -= entry * qty + cost
        positions[j] = {
            "qty": qty,
            "entry": entry,
            "buy_cost": cost,
            "t": t,
            "entry_date": date_str(t),
            "states": states,
        }

    for t in range(n_days):
        if ctx and t % 50 == 0:
            ctx.check_stop()
        has_bar = ~np.isnan(d.open[t])
        # 0. stocks that stopped trading for good are sold at their last close
        for j in [j for j in positions if t > d.last_t[j]]:
            lt = int(d.last_t[j])
            px = d.close[lt, j] if lt >= 0 else float("nan")
            if np.isnan(px):
                px = last_close(j, positions[j]["entry"])
            sell(j, t, float(px), "delisted")
        # 1. exits scheduled yesterday fill at today's open
        for j in list(pending_sell):
            if has_bar[j]:
                sell(j, t, d.open[t, j], pending_sell[j])
        # 2. intraday exits on today's bar (stops before targets)
        for j in list(positions):
            if not has_bar[j]:
                continue
            bar = _bar(d, t, j)
            pos = positions[j]
            for i in order:
                c = {"days_held": t - pos["t"], "signals": {}, "idx": i}
                hit, price, reason = defs[i].check(pos["states"][i], bar, c)
                if hit:
                    sell(j, t, bar["open"] if price is None else price, reason)
                    break
        # 3. entries scheduled yesterday fill at today's open
        for j, atr in pending_buy:
            if j not in positions and has_bar[j] and len(positions) < cfg.max_positions:
                buy(j, t, atr)
        pending_buy = []
        # 4. mark to market
        mark = t
        eq = equity_now()
        equity.append({"t": date_str(t), "v": round(eq, 2)})
        # 5. close exits schedule a sale at the next open
        for j, pos in positions.items():
            if j in pending_sell or not has_bar[j]:
                continue
            bar = _bar(d, t, j)
            sig = {k: bool(v[t, j]) for k, v in d.exit_sig.items()}
            for i in close_exits:
                c = {"days_held": t - pos["t"], "signals": sig, "idx": i}
                hit, _, reason = defs[i].check(pos["states"][i], bar, c)
                if hit:
                    pending_sell[j] = reason
                    break
        # 6. new entry signals, best ranked first
        if t >= n_days - 1:
            continue
        if cfg.mode == "rotate_monthly":
            if d.dates[t + 1].month != d.dates[t].month:
                slots = _scaled_slots(cfg, breadth_arr[t])
                pending_buy = _rotate(cfg, d, t, has_bar, positions, pending_sell, slots)
            continue
        free = _scaled_slots(cfg, breadth_arr[t]) - (len(positions) - len(pending_sell))
        if free > 0:
            cand = _ranked(d, t, has_bar, positions)
            pending_buy = _pick(cfg, d, cand, free, positions, t)

    for j, pos in list(positions.items()):  # still open at the end: report at the last close
        px = last_close(j, pos["entry"])
        value = px * pos["qty"]
        cost = trade_costs("sell", value, model)
        invested = pos["entry"] * pos["qty"] + pos["buy_cost"]
        pnl = value - cost - invested
        trades.append(
            {
                "symbol": d.symbols[j],
                "entry_date": pos["entry_date"],
                "entry": round(pos["entry"], 4),
                "exit_date": date_str(n_days - 1),
                "exit": round(px, 4),
                "qty": pos["qty"],
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl / invested * 100, 3),
                "reason": "end of test",
                "days": n_days - 1 - pos["t"],
            }
        )

    warnings.extend(_industry_warning(cfg, d, trades))
    _add_bench(equity, d.dates, bench, cfg.initial_capital)
    return {"equity": equity, "trades": trades, "metrics": {}, "warnings": warnings}


def _ranked(d: _Data, t: int, has_bar, exclude: dict) -> list:
    """Stocks passing the entry rule today, best rank first, skipping `exclude`."""
    cand = [j for j in np.flatnonzero(d.entry[t] & has_bar) if j not in exclude and t < d.last_t[j]]
    rv = d.rank_val
    cand.sort(key=lambda j: (-(rv[t, j] if not math.isnan(rv[t, j]) else -math.inf), j))
    return cand


def _rotate(cfg, d: _Data, t: int, has_bar, positions: dict, pending_sell: dict, target: int) -> list:
    """Month-end rotation: schedule sales of holdings outside the keep list, return new buys."""
    ranked = _ranked(d, t, has_bar, {})
    keep_n = math.ceil(cfg.max_positions * cfg.hold_buffer)
    keep = {j for j, _ in _pick(cfg, d, ranked, keep_n, {}, t)}
    for j in positions:
        if j not in keep and j not in pending_sell:
            pending_sell[j] = "rotation"
    held = {j: p for j, p in positions.items() if j not in pending_sell}
    free = target - len(held)
    if free <= 0:
        return []
    cand = [j for j in ranked if j not in positions]
    return _pick(cfg, d, cand, free, held, t)


def _pick(cfg: BacktestConfig, d: _Data, cand: list, free: int, positions: dict, t: int) -> list:
    """Best-ranked candidates that fit the free slots and the industry cap."""
    cap = cfg.max_per_industry
    count: dict[str, int] = {}
    if cap:
        for j in positions:
            if d.industry[j]:
                count[d.industry[j]] = count.get(d.industry[j], 0) + 1
    out: list[tuple[int, float]] = []
    for j in cand:
        if len(out) >= free:
            break
        ind = d.industry[j]
        if cap and ind:
            if count.get(ind, 0) >= cap:
                continue
            count[ind] = count.get(ind, 0) + 1
        out.append((j, float(d.atr[t, j])))
    return out


def _industry_warning(cfg: BacktestConfig, d: _Data, trades: list[dict]) -> list[str]:
    if not cfg.max_per_industry or not trades:
        return []
    known = {s: d.industry[j] for j, s in enumerate(d.symbols)}
    pct = 100 * sum(1 for tr in trades if not known.get(tr["symbol"])) / len(trades)
    if pct < 10:
        return []
    return [
        f"Industry cap: {pct:.0f}% of trades were in stocks with no known industry (mostly ones that "
        "later left the market), so the cap did not apply to them."
    ]


def _add_bench(equity: list[dict], dates: pd.DatetimeIndex, bench, capital: float) -> None:
    if bench is None or len(bench) == 0 or not len(dates):
        return
    b = bench.astype(float).reindex(dates, method="ffill").dropna()
    if not len(b):
        return
    scaled = b / b.iloc[0] * capital
    for row, dt in zip(equity, dates, strict=True):
        if dt in scaled.index:
            row["bench"] = round(float(scaled[dt]), 2)
