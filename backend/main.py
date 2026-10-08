"""Entry point: `uvicorn main:app`.

The application is built in app/bootstrap.py. Everything it is made of lives in the app package; this file only
exposes it - and, for the test suite and one-off scripts, lets `main.<name>` find a name wherever it now lives.
"""
import os
import sys

from app.bootstrap import app  # noqa: F401
from app import db as database, models  # noqa: F401  (tests and scripts say main.models, main.database)

_INDEX = None


def _index():
    """name -> the object, for every top-level name in the app package (the module that defines it wins)."""
    global _INDEX
    if _INDEX is None:
        found, defined = {}, {}
        for modname in sorted(m for m in sys.modules if m == "app" or m.startswith("app.")):
            for name, value in list(vars(sys.modules[modname]).items()):
                if name.startswith("__") or name in ("router",):
                    continue
                if getattr(value, "__name__", "").startswith("app.") and type(value).__name__ == "module":
                    continue            # the app's own sub-modules (core.oauth) are not what `main.oauth` means
                home = getattr(value, "__module__", None)
                if home == modname:
                    defined.setdefault(name, value)
                found.setdefault(name, value)
        found.update(defined)
        _INDEX = found
    return _INDEX


def __getattr__(name):
    try:
        return _index()[name]
    except KeyError:
        raise AttributeError("module 'main' has no attribute %r" % name) from None


if __name__ == "__main__":
    import uvicorn
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host=host, port=port, reload=False)
