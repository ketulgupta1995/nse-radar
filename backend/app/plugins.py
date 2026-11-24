import importlib
import logging
import pkgutil
from types import ModuleType

log = logging.getLogger(__name__)


def import_all(package: str) -> list[ModuleType]:
    """Import every non-underscore module in `package`, sorted by name (SPEC §2.4).

    A package that doesn't exist yet (e.g. alerts/ai before their tickets) is skipped quietly.
    A module whose third-party library isn't installed (e.g. yfinance on the phone, SPEC §17.2)
    is skipped with a warning, so the rest of the app still starts.
    """
    try:
        pkg = importlib.import_module(package)
    except ModuleNotFoundError as e:
        if e.name and (package == e.name or package.startswith(e.name + ".")):
            return []
        raise
    names = sorted(m.name for m in pkgutil.iter_modules(pkg.__path__) if not m.name.startswith("_"))
    mods = []
    for n in names:
        try:
            mods.append(importlib.import_module(f"{package}.{n}"))
        except ModuleNotFoundError as e:
            if not e.name or e.name == "app" or e.name.startswith("app."):
                raise
            log.warning("skipped plugin %s.%s: library %r is not installed", package, n, e.name)
    return mods
