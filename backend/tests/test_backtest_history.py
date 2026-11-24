import pandas as pd

from app.backtest.history import repair_frame


def _frame(closes: list[float]) -> pd.DataFrame:
    idx = pd.bdate_range("2024-01-01", periods=len(closes))
    df = pd.DataFrame(
        {
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [100.0] * len(closes),
            "value": [5.0] * len(closes),
        },
        index=idx,
    )
    df.attrs["symbol"] = "X"
    return df


def _continuous(df: pd.DataFrame) -> bool:
    return bool((df["close"] / df["close"].shift(1)).dropna().between(0.55, 1.45).all())


def test_clean_series():
    f = _frame([100, 101, 102, 101])
    out, n = repair_frame(f)
    assert n == 0 and out is not f
    pd.testing.assert_frame_equal(out, f)


def test_empty():
    out, n = repair_frame(pd.DataFrame())
    assert n == 0 and out is not None


def test_1_to_10_split():
    out, n = repair_frame(_frame([170, 180, 18, 18.5]))
    assert n == 1
    assert out["close"].iloc[:2].tolist() == [17.0, 18.0]
    assert out["volume"].iloc[:2].tolist() == [1000.0, 1000.0]
    assert out["volume"].iloc[2:].tolist() == [100.0, 100.0]
    assert out["value"].tolist() == [5.0] * 4
    assert _continuous(out)


def test_two_splits():
    out, n = repair_frame(_frame([100, 50, 51, 10.2, 10]))
    assert n == 2
    assert _continuous(out)


def test_bonus_ratio_below_threshold_not_a_jump():
    # prev/close = 1.5 is only a -33% move: above the 0.55 trigger, so left alone (see ticket notes).
    out, n = repair_frame(_frame([150, 100, 100]))
    assert n == 0
    assert out["close"].tolist() == [150, 100, 100]


def test_drop_2_5():
    out, n = repair_frame(_frame([100, 40, 40]))
    assert n == 1 and abs(out["close"].iloc[0] - 40) < 1e-9


def test_unmatched_drop():
    out, n = repair_frame(_frame([100, 100 / 2.7, 37]))
    assert out is None and n == 0


def test_rise_unrepairable():
    out, n = repair_frame(_frame([100, 160, 161]))
    assert out is None and n == 0


def test_seven_jumps():
    closes = [1e7]
    for _ in range(7):
        closes.append(closes[-1] / 2)
    out, n = repair_frame(_frame(closes))
    assert out is None and n == 6


def test_input_unchanged_attrs_kept():
    f = _frame([180, 18, 18])
    before = f.copy()
    out, _ = repair_frame(f)
    pd.testing.assert_frame_equal(f, before)
    assert out.attrs == {"symbol": "X"}
