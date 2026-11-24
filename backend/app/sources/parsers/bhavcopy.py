"""NSE bhavcopy parsing (SPEC §7.1). Pure functions: bytes in, Bars out."""

import csv
import io
import logging
import zipfile
from datetime import date

from app.sources.base import Bar, SourceError

log = logging.getLogger(__name__)

UDIFF_START = date(2024, 7, 8)
EQUITY_SERIES = ("EQ", "BE", "BZ", "RR", "IV")
_BASE = "https://nsearchives.nseindia.com/content"
_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def bhav_url(d: date) -> str:
    if d >= UDIFF_START:
        return f"{_BASE}/cm/BhavCopy_NSE_CM_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"
    mon = _MONTHS[d.month - 1]
    return f"{_BASE}/historical/EQUITIES/{d.year}/{mon}/cm{d.day:02d}{mon}{d.year}bhav.csv.zip"


def _unzip(content: bytes) -> bytes:
    if not content.startswith(b"PK\x03\x04"):
        return content
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            return z.read(z.namelist()[0])
    except (zipfile.BadZipFile, IndexError) as e:
        raise SourceError(f"bad bhavcopy zip: {e}") from e


def _num(v: str | None) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def parse_bhav(content: bytes, d: date) -> list[Bar]:
    """Zip or CSV bytes -> EQ/BE/BZ-series bars dated `d`. Format is detected from the header."""
    try:
        text = _unzip(content).decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise SourceError(f"bhavcopy is not text: {e}") from e
    reader = csv.DictReader(io.StringIO(text))
    cols = {(c or "").strip() for c in (reader.fieldnames or [])}
    if "TckrSymb" in cols:
        fmt = (
            "TckrSymb", "OpnPric", "HghPric", "LwPric", "ClsPric",
            "TtlTradgVol", "TtlTrfVal", "TtlNbOfTxsExctd",
        )  # fmt: skip
        series_col = "SctySrs"
    elif "SYMBOL" in cols:
        fmt = ("SYMBOL", "OPEN", "HIGH", "LOW", "CLOSE", "TOTTRDQTY", "TOTTRDVAL", "TOTALTRADES")
        series_col = "SERIES"
    else:
        raise SourceError("unrecognised bhavcopy header")
    sym_c, o_c, h_c, l_c, c_c, v_c, val_c, t_c = fmt
    bars: dict[str, Bar] = {}
    dropped = 0
    for raw in reader:
        row = {(k or "").strip(): (v or "").strip() for k, v in raw.items() if k is not None}
        if row.get(series_col) not in EQUITY_SERIES:
            continue
        if series_col == "SctySrs" and row.get("FinInstrmTp") != "STK":
            continue
        o, h, lo, c = (_num(row.get(k)) for k in (o_c, h_c, l_c, c_c))
        if None in (o, h, lo, c) or not row.get(sym_c):
            dropped += 1
            continue
        trades = _num(row.get(t_c))
        sym = row[sym_c].upper()
        if sym in bars and row[series_col] != "EQ":
            continue  # one bar per symbol; the EQ row wins
        bars[sym] = Bar(
            sym, d.isoformat(), o, h, lo, c,
            _num(row.get(v_c)), _num(row.get(val_c)), int(trades) if trades is not None else None,
            row[series_col] or None, row.get("ISIN") or None,
        )  # fmt: skip
    if dropped:
        log.warning("bhavcopy %s: dropped %d rows with missing prices", d, dropped)
    return list(bars.values())
