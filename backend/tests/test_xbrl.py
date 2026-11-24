import json
from pathlib import Path

import pytest

from app.sources import http
from app.sources.adapters.nse_api import NseApi
from app.sources.parsers.xbrl import XbrlError, parse_integrated_list, parse_results_list, parse_xbrl

FIX = Path(__file__).parent / "fixtures/sources/nse_api"
ITEMS = json.loads((FIX / "financial_results_TCS.json").read_text())
SAMPLE = (FIX / "xbrl_sample.xml").read_bytes()


def test_results_list_on_fixture():
    rows = parse_results_list(ITEMS)
    assert [(r["period_end"], r["consolidated"]) for r in rows] == [
        ("2024-12-31", True),
        ("2024-12-31", False),
        ("2024-09-30", True),
    ]
    r = rows[0]
    assert r["period_start"] == "2024-10-01" and r["audited"] is True
    assert r["filing_date"] == "2025-01-09" and r["xbrl_url"].endswith(".xml")


def test_results_list_drops_no_xbrl_and_keeps_latest_filing():
    old = {**ITEMS[0], "filingDate": "01-Jan-2025 10:00", "xbrl": "https://x/old.xml"}
    no_xbrl = {**ITEMS[2], "xbrl": None}
    rows = parse_results_list([old, ITEMS[0], no_xbrl])
    assert len(rows) == 1 and rows[0]["xbrl_url"] == ITEMS[0]["xbrl"]


def test_parse_xbrl_sample():
    q = parse_xbrl(SAMPLE, "2024-10-01", "2024-12-31")
    assert q["revenue"] == pytest.approx(63973.0) and q["revenue"] > 50000  # the quarter, not YTD
    assert q["net_profit"] == pytest.approx(12380.0) and q["net_profit"] > 0
    assert q["pbt"] == pytest.approx(16666.0) and q["eps"] == pytest.approx(34.21)
    assert q["other_income"] == pytest.approx(1243.0) and q["total_expenses"] == pytest.approx(48550.0)


@pytest.mark.parametrize("junk", [b"", b"not xml", b"<a><b/></a>"])
def test_garbage_raises(junk):
    with pytest.raises(XbrlError):
        parse_xbrl(junk, "2024-10-01", "2024-12-31")


def test_wrong_period_raises():
    with pytest.raises(XbrlError):
        parse_xbrl(SAMPLE, "2020-01-01", "2020-03-31")


def test_quarters_failure_does_not_stop_others_and_known_skipped():
    def fake(url, params, headers):
        if "financial-results" in url:
            return 200, json.dumps(ITEMS).encode()
        if url.endswith("INDAS_117182_1341298_09012025093940.xml"):
            return 200, SAMPLE
        return 404, b""

    http.set_transport(fake)
    try:
        qs = NseApi().quarters("tcs", set())
        known = NseApi().quarters("TCS", {"2024-12-31"})
    finally:
        http.set_transport(None)
    assert [q.period_end for q in qs] == ["2024-12-31", "2024-09-30"]
    assert qs[0].parse_error is None and qs[0].consolidated and qs[0].revenue > 50000
    assert qs[1].parse_error and qs[1].revenue is None
    assert [q.period_end for q in known] == ["2024-09-30"]


INTEGRATED = json.loads((FIX / "integrated_results_TCS.json").read_text())
INTEGRATED_XML = (FIX / "xbrl_integrated_sample.xml").read_bytes()
INTEGRATED_URL = "INTEGRATED_FILING_INDAS_1734607_08102026100810_WEB.xml"


def test_integrated_list_on_fixture():
    rows = parse_integrated_list(INTEGRATED)
    assert len(rows) == 14 and len({r["period_end"] for r in rows}) == 7
    assert (rows[0]["period_end"], rows[0]["consolidated"]) == ("2026-09-30", True)
    assert rows[0]["period_start"] == "2026-07-01" and rows[0]["filing_date"] == "2026-10-08"
    assert rows[0]["xbrl_url"].endswith(INTEGRATED_URL)
    assert rows[-1]["period_end"] == "2025-03-31"
    assert {r["period_start"] for r in rows if r["period_end"] == "2025-12-31"} == {"2025-10-01"}


def test_integrated_list_skips_other_types_and_keeps_latest_revision():
    first = INTEGRATED["data"][0]
    governance = {**first, "type": "Integrated Filing- Governance", "xbrl": "https://x/gov.xml"}
    revised = {**first, "broadcast_Date": "01-Nov-2026 10:00:00", "xbrl": "https://x/revised.xml"}
    rows = parse_integrated_list({"data": [governance, first, revised]})
    assert [r["xbrl_url"] for r in rows] == ["https://x/revised.xml"]
    assert parse_integrated_list({"data": []}) == [] and parse_integrated_list("junk") == []


def test_parse_integrated_xbrl_sample():
    q = parse_xbrl(INTEGRATED_XML, "2026-07-01", "2026-09-30")
    assert q["revenue"] == pytest.approx(73188.0) and q["net_profit"] == pytest.approx(13884.0)
    assert q["pbt"] == pytest.approx(18638.0) and q["eps"] == pytest.approx(38.37)


def test_quarters_merge_integrated_and_old_lists():
    def fake(url, params, headers):
        if "integrated-filing-results" in url:
            return 200, json.dumps(INTEGRATED).encode()
        if "financial-results" in url:
            return 200, json.dumps(ITEMS).encode()
        if url.endswith(INTEGRATED_URL):
            return 200, INTEGRATED_XML
        return 404, b""

    http.set_transport(fake)
    try:
        qs = NseApi().quarters("TCS", set())
        only_old = NseApi().quarters("TCS", {r["period_end"] for r in parse_integrated_list(INTEGRATED)})
    finally:
        http.set_transport(None)
    assert len(qs) == 9  # 7 integrated + 2 old periods, newest first
    assert qs[0].period_end == "2026-09-30" and qs[0].consolidated and qs[0].revenue > 70000
    assert [q.period_end for q in qs[-2:]] == ["2024-12-31", "2024-09-30"]
    assert [q.period_end for q in only_old] == ["2024-12-31", "2024-09-30"]


def test_quarters_old_list_missing_still_uses_integrated():
    def fake(url, params, headers):
        if "integrated-filing-results" in url:
            return 200, json.dumps(INTEGRATED).encode()
        return 404, b""

    http.set_transport(fake)
    try:
        qs = NseApi().quarters("TCS", set())
    finally:
        http.set_transport(None)
    assert len(qs) == 7 and qs[-1].period_end == "2025-03-31"


UNDECLARED = (FIX / "xbrl_undeclared_oned.xml").read_bytes()


def test_undeclared_oned_context_used():
    q = parse_xbrl(UNDECLARED, "2021-04-01", "2021-06-30")
    assert q["revenue"] == pytest.approx(27896.0) and q["net_profit"] == pytest.approx(5195.0)
    assert q["eps"] == pytest.approx(12.21)
    assert q["other_income"] == pytest.approx(724.0) and q["pbt"] == pytest.approx(6870.0)
    assert q["total_expenses"] == pytest.approx(21750.0)


def test_declared_match_beats_oned():
    plain = (
        b'<xbrli:context id="D2023"><xbrli:entity><xbrli:identifier scheme="x">I</xbrli:identifier>'
        b"</xbrli:entity><xbrli:period><xbrli:startDate>2021-04-01</xbrli:startDate>"
        b"<xbrli:endDate>2021-06-30</xbrli:endDate></xbrli:period></xbrli:context>"
        b'<in-bse-fin:Revenue contextRef="D2023">10000000</in-bse-fin:Revenue>'
        b'<in-bse-fin:ProfitLossForPeriod contextRef="D2023">20000000</in-bse-fin:ProfitLossForPeriod>'
    )
    q = parse_xbrl(UNDECLARED.replace(b"</xbrli:xbrl>", plain + b"</xbrli:xbrl>"), "2021-04-01", "2021-06-30")
    assert q["net_profit"] == pytest.approx(2.0) and q["revenue"] == pytest.approx(1.0)


def test_no_plain_context_and_no_oned_raises():
    doc = UNDECLARED.replace(b'contextRef="OneD"', b'contextRef="Other"')
    with pytest.raises(XbrlError, match="no context matches"):
        parse_xbrl(doc, "2021-04-01", "2021-06-30")


def test_parse_bank_xbrl_sample():  # banks use the in-capmkt banking tags (HDFCBANK, Sep 2026)
    q = parse_xbrl((FIX / "xbrl_bank_sample.xml").read_bytes(), "2026-07-01", "2026-09-30")
    assert q["revenue"] == pytest.approx(95131.63) and q["net_profit"] == pytest.approx(20700.03)
    assert q["pbt"] == pytest.approx(27825.48) and q["eps"] == pytest.approx(13.43)
