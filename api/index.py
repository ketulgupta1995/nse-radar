"""Vercel entry point: the FastAPI app as one Python function (SPEC §17.5). No uvicorn."""

import os
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

os.environ.setdefault("STOCK_RUNTIME", "vercel")

from app.main import app  # noqa: E402

__all__ = ["app"]
