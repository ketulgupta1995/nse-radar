"""Forward-test outcomes: what happened after each logged signal (SPEC §16.3)."""

from __future__ import annotations

import json
import logging
import math

import pandas as pd

from app import db, timeutil
from app.analytics import frames, indicators
from app.backtest import exits as exits_mod
from app.backtest.costs import fill_price, trade_costs

log = logging.getLogger(__name__)

STALE_DAYS = 14
STATUSES = ("pending", "open", "closed", "no_data")
COLUMNS = (
    "status", "entry_date", "entry_fill", "gap_pct", "stop_level", "target_level", "exit_date",
    "exit_fill", "exit_reason", "days_held", "return_pct", "r_multiple", "mfe_r", "mae_r",
    "stock_cc_pct", "nifty_cc_pct", "excess_pct", "last_bar",
)  # fmt: skip


def _empty(status: str, last_bar: str | None) -> dict:
    out = dict.fromkeys(COLUMNS)
    out["status"] = status
    out["last_bar"] = last_bar
    return out


def _date(ts: pd.Timestamp) -> str:
    return ts.strftime("%Y-%m-%d")


def _exit_defs(cfg: dict) -> list[tuple[exits_mod.ExitDef, dict]]:
    out = []
    for e in cfg["exits"]:
        if e["type"] == "rule_exit":
            log.warning("signal exit_config contains rule_exit; ignored")
            continue
        d = exits_mod.EXITS[e["type"]]
        out.append((d, exits_mod.resolve_params(d, e.get("params") or {})))
    return out


def _bar(frame: pd.DataFrame, i: int) -> pd.Series:
    r = frame.iloc[i]
    return pd.Series({k: float(r[k]) for k in ("open", "high", "low", "close")})


def _replay(frame: pd.DataFrame, e: int, defs: list, states: list[dict]) -> tuple[int, float, str] | None:
    """Walk bars from the entry bar; the engine's order. Returns (exit bar, raw price, reason)."""
    order = sorted(
        (i for i, (d, _) in enumerate(defs) if d.when == "intraday"),
        key=lambda i: not exits_mod.is_stop(defs[i][0].type),
    )
    close_exits = [i for i, (d, _) in enumerate(defs) if d.when == "close"]
    pending: str | None = None
    for t in range(e, len(frame)):
        bar = _bar(frame, t)
        if pending is not None:  # scheduled yesterday: sell at today's open
            return t, float(bar["open"]), pending
        if t > e:  # the entry bar itself is not checked intraday (engine order)
            for i in order:
                hit, price, reason = defs[i][0].check(
                    states[i], bar, {"days_held": t - e, "signals": {}, "idx": i}
                )
                if hit:
                    return t, float(bar["open"]) if price is None else float(price), reason
        for i in close_exits:
            hit, _, reason = defs[i][0].check(states[i], bar, {"days_held": t - e, "signals": {}, "idx": i})
            if hit:
                pending = reason
                break
    return None


def _net_return_pct(entry_fill: float, sell_price: float, notional: float, model: dict) -> float:
    qty = max(1, int(notional // entry_fill))
    buy_value = entry_fill * qty
    buy_cost = trade_costs("buy", buy_value, model)
    sell_value = fill_price("sell", sell_price, model) * qty
    sell_cost = trade_costs("sell", sell_value, model)
    return (sell_value - sell_cost - buy_value - buy_cost) / (buy_value + buy_cost) * 100


def _bench_at(bench: pd.Series, ts: pd.Timestamp) -> float | None:
    if bench is None or len(bench) == 0:
        return None
    v = bench.astype(float).asof(ts)
    return None if v is None or math.isnan(v) else float(v)


def compute_outcome(
    signal: dict, frame: pd.DataFrame, bench: pd.Series, model: dict, newest_bar: str
) -> dict:
    """Pure: the signal_outcomes columns for one signal (no signal_id / updated_at)."""
    if len(frame) == 0:
        return _empty("no_data", None)
    last_ts = frame.index[-1]
    last_bar = _date(last_ts)
    stale = (pd.Timestamp(newest_bar) - last_ts).days > STALE_DAYS
    as_of = pd.Timestamp(signal["as_of"])
    e = int(frame.index.searchsorted(as_of, side="right"))  # first bar after as_of
    if e >= len(frame):
        return _empty("no_data" if stale else "pending", last_bar)
    if as_of not in frame.index:
        return _empty("no_data", last_bar)
    atr = float(indicators.compute("atr", frame, bench, n=14).loc[as_of])
    if math.isnan(atr):
        return _empty("no_data", last_bar)

    cfg = (
        signal["exit_config"]
        if isinstance(signal["exit_config"], dict)
        else json.loads(signal["exit_config"])
    )
    defs = _exit_defs(cfg)
    entry_open = float(frame["open"].iloc[e])
    entry_fill = fill_price("buy", entry_open, model)
    pos = {"entry_fill": entry_fill, "atr14": atr}
    states = [dict(d.setup({**pos, "exit_idx": i}, p)) for i, (d, p) in enumerate(defs)]
    stop_idx = next((i for i, (d, _) in enumerate(defs) if exits_mod.is_stop(d.type)), None)
    target_idx = next((i for i, (d, _) in enumerate(defs) if d.type.startswith("target_")), None)
    stop_level = states[stop_idx]["level"] if stop_idx is not None else None
    target_level = states[target_idx]["level"] if target_idx is not None else None

    hit = _replay(frame, e, defs, states)
    end = hit[0] if hit else len(frame) - 1
    exit_price = hit[1] if hit else float(frame["close"].iloc[-1])
    status = "closed" if hit else ("no_data" if stale else "open")

    risk = entry_fill - stop_level if stop_level is not None else None
    span = frame.iloc[e : end + 1]

    def in_r(price: float) -> float | None:
        return (price - entry_fill) / risk if risk and risk > 0 else None

    entry_ts, end_ts = frame.index[e], frame.index[end]
    stock_cc = (float(frame["close"].iloc[end]) / float(frame["close"].iloc[e]) - 1) * 100
    b0, b1 = _bench_at(bench, entry_ts), _bench_at(bench, end_ts)
    nifty_cc = (b1 / b0 - 1) * 100 if b0 and b1 else None
    return {
        "status": status,
        "entry_date": _date(entry_ts),
        "entry_fill": entry_fill,
        "gap_pct": (entry_open / float(frame["close"].loc[as_of]) - 1) * 100,
        "stop_level": stop_level,
        "target_level": target_level,
        "exit_date": _date(end_ts) if hit else None,
        "exit_fill": exit_price if hit else None,
        "exit_reason": hit[2] if hit else None,
        "days_held": end - e,
        "return_pct": _net_return_pct(entry_fill, exit_price, float(cfg.get("notional_inr", 100000)), model),
        "r_multiple": in_r(exit_price),
        "mfe_r": in_r(float(span["high"].max())),
        "mae_r": in_r(float(span["low"].min())),
        "stock_cc_pct": stock_cc,
        "nifty_cc_pct": nifty_cc,
        "excess_pct": stock_cc - nifty_cc if nifty_cc is not None else None,
        "last_bar": last_bar,
    }


def update_outcomes(ctx=None) -> dict:
    """Recompute outcomes that are missing, unfinished, or stale. Returns status counts."""
    with db.tx() as c:
        signals = [dict(r) for r in c.execute("SELECT * FROM signals ORDER BY id")]
        existing = {r["signal_id"]: dict(r) for r in c.execute("SELECT * FROM signal_outcomes")}
        model = db.get_setting("cost_model", c)
    newest_bar = frames.last_trading_date() or timeutil.today().isoformat()
    bench = frames.load_benchmark()
    cache: dict[str, pd.DataFrame] = {}  # loaded outside any write transaction
    for s in signals:
        if s["symbol"] not in cache:
            cache[s["symbol"]] = frames.load_frame(s["symbol"])

    rows: list[tuple[int, dict]] = []
    for s in signals:
        if ctx:
            ctx.check_stop()
        old = existing.get(s["id"])
        frame = cache[s["symbol"]]
        if old and old["status"] == "closed":
            newest_sym = _date(frame.index[-1]) if len(frame) else None
            if newest_sym is None or (old["last_bar"] and newest_sym <= old["last_bar"]):
                continue
        try:
            rows.append((s["id"], compute_outcome(s, frame, bench, model, newest_bar)))
        except Exception:
            log.exception("outcome failed for signal %s", s["id"])
    now = timeutil.now_iso()
    cols = ("signal_id", *COLUMNS, "updated_at")
    sql = (
        f"INSERT INTO signal_outcomes({', '.join(cols)}) VALUES ({','.join('?' * len(cols))}) "
        f"ON CONFLICT(signal_id) DO UPDATE SET {', '.join(f'{k}=excluded.{k}' for k in cols[1:])}"
    )
    with db.tx() as c:
        for sid, o in rows:
            c.execute(sql, (sid, *(o[k] for k in COLUMNS), now))
        counts = dict.fromkeys(STATUSES, 0)
        for r in c.execute("SELECT status, COUNT(*) AS n FROM signal_outcomes GROUP BY status"):
            counts[r["status"]] = r["n"]
    return counts
