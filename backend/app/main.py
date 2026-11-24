import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app import bootstrap, config, db
from app.cloud import auth
from app.jobs import runner, scheduler
from app.plugins import import_all

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if config.RUNTIME == "vercel":  # no migrations, no threads: jobs run in the drain (§17.2)
        bootstrap.load_plugins()
        log.info("started (vercel)")
        yield
        return
    db.init_db()
    runner.recover_on_startup()
    bootstrap.load_plugins()
    if os.environ.get("STOCK_NO_THREADS") != "1":
        runner.start_worker()
    scheduler.startup()
    log.info("started")
    yield


app = FastAPI(title="stock-tools", lifespan=lifespan)
auth.install(app)

for _mod in import_all("app.api"):
    _router = getattr(_mod, "router", None)
    if isinstance(_router, APIRouter):
        app.include_router(_router, prefix="/api")

_dist = Path(config.ROOT) / "frontend" / "dist"


def _mount_frontend(app: FastAPI) -> None:
    """Serve the React build and the SPA fallback (local mode only; Vercel serves them itself, §17.5)."""
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


if config.RUNTIME != "vercel":
    _mount_frontend(app)
