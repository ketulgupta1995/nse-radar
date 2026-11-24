"""Parse a Screener.in company page into plain data, then into §9.4 fields (SPEC §9.2).

Pure functions: bytes in, dicts out. Missing sections are listed in `missing`, never raised.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

_SECTIONS = {
    "quarters": "quarters",
    "profit_loss": "profit-loss",
    "balance_sheet": "balance-sheet",
    "ratios_hist": "ratios",
    "shareholding": "shareholding",
}
_RATIO_KEYS = {
    "Market Cap": "market_cap",
    "Current Price": "price",
    "Stock P/E": "pe",
    "Book Value": "book_value",
    "Dividend Yield": "dividend_yield",
    "ROCE": "roce",
    "ROE": "roe",
    "Face Value": "face_value",
}
_GROWTH_BLOCKS = {
    "Compounded Sales Growth": "sales_cagr",
    "Compounded Profit Growth": "profit_cagr",
    "Return on Equity": "roe",
}
_PERIODS = {"10 Years": "10y", "5 Years": "5y", "3 Years": "3y", "TTM": "ttm", "Last Year": "ttm"}


def _to_float(text: str | None) -> float | None:
    if text is None:
        return None
    t = re.sub(r"[₹%,+\s]|Cr\.", "", text)
    if t in ("", "-", "—"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _clean_label(text: str) -> str:
    return re.sub(r"[\s+ ]+$", "", text.strip()).strip()


def _table(section: Tag | None) -> dict | None:
    """First `table.data-table` of a section as {periods, rows: {label: [float|None]}}."""
    table = section.select_one("table.data-table") if section else None
    if table is None:
        return None
    periods = [th.get_text(strip=True) for th in table.select("thead th")][1:]
    rows: dict[str, list[float | None]] = {}
    for tr in table.select("tbody tr"):
        cells = tr.find_all(["th", "td"])
        if len(cells) < 2:
            continue
        label = _clean_label(cells[0].get_text(" ", strip=True))
        values = [_to_float(c.get_text(" ", strip=True)) for c in cells[1:]]
        if label and len(values) == len(periods):
            rows[label] = values
    if not periods or not any(v is not None for vals in rows.values() for v in vals):
        return None
    return {"periods": periods, "rows": rows}


def _growth(section: Tag | None) -> dict:
    out: dict[str, dict] = {"sales_cagr": {}, "profit_cagr": {}, "roe": {}}
    if section is None:
        return out
    for block in section.select("table.ranges-table"):
        rows = [r.get_text(" ", strip=True) for r in block.select("tr")]
        key = _GROWTH_BLOCKS.get(rows[0].strip()) if rows else None
        if key is None:
            continue
        for line in rows[1:]:
            label, _, val = line.partition(":")
            if label.strip() in _PERIODS:
                out[key][_PERIODS[label.strip()]] = _to_float(val)
    return out


def parse_company_page(html: bytes) -> dict:
    soup = BeautifulSoup(html, "lxml")
    missing: list[str] = []
    ratios: dict[str, float | None] = {}
    for li in soup.select("#top-ratios li"):
        name = li.select_one(".name")
        value = li.select_one(".number")
        label = _clean_label(name.get_text(" ", strip=True)) if name else ""
        if label in _RATIO_KEYS and value is not None:
            ratios[_RATIO_KEYS[label]] = _to_float(value.get_text(strip=True))
    if not ratios:
        missing.append("ratios")
    out: dict = {"ratios": ratios}
    for key, sec_id in _SECTIONS.items():
        section = soup.select_one(f"section#{sec_id}")
        if key == "shareholding" and section is not None:
            section = section.select_one("#quarterly-shp") or section
        parsed = _table(section)
        if parsed is None:
            missing.append(key)
        out[key] = parsed or {"periods": [], "rows": {}}
    out["growth"] = _growth(soup.select_one("section#profit-loss"))
    if not any(out["growth"]["sales_cagr"].values()):
        missing.append("growth")
    out["missing"] = missing
    return out


# ---- §9.4 fields ----------------------------------------------------------------------------


def _row(parsed: dict, section: str, label: str) -> list[float | None]:
    return parsed.get(section, {}).get("rows", {}).get(label, [])


def _last(values: list[float | None]) -> float | None:
    return next((v for v in reversed(values) if v is not None), None)


def _at(values: list[float | None], i: int) -> float | None:
    return values[i] if len(values) >= abs(i) else None


def _yoy(values: list[float | None]) -> float | None:
    now, then = _at(values, -1), _at(values, -5)
    if now is None or then is None or then <= 0:
        return None
    return round((now / then - 1) * 100, 2)


def to_fields(parsed: dict) -> dict:
    r = parsed.get("ratios", {})
    g = parsed.get("growth", {})
    f: dict[str, float | None] = {
        "market_cap_cr": r.get("market_cap"),
        "pe": r.get("pe"),
        "roce_pct": r.get("roce"),
        "roe_pct": r.get("roe"),
        "dividend_yield_pct": r.get("dividend_yield"),
        "pb": None,
        "debt_to_equity": None,
        "sales_growth_3y_pct": g.get("sales_cagr", {}).get("3y"),
        "profit_growth_3y_pct": g.get("profit_cagr", {}).get("3y"),
        "sales_growth_yoy_pct": _yoy(_row(parsed, "quarters", "Sales")),
        "profit_growth_yoy_pct": _yoy(_row(parsed, "quarters", "Net Profit")),
        "profit_positive_4q": None,
        "promoter_pct": None,
        "promoter_change_1y_pp": None,
    }
    price, book = r.get("price"), r.get("book_value")
    if price is not None and book:
        f["pb"] = round(price / book, 2)
    borrow = _last(_row(parsed, "balance_sheet", "Borrowings"))
    equity = (_last(_row(parsed, "balance_sheet", "Equity Capital")) or 0) + (
        _last(_row(parsed, "balance_sheet", "Reserves")) or 0
    )
    if borrow is not None and equity > 0:
        f["debt_to_equity"] = round(borrow / equity, 3)
    profits = _row(parsed, "quarters", "Net Profit")[-4:]
    if len(profits) == 4 and all(p is not None for p in profits):
        f["profit_positive_4q"] = 1.0 if all(p > 0 for p in profits) else 0.0  # type: ignore[operator]
    promoters = _row(parsed, "shareholding", "Promoters")
    f["promoter_pct"] = _last(promoters)
    now, then = _at(promoters, -1), _at(promoters, -5)
    if now is not None and then is not None:
        f["promoter_change_1y_pp"] = round(now - then, 2)
    return f
