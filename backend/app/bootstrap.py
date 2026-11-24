"""Plug-in loading shared by the web app (`main.lifespan`) and the drain CLI (SPEC §2.4, §17.3)."""

from app import config
from app.analytics import custom_indicators
from app.plugins import import_all
from app.sources.jobs import register_source_jobs


def load_plugins() -> None:
    """Import every plug-in package and register source jobs.

    Approved custom indicators are loaded everywhere except Vercel, where they never run (§17.2).
    """
    import_all("app.sources.adapters")
    import_all("app.jobs.defs")
    register_source_jobs()
    import_all("app.alerts.scanners")
    import_all("app.ai.providers")
    import_all("app.ai.tasks")
    if config.RUNTIME != "vercel":
        custom_indicators.load_approved()
