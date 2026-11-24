from pathlib import Path

from app.analytics.fundamentals import FIELD_BY_NAME
from app.sources import http
from app.sources.adapters.screener import Screener
from app.sources.parsers.screener_html import parse_company_page, to_fields

FIX = Path(__file__).parent / "fixtures/sources/screener/TCS_consolidated.html"
HTML = FIX.read_bytes()


def test_fixture_parses():
    p = parse_company_page(HTML)
    assert isinstance(p["ratios"]["roce"], float) and isinstance(p["ratios"]["pe"], float)
    q = p["quarters"]
    assert len(q["periods"]) > 8
    assert all(len(v) == len(q["periods"]) for v in q["rows"].values())
    assert "Promoters" in p["shareholding"]["rows"]
    assert isinstance(p["growth"]["sales_cagr"]["3y"], float)
    assert p["growth"]["roe"]["ttm"] is not None
    assert p["missing"] == []


def test_to_fields_subset_of_spec():
    f = to_fields(parse_company_page(HTML))
    assert set(f) <= set(FIELD_BY_NAME)
    assert f["pb"] and f["pb"] > 0
    assert 0 <= f["debt_to_equity"] < 1
    assert f["profit_positive_4q"] == 1.0
    assert 0 < f["promoter_pct"] < 100 and f["promoter_change_1y_pp"] is not None
    assert f["sales_growth_yoy_pct"] is not None


def test_missing_quarters_section_is_reported():
    soup_html = HTML.decode("utf-8", "replace")
    start = soup_html.index('<section id="quarters"')
    end = soup_html.index("</section>", start) + len("</section>")
    p = parse_company_page((soup_html[:start] + soup_html[end:]).encode())
    assert "quarters" in p["missing"]
    f = to_fields(p)
    assert f["sales_growth_yoy_pct"] is None and f["profit_positive_4q"] is None


def test_garbage_html_does_not_raise():
    p = parse_company_page(b"<html><body>nothing</body></html>")
    assert {"ratios", "quarters", "shareholding", "growth"} <= set(p["missing"])
    assert to_fields(p)["pe"] is None


def test_detail_keeps_balance_sheet_and_ratios():
    http.set_transport(lambda url, params, headers: (200, HTML))
    try:
        snap = Screener().fundamentals("TCS")
    finally:
        http.set_transport(None)
    assert snap.detail["balance_sheet"]["periods"] and snap.detail["ratios_hist"]["periods"]


def test_falls_back_to_standalone_when_quarters_blank():
    html = HTML.decode("utf-8", "replace")
    start = html.index('<section id="quarters"')
    end = html.index("</section>", start) + len("</section>")
    blank = (html[:start] + html[end:]).encode()
    calls = []

    def fake(url, params, headers):
        calls.append(url)
        return 200, (blank if url.endswith("/consolidated/") else HTML)

    http.set_transport(fake)
    try:
        snap = Screener().fundamentals("TCS")
    finally:
        http.set_transport(None)
    assert snap.detail["variant"] == "standalone" and len(calls) == 2
