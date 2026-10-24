"""API routes package.

Re-exports the FastAPI app and router so existing imports like
``from backend.api.routes import app, create_app`` continue to work without
changes.  New submodules (Lab, SDK v1) are mounted alongside the legacy
routes.
"""

from __future__ import annotations

# Import shared infrastructure from the legacy module.
from backend.api.routes._legacy import RuntimeManager, _api_router

# Import new route modules.
from backend.api.routes._lab import router as lab_router
from backend.api.routes._sdk_v1 import router as sdk_v1_router


def create_app(settings=None, runtime=None):
    """Create the full FastAPI application with all route modules mounted."""
    from fastapi import APIRouter, FastAPI, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse

    from backend.api.middleware import BodySizeLimitMiddleware
    from backend.config import Settings, get_settings
    from backend.security import build_default_redactor

    settings = settings or get_settings()
    if not isinstance(settings, Settings):
        settings = Settings.from_env()

    app = FastAPI(
        title="AI Agent Failure Memory",
        version="0.1.0",
        description=(
            "Failure -> Cause -> Lesson -> Future Prevention memory for AI agents. "
            "Offline and deterministic by default."
        ),
    )

    # Middleware — CORS must be outermost.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_body_bytes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Shared state.
    app.state.settings = settings
    app.state.redactor = build_default_redactor(settings)
    app.state.runtime_manager = RuntimeManager(settings, runtime)

    @app.get("/")
    def root() -> dict:
        return {
            "name": "AI Agent Failure Memory",
            "version": "0.1.0",
            "docs": "/docs",
            "api": "/api",
        }

    import sqlite3

    @app.exception_handler(ValueError)
    async def _value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(sqlite3.Error)
    async def _sqlite_handler(request: Request, exc: sqlite3.Error) -> JSONResponse:
        import logging

        logger = logging.getLogger("failure_memory.api")
        logger.warning(
            "Storage error while handling %s: %s", request.url.path, type(exc).__name__
        )
        return JSONResponse(
            status_code=503,
            content={"detail": "failure-memory storage is temporarily unavailable"},
        )

    @app.exception_handler(RecursionError)
    async def _recursion_handler(request: Request, exc: RecursionError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"detail": "request body is too deeply nested"},
        )

    # Mount all routers.
    app.include_router(_api_router)       # /api/*  (legacy routes)
    app.include_router(lab_router)        # /lab/*  (Replay Lab)
    app.include_router(sdk_v1_router)     # /v1/sdk/* (SDK v1)

    return app


# Module-level app instance for convenience.
app = create_app()

__all__ = ["app", "create_app", "RuntimeManager"]
