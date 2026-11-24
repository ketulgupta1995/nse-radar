import logging
import time
from typing import Literal

from app import db, timeutil

MAX_MSG = 4000
SYNC_EVERY_S = 15.0  # replica: how often a running job pulls the primary's writes to see a stop request


class StopRequested(Exception):
    pass


class JobContext:
    def __init__(self, run_id: int, params: dict, job_name: str = "job"):
        self.run_id = run_id
        self.params = params
        self._logger = logging.getLogger(f"jobs.{job_name}")
        self._last_check: float | None = None
        self._stop = False

    def set_total(self, n: int) -> None:
        with db.tx() as c:
            c.execute("UPDATE job_runs SET total=? WHERE id=?", (n, self.run_id))

    def item(self, key: str, status: Literal["ok", "skipped", "failed"], detail: str | None = None) -> None:
        with db.tx() as c:
            c.execute(
                "INSERT INTO job_items(run_id, key, status, detail, at) VALUES (?,?,?,?,?) "
                "ON CONFLICT(run_id, key) DO UPDATE SET status=excluded.status, "
                "detail=excluded.detail, at=excluded.at",
                (self.run_id, key, status, detail, timeutil.now_iso()),
            )
            c.execute(
                "UPDATE job_runs SET "
                "ok=(SELECT COUNT(*) FROM job_items WHERE run_id=? AND status='ok'), "
                "skipped=(SELECT COUNT(*) FROM job_items WHERE run_id=? AND status='skipped'), "
                "failed=(SELECT COUNT(*) FROM job_items WHERE run_id=? AND status='failed'), "
                "done=(SELECT COUNT(*) FROM job_items WHERE run_id=?) WHERE id=?",
                (self.run_id,) * 5,
            )

    def log(self, msg: str, level: Literal["info", "warn", "error"] = "info") -> None:
        msg = msg[:MAX_MSG]
        with db.tx() as c:
            c.execute(
                "INSERT INTO job_logs(run_id, at, level, msg) VALUES (?,?,?,?)",
                (self.run_id, timeutil.now_iso(), level, msg),
            )
        self._logger.log({"info": logging.INFO, "warn": logging.WARNING, "error": logging.ERROR}[level], msg)

    def stop_requested(self) -> bool:
        if self._stop:
            return True
        t = time.monotonic()
        if self._last_check is None or t - self._last_check >= 1.0:
            self._last_check = t
            db.sync_if_due(SYNC_EVERY_S)  # replica: a stop asked for on the site arrives through a sync
            with db.tx() as c:
                row = c.execute("SELECT stop_requested FROM job_runs WHERE id=?", (self.run_id,)).fetchone()
            self._stop = bool(row and row["stop_requested"])
        return self._stop

    def check_stop(self) -> None:
        if self.stop_requested():
            raise StopRequested()
