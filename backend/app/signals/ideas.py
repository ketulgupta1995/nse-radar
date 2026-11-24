"""Group repeat loggings of a stock into ideas (SPEC §16.7).

A stock is logged again when another screen picks it up, or when it leaves a screen and comes back.
While the first logging (the anchor) is still being followed, those later loggings are the same trade:
they join the anchor's idea as context and never change its outcome.
"""

from __future__ import annotations

import json
from typing import Any


def _joins(anchor: dict, as_of: str) -> bool:
    """A logging joins the current idea while the anchor isn't closed, or before its exit date."""
    if anchor.get("status") != "closed":
        return True
    exit_date = anchor.get("exit_date")
    return exit_date is None or as_of < exit_date


def group_ideas(sigs: list[dict]) -> list[dict]:
    """-> [{"anchor": logging, "members": [loggings oldest first]}], in anchor (as_of, id) order."""
    ordered = sorted(sigs, key=lambda s: (s["symbol"], s["as_of"], s["id"]))
    ideas: list[dict] = []
    current: dict[str, dict] = {}
    for s in ordered:
        idea = current.get(s["symbol"])
        if idea is not None and _joins(idea["anchor"], s["as_of"]):
            idea["members"].append(s)
            continue
        idea = {"anchor": s, "members": [s]}
        current[s["symbol"]] = idea
        ideas.append(idea)
    ideas.sort(key=lambda i: (i["anchor"]["as_of"], i["anchor"]["id"]))
    return ideas


def _reasons(raw: Any) -> list:
    if isinstance(raw, list):
        return raw
    try:
        v = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return v if isinstance(v, list) else []


def merged_reasons(members: list[dict]) -> list:
    """All members' reasons in first-seen order, without duplicates."""
    out: list = []
    seen: set[str] = set()
    for m in members:
        for r in _reasons(m.get("reasons")):
            key = json.dumps(r, sort_keys=True)
            if key not in seen:
                seen.add(key)
                out.append(r)
    return out


def best_score(members: list[dict]) -> float | None:
    scores = [m["score"] for m in members if m.get("score") is not None]
    return max(scores) if scores else None


def best_rank(members: list[dict]) -> int | None:
    ranks = [m["rank"] for m in members if m.get("source") == "shortlist" and m.get("rank") is not None]
    return min(ranks) if ranks else None
