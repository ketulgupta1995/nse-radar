"""Shared helper for AI tasks that expect a JSON object in the reply."""

from __future__ import annotations

import json


def extract_json(text: str) -> dict | None:
    """The first JSON object found in `text`, or None."""
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = dec.raw_decode(text, i)
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    return None
