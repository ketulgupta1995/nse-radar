import pytest

from app.sources.adapters.nse_api import NseApi
from app.sources.parsers.actions import parse_action_subject, parse_nse_date

SPLIT = "Face Value Split (Sub-Division) - From Rs {} Per Share To {} Per Share"


@pytest.mark.parametrize(
    ("subject", "kind", "factor"),
    [
        (SPLIT.format("10/-", "Rs 2/-"), "split", 0.2),
        (SPLIT.format("5/-", "Re 1/-"), "split", 0.2),
        (SPLIT.format("2/-", "Rs 1/-"), "split", 0.5),
        ("Bonus 1:1", "bonus", 0.5),
        ("Bonus 3:2", "bonus", 0.4),
        ("Bonus 1:2", "bonus", 2 / 3),
        ("Interim Dividend - Rs 12 Per Share", "other", None),
        ("Annual General Meeting", "other", None),
        ("Rights 1:5 @ Premium Rs 100/-", "rights", None),
        ("Demerger", "demerger", None),
        ("Scheme Of Demerger", "demerger", None),
        ("Composite Scheme Of Arrangement", "demerger", None),
        ("Scheme Of Arrangement", "demerger", None),
        ("Rights 19:67 @ Premium Rs 215 Per Share", "rights", None),
        ("Rights Issue - 3:5 @ Premium Rs.93/-", "rights", None),
        ("Rights - 4:25 Fully Paid Up Shares @ Premium", "rights", None),
        ("Face Value Split something odd", "unparsed", None),
        ("Bonus issue", "unparsed", None),
        ("Bonus 1:1 And Dividend Rs 2", "bonus", 0.5),
    ],
)
def test_subject_table(subject, kind, factor):
    k, f = parse_action_subject(subject)
    assert k == kind
    assert f == pytest.approx(factor) if factor is not None else f is None


T076_CASES = [
    ("Bonus 1:1 / Face Value Split From Rs.10/- To Re.1/-", "split", 0.05),
    ("Bonus 1:1 And Face Value Split From Rs.10/- To Rs.5/-", "split", 0.25),
    ("Bonus - 1:1 And Face Value Split From Rs. 10 To Rs. 2", "split", 0.1),
    ("Bonus 1 : 1 / Face Value Split From Rs 10/- Each To Rs 2/- Each", "split", 0.1),
    ("Bonus 1:2/Face Value Split (Sub-Division) From Rs 2/- Per Share To Re 1/- Per Share", "split", 0.3333),
    ("Bonus 1:1 And Face Value Split Rs.10/- To Rs.5/- Per Share", "split", 0.25),
    ("Face Value Split Rs.10/- To Re.1/- Per Share", "split", 0.1),
    ("Face Value Split Rs 10 To Rs 2", "split", 0.2),
    ("Fv Split Rs.10 To Rs.5", "split", 0.5),
    ("Face Value Split (Sub-Division) - From Rs 10/- Per Share To Re 1/- Per Share", "split", 0.1),
    (
        "Interim Div - Rs 6/- Per Share + Face Value Split (Sub-Division) - "
        "From Rs 10/- Per Share To Re 1/- Per Share",
        "split",
        0.1,
    ),
    ("Dividend Rs.6/- Per Share And Face Value Split From Rs.2/- To Re.1/-", "split", 0.5),
    ("Bonus- 1:2", "bonus", 0.6667),
    ("Bonus Shares In The Ratio Of 1:1", "bonus", 0.5),
    ("Annual General Meeting / Dividend - Rs 3/- Per Share / Bonus - 1:2", "bonus", 0.6667),
    ("Bonus 1:1/Dividend- Rs 13.5 Per Share", "bonus", 0.5),
    ("Bonus  1:4", "bonus", 0.8),
    ("Bonus 1 : 1250", "bonus", 0.9992),
    ("Scheme Of Arrangement - Bonus Debentures 6:1", "other", None),
    ("Sch Of Agmt- Bonus Deb1:1", "other", None),
    ("Scheme Of Arangement- Bonus - 1 Debenture For 1 Equity Share Held", "other", None),
    ("Scheme Of Arrangement - Bonus Ncrps 4:1", "other", None),
    ("Bonus Preference Shares 21:1", "other", None),
    ("Dividend - Rs 10 Per Share", "other", None),
    ("Face Value Split", "unparsed", None),
]


@pytest.mark.parametrize(("subject", "kind", "factor"), T076_CASES)
def test_t076_subjects(subject, kind, factor):
    k, f = parse_action_subject(subject)
    assert k == kind
    if factor is None:
        assert f is None
    else:
        assert round(f, 4) == factor


@pytest.mark.parametrize("subject,kind,factor", [
    ("Fv Splt Frm Rs 10 To Rs 2", "split", 0.2),
    ("Fv Splt Frm Rs 10 To Re 1", "split", 0.1),
    ("Fv Splt Frm Rs 10 To Rs 5", "split", 0.5),
    ("Fv Spl-Rs10tors5/Bon-2:1", "split", 1 / 6),
    ("Bon 1:1/Fv Spl Rs.5tors.2", "split", 0.2),
    ("Bon-2:1", "bonus", 1 / 3),
    ("Spl Int Div-Rs.100 P Shr Purpose Revised", "other", None),
    ("Div- Int Rs.25+Spl Rs.100purpose Revised", "other", None),
    ("Sch Of Agmt- Bonus Deb1:1", "other", None),
    ("Carbon Bonanza 2:1", "other", None),
])
def test_abbreviated_wordings(subject, kind, factor):
    k, f = parse_action_subject(subject)
    assert k == kind
    assert (f is None) if factor is None else f == pytest.approx(factor)


def test_parse_nse_date():
    assert parse_nse_date("14-Oct-2026") == "2026-10-14"
    assert parse_nse_date("-") is None
    assert parse_nse_date(None) is None
    assert parse_nse_date("garbage") is None


def test_adapter_filters_eq_and_parses(monkeypatch):
    import json
    from pathlib import Path

    from app.sources import http

    data = (Path(__file__).parent / "fixtures/sources/nse_api/corp_actions_SAMPLE.json").read_bytes()
    http.set_transport(lambda url, params, headers: (200, data))
    try:
        acts = NseApi().actions("sample")
    finally:
        http.set_transport(None)
    assert [(a.ex_date, a.kind) for a in acts] == [
        ("2026-03-20", "other"), ("2026-06-02", "bonus"), ("2026-10-14", "split")
    ]
    assert acts[1].factor == 0.5 and acts[2].factor == pytest.approx(0.2)
    assert json.dumps([a.symbol for a in acts]) == '["SAMPLE", "SAMPLE", "SAMPLE"]'
