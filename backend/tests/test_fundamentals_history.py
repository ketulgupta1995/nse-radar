import json

import numpy as np
import pandas as pd

from app import db
from app.analytics import fundamentals as fnd

YEARS = ["Mar 2019", "Mar 2020", "Mar 2021", "Mar 2022", "Mar 2023", "Mar 2024"]
SALES = [100.0, 110.0, 120.0, 133.1, 150.0, 170.0]
PROFIT = [-5.0, 10.0, 12.0, 20.0, 25.0, 30.0]  # FY2019 is a loss: negative base year
EQ_CAP = [10.0] * 6
RESERVES = [90.0, 100.0, 110.0, 140.0, 150.0, 190.0]
DEBT = [50.0, 60.0, 40.0, 30.0, 20.0, 10.0]
ROCE = [11.0, 12.0, None, 18.0, 19.0, 20.0]
PBT = [1.0, 14.0, 16.0, 26.0, 33.0, 40.0]
INTEREST = [4.0, 5.0, 6.0, 7.0, 8.0, 9.0]
PROMOTER = [50.0, 51.0, 52.0, 53.0, 54.0, 52.5, 52.0, 51.0]  # Mar 2022 .. Dec 2023


def _detail() -> dict:
    return {
        "profit_loss": {
            "periods": [*YEARS, "TTM"],
            "rows": {
                "Sales": [*SALES, 180.0],
                "Net Profit": [*PROFIT, 31.0],
                "Profit before tax": [*PBT, 41.0],
                "Interest": [*INTEREST, 9.0],
            },
        },
        "balance_sheet": {
            "periods": [*YEARS, "Sep 2024"],
            "rows": {
                "Equity Capital": [*EQ_CAP, 10.0],
                "Reserves": [*RESERVES, 999.0],
                "Borrowings": [*DEBT, 1.0],
            },
        },
        "ratios_hist": {"periods": YEARS, "rows": {"ROCE %": ROCE}},
        "shareholding": {
            "periods": ["Mar 2022", "Jun 2022", "Sep 2022", "Dec 2022", "Mar 2023", "Jun 2023", "Sep 2023",
                        "Dec 2023"],
            "rows": {"Promoters": PROMOTER},
        },
    }  # fmt: skip


def _store(detail: dict | None) -> None:
    with db.tx() as c:
        c.execute("INSERT INTO symbols(symbol, name, in_universe) VALUES ('HIS','His',1)")
        if detail is not None:
            c.execute(
                "INSERT INTO fund_snapshots(source, symbol, fetched_at, fields, detail) "
                "VALUES ('screener','HIS','2024-01-01','{\"roce_pct\": 99}', ?)",
                (json.dumps(detail),),
            )


def _series(dates: list[str]) -> dict[str, pd.Series]:
    with db.tx() as c:
        return fnd.pit_history_series("HIS", pd.DatetimeIndex(pd.to_datetime(dates)), c)


def test_debt_to_equity_known_sixty_days_after_year_end(client):
    _store(_detail())
    s = _series(["2020-05-29", "2020-05-30"])["debt_to_equity"]
    assert s.iloc[0] == round(50.0 / 100.0, 3)  # the day before, FY2019 still applies
    assert s.iloc[1] == round(60.0 / 110.0, 3)  # FY2020: 60 / (10 + 100)


def test_roce_uses_ratio_row_else_fallback(client):
    _store(_detail())
    s = _series(["2020-06-01", "2021-06-01"])["roce_pct"]
    assert s.iloc[0] == 12.0
    # FY2021 cell is None: (16 + 6) / (10 + 110 + 40) * 100
    assert s.iloc[1] == round(22.0 / 160.0 * 100, 2)


def test_profit_growth_3y_needs_year_three_back_and_positive_base(client):
    _store(_detail())
    s = _series(["2021-06-01", "2022-05-29", "2022-06-01", "2023-06-01"])["profit_growth_3y_pct"]
    assert s.isna().iloc[0]  # FY2021 known, FY2018 missing
    assert s.isna().iloc[1]
    assert s.iloc[2] != s.iloc[2]  # FY2022 vs FY2019 loss: negative base -> NaN
    assert s.iloc[3] == round(((25.0 / 10.0) ** (1 / 3) - 1) * 100, 2)  # FY2023 vs FY2020


def test_sales_growth_3y_value(client):
    _store(_detail())
    s = _series(["2022-06-01"])["sales_growth_3y_pct"]
    assert s.iloc[0] == round(((133.1 / 100.0) ** (1 / 3) - 1) * 100, 2)


def test_interim_balance_sheet_and_ttm_columns_ignored(client):
    _store(_detail())
    s = _series(["2025-01-15"])  # FY2024 known; Sep 2024 reserves of 999 must not be used
    assert s["debt_to_equity"].iloc[0] == round(10.0 / 200.0, 3)
    assert s["roe_pct"].iloc[0] == round(30.0 / 200.0 * 100, 2)


def test_promoter_change_needs_five_quarters(client):
    _store(_detail())
    s = _series(["2023-04-20", "2023-04-22", "2024-01-20"])
    # Mar 2023 quarter known 2023-04-21; the quarter a year earlier is Mar 2022
    assert s["promoter_change_1y_pp"].isna().iloc[0]
    assert s["promoter_pct"].iloc[0] == 53.0  # Dec 2022 known 2023-01-21
    assert s["promoter_change_1y_pp"].iloc[1] == round(54.0 - 50.0, 2)
    assert s["promoter_pct"].iloc[1] == 54.0
    assert s["promoter_change_1y_pp"].iloc[2] == 0.0  # Sep 2023 (52.0) vs Sep 2022 (52.0)


def test_before_first_known_column_is_nan(client):
    _store(_detail())
    s = _series(["2019-01-01"])
    assert all(v.isna().all() for v in s.values())


def test_stale_data_is_nan(client):
    _store(_detail())
    # FY2024 ends 2024-03-31: +550 days = 2025-10-02 is the last good day
    y = _series(["2025-10-02", "2025-10-03"])
    assert y["debt_to_equity"].iloc[0] == 0.05 and y["debt_to_equity"].isna().iloc[1]
    # Dec 2023 holding: +200 days = 2024-07-18 is the last good day
    h = _series(["2024-07-18", "2024-07-19"])["promoter_pct"]
    assert h.iloc[0] == 51.0 and h.isna().iloc[1]


def test_no_screener_row_or_missing_tables_is_all_nan(client):
    _store(None)
    s = _series(["2024-06-01"])
    assert list(s) == list(fnd.HISTORY_FIELDS) and all(v.isna().all() for v in s.values())
    with db.tx() as c:
        c.execute(
            "INSERT INTO fund_snapshots(source, symbol, fetched_at, fields, detail) "
            "VALUES ('screener','HIS','2024-01-01','{}', ?)",
            (json.dumps({"profit_loss": _detail()["profit_loss"]}),),
        )
    s = _series(["2024-06-01"])
    assert np.isnan(s["debt_to_equity"].iloc[0]) and np.isnan(s["promoter_pct"].iloc[0])
    assert s["sales_growth_3y_pct"].iloc[0] > 0  # P&L alone still yields growth
