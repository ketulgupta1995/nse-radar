"""Alert scanner registry (SPEC §13.2). A new alert kind is one module in `alerts/scanners/`."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class AlertDraft:
    kind: str
    message: str
    dedupe_key: str
    symbol: str | None = None
    link: str | None = None
    severity: str = "info"


@dataclass(frozen=True)
class AlertScanner:
    kind: str
    label: str
    fn: Callable[[sqlite3.Connection, datetime], list[AlertDraft]]


_SCANNERS: dict[str, AlertScanner] = {}


def register(s: AlertScanner) -> AlertScanner:
    if s.kind in _SCANNERS:
        raise ValueError(f"duplicate alert kind: {s.kind}")
    _SCANNERS[s.kind] = s
    return s


def unregister(kind: str) -> None:
    """Tests only."""
    _SCANNERS.pop(kind, None)


def all_scanners() -> list[AlertScanner]:
    return list(_SCANNERS.values())


def inr(value: float) -> str:
    """₹3,412 or ₹3,412.50."""
    return f"₹{value:,.0f}" if float(value).is_integer() else f"₹{value:,.2f}"


def day_name(iso: str) -> str:
    """'2026-11-04' -> 'Tue 4 Nov'."""
    d = datetime.fromisoformat(iso)
    return f"{d:%a} {d.day} {d:%b}"
