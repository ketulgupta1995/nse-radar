"""Parsers for NSE list files (pure functions: bytes in, records out)."""

import csv
import io
import logging
from datetime import date, datetime

from app.sources.base import SourceError, SymbolChange, SymbolRow

log = logging.getLogger(__name__)

SYMBOL_CHANGE_COLUMNS = ("name of the company", "old symbol", "new symbol", "effective date")


def parse_symbol_changes(csv_bytes: bytes) -> list[SymbolChange]:
    """Parse symbolchange.csv (NAME OF THE COMPANY, OLD SYMBOL, NEW SYMBOL, EFFECTIVE DATE)."""
    try:
        reader = csv.reader(io.StringIO(csv_bytes.decode("utf-8-sig")))
        header = next(reader, None)
        names = [(h or "").strip().lower() for h in header or []]
        if not all(c in names for c in SYMBOL_CHANGE_COLUMNS):
            raise SourceError("ticker change list has unrecognised columns")
        i_name, i_old, i_new, i_date = (names.index(c) for c in SYMBOL_CHANGE_COLUMNS)
        out: list[SymbolChange] = []
        skipped = 0
        for row in reader:
            if not any(cell.strip() for cell in row):
                continue
            cells = [c.strip() for c in row] + [""] * (len(names) - len(row))
            old, new = cells[i_old].upper(), cells[i_new].upper()
            try:
                eff = datetime.strptime(cells[i_date].title(), "%d-%b-%Y").date().isoformat()
            except ValueError:
                skipped += 1
                continue
            if not old or not new or old == new or not cells[i_name]:
                skipped += 1
                continue
            out.append(SymbolChange(old, new, eff, cells[i_name]))
    except (UnicodeDecodeError, csv.Error) as e:
        raise SourceError(f"unreadable ticker change list: {e}") from e
    if skipped:
        log.warning("ticker change list: skipped %d unusable rows", skipped)
    return out


def parse_nifty500(csv_bytes: bytes) -> list[SymbolRow]:
    """Parse ind_nifty500list.csv (Company Name, Industry, Symbol, Series, ISIN Code)."""
    try:
        reader = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8-sig")))
        rows = []
        for r in reader:
            sym = (r.get("Symbol") or "").strip().upper()
            isin = (r.get("ISIN Code") or "").strip().upper()
            if not sym or sym.startswith("DUMMY") or isin.startswith("DUM"):
                continue  # NSE's placeholder rows (e.g. "Dummy HEG Ltd.") are not tradable stocks
            rows.append(
                SymbolRow(
                    sym,
                    (r.get("Company Name") or "").strip() or sym,
                    (r.get("Industry") or "").strip() or None,
                    (r.get("ISIN Code") or "").strip() or None,
                )
            )
    except (UnicodeDecodeError, csv.Error) as e:
        raise SourceError(f"unreadable Nifty 500 list: {e}") from e
    if not rows:
        raise SourceError("Nifty 500 list had no rows (columns changed?)")
    return rows


def index_close_url(d: date) -> str:
    return f"https://nsearchives.nseindia.com/content/indices/ind_close_all_{d:%d%m%Y}.csv"


def parse_index_close(csv_bytes: bytes, index_name: str) -> float | None:
    """Closing value of `index_name` (case-insensitive) from ind_close_all_*.csv, else None."""
    try:
        reader = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8-sig")))
        for r in reader:
            if (r.get("Index Name") or "").strip().lower() == index_name.strip().lower():
                try:
                    return float((r.get("Closing Index Value") or "").replace(",", ""))
                except ValueError:
                    return None
    except (UnicodeDecodeError, csv.Error) as e:
        raise SourceError(f"unreadable index close file: {e}") from e
    return None
