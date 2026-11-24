import importlib.util
import sqlite3
from pathlib import Path

_p = Path(__file__).resolve().parents[2] / "scripts" / "reparse_actions.py"
_spec = importlib.util.spec_from_file_location("reparse_actions", _p)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def test_find_changes():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE corp_actions "
        "(source TEXT, symbol TEXT, ex_date TEXT, subject TEXT, kind TEXT, factor REAL)"
    )
    sub = "Bonus 1:1 / Face Value Split From Rs.10/- To Re.1/-"
    conn.executemany(
        "INSERT INTO corp_actions VALUES (?,?,?,?,?,?)",
        [
            ("nse_api", "TITAN", "2011-01-01", sub, "split", 0.1),  # old parse: wrong
            ("nse_api", "ABC", "2020-01-01", "Bonus 1:1", "bonus", 0.5),  # already right
            ("yfinance", "TITAN", "2011-01-01", sub, "split", 0.1),  # other source: untouched
        ],
    )
    ch = mod.find_changes(conn)
    assert len(ch) == 1
    assert ch[0]["symbol"] == "TITAN"
    assert ch[0]["new_kind"] == "split"
    assert round(ch[0]["new_factor"], 4) == 0.05
