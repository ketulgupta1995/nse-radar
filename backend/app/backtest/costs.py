"""Indian delivery trade costs (SPEC §12.1)."""

from typing import Literal

Side = Literal["buy", "sell"]


def trade_costs(side: Side, value_inr: float, model: dict) -> float:
    """Total rupees of charges for one buy or sell of `value_inr`."""
    brokerage = min(value_inr * model["brokerage_pct"] / 100, model["brokerage_cap_inr"])
    exchange = value_inr * model["exchange_pct"] / 100
    sebi = value_inr * model["sebi_pct"] / 100
    gst = (brokerage + exchange + sebi) * model["gst_pct"] / 100
    stt = value_inr * model["stt_pct"] / 100
    if side == "buy":
        extra = value_inr * model["stamp_buy_pct"] / 100
    else:
        extra = model["dp_charge_inr"]
    return brokerage + exchange + sebi + gst + stt + extra


def fill_price(side: Side, open_price: float, model: dict) -> float:
    """Price actually paid/received after slippage: buys pay more, sells get less."""
    slip = model["slippage_pct"] / 100
    return open_price * (1 + slip) if side == "buy" else open_price * (1 - slip)
