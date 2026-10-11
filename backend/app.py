"""Application entry point.

The FastAPI application lives in :mod:`backend.api.routes`; this module simply
re-exports it so both of the documented launch commands work::

    uvicorn backend.app:app --reload
    uvicorn backend.api.routes:app --reload
"""

from __future__ import annotations

from backend.api.routes import app, create_app

__all__ = ["app", "create_app"]

if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run("backend.app:app", host="127.0.0.1", port=8000, reload=True)
