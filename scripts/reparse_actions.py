"""Re-apply the NSE action-subject parser to stored corp_actions rows (source='nse_api').

Usage: backend/.venv/bin/python scripts/reparse_actions.py [--apply]
Without --apply it only prints the rows that would change.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app import db
from app.sources.parsers.actions import parse_action_subject


def _same(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is b
    return abs(a - b) < 1e-9


def find_changes(conn: sqlite3.Connection) -> list[dict]:
    """Rows of source 'nse_api' whose (kind, factor) differ from what the parser gives now."""
    out = []
    rows = conn.execute(
        "SELECT symbol, ex_date, subject, kind, factor FROM corp_actions "
        "WHERE source='nse_api' ORDER BY symbol, ex_date"
    ).fetchall()
    for r in rows:
        kind, factor = parse_action_subject(r["subject"])
        if kind != r["kind"] or not _same(factor, r["factor"]):
            out.append({**dict(r), "new_kind": kind, "new_factor": factor})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write the changes (default: only print)")
    args = ap.parse_args()
    with db.tx() as conn:
        changes = find_changes(conn)
        for c in changes:
            print(
                f"{c['symbol']} {c['ex_date']} {c['kind']} {c['factor']} -> "
                f"{c['new_kind']} {c['new_factor']} {c['subject'][:70]}"
            )
        if args.apply:
            for c in changes:
                conn.execute(
                    "UPDATE corp_actions SET kind=?, factor=? "
                    "WHERE source='nse_api' AND symbol=? AND ex_date=? AND subject=?",
                    (c["new_kind"], c["new_factor"], c["symbol"], c["ex_date"], c["subject"]),
                )
    print(f"{len(changes)} row(s) {'updated' if args.apply else 'would change (use --apply)'}")


if __name__ == "__main__":
    main()
