"""NSE quarterly-results list and XBRL filings (SPEC §9.1). Pure functions.

Element names, contexts and units were confirmed on a real TCS file (docs/DATA_SOURCES.md, T032):
values are full rupees (`unitRef="INR"`), so crore = value / 1e7. A filing has several duration
contexts with the same dates (`OneD` = the quarter, `FourD` = year to date), so after matching on
dates the context id `OneD` wins.
"""

from __future__ import annotations

from datetime import datetime

from lxml import etree

from app.sources.parsers.actions import parse_nse_date

CRORE = 1e7


class XbrlError(ValueError): ...


def _filing_dt(item: dict) -> datetime:
    for key, fmt in (("filingDate", "%d-%b-%Y %H:%M"), ("broadCastDate", "%d-%b-%Y %H:%M:%S")):
        try:
            return datetime.strptime((item.get(key) or "").strip(), fmt)
        except ValueError:
            continue
    return datetime.min


def parse_results_list(items: list[dict]) -> list[dict]:
    """-> [{period_end, period_start, consolidated, audited, filing_date, xbrl_url}], newest period first."""
    best: dict[tuple[str, bool], tuple[datetime, dict]] = {}
    for it in items:
        if not isinstance(it, dict) or not (it.get("xbrl") or "").strip().startswith("http"):
            continue
        end = parse_nse_date(it.get("toDate"))
        if end is None:
            continue
        consolidated = it.get("consolidated") == "Consolidated"
        when = _filing_dt(it)
        if (end, consolidated) in best and best[(end, consolidated)][0] >= when:
            continue
        best[(end, consolidated)] = (
            when,
            {
                "period_end": end,
                "period_start": parse_nse_date(it.get("fromDate")),
                "consolidated": consolidated,
                "audited": it.get("audited") == "Audited",
                "filing_date": when.date().isoformat() if when != datetime.min else None,
                "xbrl_url": it["xbrl"].strip(),
            },
        )
    rows = [v[1] for v in best.values()]
    return sorted(rows, key=lambda r: (r["period_end"], r["consolidated"]), reverse=True)


INTEGRATED_FINANCIALS = "Integrated Filing- Financials"


def _quarter_start(end: str) -> str:
    """'2026-09-30' -> '2026-07-01' (first day of the 3-month quarter ending on `end`)."""
    y, m = int(end[:4]), int(end[5:7]) - 2
    if m < 1:
        y, m = y - 1, m + 12
    return f"{y}-{m:02d}-01"


def parse_integrated_list(payload: object) -> list[dict]:
    """NSE `integrated-filing-results` -> same rows as `parse_results_list`, newest period first.

    Since 2025 (quarters ending Mar 2025 onwards) NSE publishes results only as "Integrated
    Filing- Financials"; the old results list stops at Dec 2024. Revised filings replace the
    original for the same period (latest broadcast wins).
    """
    items = payload.get("data") if isinstance(payload, dict) else payload
    best: dict[tuple[str, bool], tuple[datetime, dict]] = {}
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict) or it.get("type") != INTEGRATED_FINANCIALS:
            continue
        url = (it.get("xbrl") or "").strip()
        end = parse_nse_date(it.get("qe_Date"))
        if not url.startswith("http") or end is None:
            continue
        consolidated = it.get("consolidated") == "Consolidated"
        try:
            when = datetime.strptime((it.get("broadcast_Date") or "").strip(), "%d-%b-%Y %H:%M:%S")
        except ValueError:
            when = datetime.min
        if (end, consolidated) in best and best[(end, consolidated)][0] >= when:
            continue
        best[(end, consolidated)] = (
            when,
            {
                "period_end": end,
                "period_start": _quarter_start(end),
                "consolidated": consolidated,
                "audited": it.get("audited") == "Audited",
                "filing_date": when.date().isoformat() if when != datetime.min else None,
                "xbrl_url": url,
            },
        )
    rows = [v[1] for v in best.values()]
    return sorted(rows, key=lambda r: (r["period_end"], r["consolidated"]), reverse=True)


# Candidate local names, first match wins. Marked names were seen in a real file; others are
# plausible variants (banks, older taxonomies) and unverified.
_CANDIDATES: dict[str, tuple[str, ...]] = {
    "revenue": ("RevenueFromOperations", "Revenue", "InterestEarned"),  # only the first is verified
    "other_income": ("OtherIncome",),
    "total_expenses": ("Expenses",),
    "pbt": ("ProfitBeforeTax", "ProfitLossFromOrdinaryActivitiesBeforeTax"),  # 2nd: banks
    "net_profit": (
        "ProfitOrLossAttributableToOwnersOfParent",
        "ProfitLossForPeriod",
        "ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates",  # banks (seen)
        "ProfitLossForThePeriod",  # banks (seen)
    ),
    "eps": (
        "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
        "BasicEarningsLossPerShareFromContinuingOperations",
        "BasicEarningsPerShareAfterExtraordinaryItems",  # banks (seen)
    ),
}
_PER_SHARE = {"eps"}


def _local(tag: object) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _contexts(root: etree._Element) -> dict[str, tuple[str | None, str | None, bool]]:
    """context id -> (start, end, has_dimensions) for duration contexts."""
    out: dict[str, tuple[str | None, str | None, bool]] = {}
    for ctx in root.iter():
        if _local(ctx.tag) != "context":
            continue
        start = end = None
        dims = False
        for el in ctx.iter():
            name = _local(el.tag)
            if name == "startDate":
                start = (el.text or "").strip()
            elif name == "endDate":
                end = (el.text or "").strip()
            elif name == "scenario":
                dims = True
        if start and end:
            out[ctx.get("id", "")] = (start, end, dims)
    return out


def _pick_context(ctxs: dict, start: str | None, end: str | None, has_oned: bool = False) -> str:
    plain = {k: v for k, v in ctxs.items() if not v[2]}
    matching = [
        k for k, v in plain.items() if (end is None or v[1] == end) and (start is None or v[0] == start)
    ]
    if not matching and end is not None:
        matching = [k for k, v in plain.items() if v[1] == end]  # filing's start date may differ
    if not matching and has_oned and "OneD" not in ctxs:
        return "OneD"  # old NSE files never declare it; a declared OneD with other dates is a mismatch
    if not matching:
        raise XbrlError("no context matches the period")
    return "OneD" if "OneD" in matching else matching[0]


def parse_xbrl(content: bytes, period_start: str | None, period_end: str | None) -> dict:
    """-> {revenue, other_income, total_expenses, pbt, net_profit, eps} (₹ crore; eps in ₹)."""
    try:
        parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
        root = etree.fromstring(content, parser)
    except (etree.XMLSyntaxError, ValueError) as e:
        raise XbrlError(f"not valid XML: {e}") from None
    if root is None:
        raise XbrlError("empty document")
    has_oned = any(el.get("contextRef") == "OneD" for el in root.iter())
    ctx_id = _pick_context(_contexts(root), period_start, period_end, has_oned)
    facts: dict[str, float] = {}
    for el in root.iter():
        if el.get("contextRef") == ctx_id and el.text:
            try:
                facts.setdefault(_local(el.tag), float(el.text))
            except ValueError:
                continue
    out: dict[str, float | None] = {}
    for key, names in _CANDIDATES.items():
        v = next((facts[n] for n in names if n in facts), None)
        out[key] = v if v is None or key in _PER_SHARE else round(v / CRORE, 2)
    if out["revenue"] is None and out["net_profit"] is None:
        raise XbrlError("neither revenue nor net profit found")
    return out
