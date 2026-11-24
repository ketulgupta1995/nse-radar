import pytest

from app.backtest.costs import fill_price, trade_costs

MODEL = {
    "brokerage_pct": 0.03, "brokerage_cap_inr": 20, "stt_pct": 0.1,
    "exchange_pct": 0.00297, "sebi_pct": 0.0001, "stamp_buy_pct": 0.015,
    "gst_pct": 18, "dp_charge_inr": 15.93, "slippage_pct": 0.10,
}


def test_buy_one_lakh():
    # brokerage = min(100000*0.03%=30, 20) = 20
    # STT = 100000*0.1% = 100; exchange = 100000*0.00297% = 2.97; SEBI = 0.10
    # GST = 18% * (20+2.97+0.10) = 4.1526; stamp = 100000*0.015% = 15
    assert trade_costs("buy", 100000, MODEL) == pytest.approx(20 + 100 + 2.97 + 0.10 + 4.1526 + 15)


def test_sell_one_lakh():
    # same as buy but no stamp; DP charge 15.93 instead
    assert trade_costs("sell", 100000, MODEL) == pytest.approx(20 + 100 + 2.97 + 0.10 + 4.1526 + 15.93)


def test_small_trade_brokerage_below_cap():
    # value 10000: brokerage = 3 (0.03%) < cap; STT 10; exchange 0.297; SEBI 0.01
    # GST = 18% * (3+0.297+0.01) = 0.59526; stamp 1.5
    assert trade_costs("buy", 10000, MODEL) == pytest.approx(3 + 10 + 0.297 + 0.01 + 0.59526 + 1.5)


def test_fill_price_slippage():
    assert fill_price("buy", 100, MODEL) == pytest.approx(100.1)
    assert fill_price("sell", 100, MODEL) == pytest.approx(99.9)
