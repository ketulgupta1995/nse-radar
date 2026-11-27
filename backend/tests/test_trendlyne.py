"""Trendlyne research list: parsing, storing and the API. Fixture rows are made up."""

from pathlib import Path

import pytest

from app import db
from app.sources import store
from app.sources.parsers.trendlyne import parse_research_page

PAGE = (Path(__file__).parent / "fixtures" / "sources" / "trendlyne" / "list.html").read_bytes()


def test_only_buy_and_sell_rows_are_kept() -> None:
    rows, reports = parse_research_page(PAGE)
    assert rows == 5
    assert [(r.symbol, r.type) for r in reports] == [("AAA", "Buy"), ("BBB", "Sell"), ("CCC", "Buy")]


def test_every_column_is_read() -> None:
    alpha, beta, gamma = parse_research_page(PAGE)[1]
    assert (alpha.report_id, alpha.date, alpha.stock) == ("1004", "2026-11-27", "Alpha & Co")
    assert alpha.author == "North Broker"  # without the upgrade badges
    assert (alpha.ltp, alpha.target, alpha.reco_price) == (1020.0, 1300.0, 1000.0)
    assert (alpha.change_pct, alpha.upside_pct) == (2.0, 27.45)
    assert alpha.url == "https://trendlyne.com/posts/1004/"
    assert (beta.change_pct, beta.upside_pct) == (-1.58, 8.42)  # a Sell's upside is published unsigned
    assert gamma.change_pct == 0.0  # no bracket and the price has not moved


@pytest.mark.parametrize(
    "content", [b"<html>blocked</html>", PAGE.replace(b"<th>LTP</th>", b"<th>Last</th>")]
)
def test_changed_layout_fails_loudly(content: bytes) -> None:
    with pytest.raises(ValueError):
        parse_research_page(content)


def test_store_updates_a_report_seen_again_and_api_filters(client) -> None:
    reports = parse_research_page(PAGE)[1]
    with db.tx() as c:
        assert store.save("research", "trendlyne", reports, key="all", conn=c) == 3
    newer = parse_research_page(PAGE.replace(b"1020.00", b"1100.00"))[1]
    with db.tx() as c:
        store.save("research", "trendlyne", newer, key="all", conn=c)
        c.execute("INSERT INTO symbols(symbol, name) VALUES ('AAA', 'Alpha')")
    rows = client.get("/api/research/reports").json()
    assert [r["symbol"] for r in rows] == ["AAA", "BBB", "CCC"]  # newest first, no duplicates
    assert rows[0]["ltp"] == 1100.0
    assert [r["tracked"] for r in rows] == [True, False, False]
    sells = client.get("/api/research/reports", params={"type": "Sell"}).json()
    assert [r["symbol"] for r in sells] == ["BBB"]
    assert client.get("/api/research/reports", params={"type": "Hold"}).status_code == 422
