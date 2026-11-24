import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app import config, db
from app.analytics import custom_indicators
from app.jobs import runner, scheduler
from app.plugins import import_all
from app.sources.jobs import register_source_jobs

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    runner.recover_on_startup()
    import_all("app.sources.adapters")
    import_all("app.jobs.defs")
    register_source_jobs()
    import_all("app.alerts.scanners")
    import_all("app.ai.providers")
    import_all("app.ai.tasks")
    custom_indicators.load_approved()
    if os.environ.get("STOCK_NO_THREADS") != "1":
        runner.start_worker()
    scheduler.startup()
    log.info("started")
    yield


app = FastAPI(title="stock-tools", lifespan=lifespan)

for _mod in import_all("app.api"):
    _router = getattr(_mod, "router", None)
    if isinstance(_router, APIRouter):
        app.include_router(_router, prefix="/api")

_dist = Path(config.ROOT) / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path == "api" or path.startswith("api/"):
        return PlainTextResponse("Not found", status_code=404)
    index = _dist / "index.html"
    if index.is_file():
        return FileResponse(index)
    return PlainTextResponse("Frontend not built: run ./start.sh")
