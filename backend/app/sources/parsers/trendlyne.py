"""Trendlyne research-report list parsing. Pure functions: bytes in, ResearchReport list out.

The page is a server-rendered table. Columns are found by their header text, so a reordered table
still parses and a renamed column fails loudly instead of filling the wrong field.
"""

from __future__ import annotations

import re
from datetime import datetime
from html.parser import HTMLParser

from app.sources.base import ResearchReport

TABLE_ID = "brokerTable"
WANTED_TYPES = {"buy": "Buy", "sell": "Sell"}
# our key -> start of the header text
COLUMNS = {
    "date": "date",
    "stock": "stock",
    "author": "author",
    "ltp": "ltp",
    "target": "target",
    "reco": "price at reco",
    "upside": "upside",
    "type": "type",
}
_SYMBOL = re.compile(r"/research-reports/stock/\d+/([^/]+)/")
_POST = re.compile(r"/posts/(\d+)/")
_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


class _Cell:
    def __init__(self) -> None:
        self.text: list[str] = []
        self.links: list[tuple[str, str]] = []  # (href, link text)
        self._href: str | None = None
        self._link: list[str] = []

    def value(self) -> str:
        return " ".join("".join(self.text).split())


class _TableParser(HTMLParser):
    """Collects the header texts and, per body row, its cells and every report post id."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found = False
        self.headers: list[str] = []
        self.rows: list[tuple[list[_Cell], list[str]]] = []
        self._inside = False
        self._header: list[str] | None = None
        self._cell: _Cell | None = None
        self._script = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "table" and a.get("id") == TABLE_ID:
            self.found = self._inside = True
        if not self._inside:
            return
        if tag == "th":
            self._header = []
        elif tag == "tr" and "Ltop" in (a.get("class") or "").split():
            self.rows.append(([], []))
        elif tag == "td" and self.rows:
            self._cell = _Cell()
            self.rows[-1][0].append(self._cell)
        elif tag in ("script", "style"):
            self._script = True
        elif tag == "br":
            self._add(" ")
        elif tag == "a":
            href = a.get("href") or ""
            if self.rows and (m := _POST.search(href)):
                self.rows[-1][1].append(m[1])
            if self._cell is not None:
                self._cell._href, self._cell._link = href, []

    def handle_endtag(self, tag: str) -> None:
        if not self._inside:
            return
        if tag == "table":
            self._inside = False
        elif tag == "th" and self._header is not None:
            self.headers.append(" ".join("".join(self._header).split()).lower())
            self._header = None
        elif tag == "td":
            self._cell = None
        elif tag in ("script", "style"):
            self._script = False
        elif tag == "a" and self._cell is not None and self._cell._href is not None:
            self._cell.links.append((self._cell._href, " ".join("".join(self._cell._link).split())))
            self._cell._href = None

    def handle_data(self, data: str) -> None:
        if self._inside and not self._script:
            self._add(data)

    def _add(self, data: str) -> None:
        if self._header is not None:
            self._header.append(data)
        elif self._cell is not None:
            self._cell.text.append(data)
            if self._cell._href is not None:
                self._cell._link.append(data)


def _numbers(text: str) -> list[float]:
    return [float(n.replace(",", "")) for n in _NUMBER.findall(text)]


def _first(text: str) -> float | None:
    found = _numbers(text)
    return found[0] if found else None


def _column_indexes(headers: list[str]) -> dict[str, int]:
    out = {}
    for key, start in COLUMNS.items():
        index = next((i for i, h in enumerate(headers) if h.startswith(start)), None)
        if index is None:
            raise ValueError(f"research table has no '{start}' column")
        out[key] = index
    return out


def _report(cells: list[_Cell], post_id: str, at: dict[str, int]) -> ResearchReport | None:
    kind = WANTED_TYPES.get(cells[at["type"]].value().lower())
    if kind is None:
        return None
    stock_cell, author_cell = cells[at["stock"]], cells[at["author"]]
    stock_link = next(((h, t) for h, t in stock_cell.links if _SYMBOL.search(h)), None)
    symbol = _SYMBOL.search(stock_link[0])[1].upper() if stock_link else None
    # The author cell also holds "Reco"/"Target" upgrade badges: keep only the broker's name.
    author = next((t for h, t in author_cell.links if "/broker/" in h), author_cell.value())
    reco = _numbers(cells[at["reco"]].value())  # "1832.10 (-1.93%)"; no bracket when unchanged
    ltp = _first(cells[at["ltp"]].value())
    change = reco[1] if len(reco) > 1 else None
    if change is None and reco and ltp == reco[0]:
        change = 0.0
    return ResearchReport(
        report_id=post_id,
        date=datetime.strptime(cells[at["date"]].value().title(), "%d %b %Y").date().isoformat(),
        stock=stock_link[1] if stock_link else stock_cell.value(),
        author=author,
        type=kind,  # type: ignore[arg-type]
        symbol=symbol,
        ltp=ltp,
        target=_first(cells[at["target"]].value()),
        reco_price=reco[0] if reco else None,
        change_pct=change,
        upside_pct=_first(cells[at["upside"]].value()),
        url=f"https://trendlyne.com/posts/{post_id}/",
    )


def parse_research_page(content: bytes) -> tuple[int, list[ResearchReport]]:
    """(rows of any type on the page, the Buy and Sell reports). ValueError if the layout changed."""
    parser = _TableParser()
    parser.feed(content.decode("utf-8", errors="replace"))
    parser.close()
    if not parser.found:
        raise ValueError("research table not found on the page")
    at = _column_indexes(parser.headers)
    out = []
    for cells, posts in parser.rows:
        if len(cells) <= max(at.values()) or not posts:
            raise ValueError("research table row has an unexpected shape")
        report = _report(cells, posts[0], at)
        if report:
            out.append(report)
    return len(parser.rows), out
