"""Shared pytest fixtures.

Every fixture uses an isolated SQLite database (``:memory:``) so tests never
touch the developer's real ``data/memory.db``.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from backend.config import Settings
from backend.memory.store import MemoryStore
from backend.services import Runtime, build_runtime


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        memory_database=":memory:",
        embedding_provider="hashing",
        llm_provider="deterministic",
        default_max_attempts=2,
        llm_benchmark_output_dir=str(tmp_path / "llm_benchmarks"),
    )


@pytest.fixture
def store() -> Iterator[MemoryStore]:
    memory_store = MemoryStore(":memory:")
    try:
        yield memory_store
    finally:
        memory_store.close()


@pytest.fixture
def runtime(settings: Settings) -> Iterator[Runtime]:
    result = build_runtime(settings)
    try:
        yield result
    finally:
        result.store.close()


@pytest.fixture
def api_client(tmp_path) -> Iterator[TestClient]:  # noqa: F821 - imported lazily below
    from fastapi.testclient import TestClient

    from backend.api.routes import create_app

    app = create_app(
        Settings(
            memory_database=":memory:",
            embedding_provider="hashing",
            llm_provider="deterministic",
            evaluation_report_path=str(tmp_path / "evaluation_report.json"),
            llm_benchmark_output_dir=str(tmp_path / "llm_benchmarks"),
        )
    )
    with TestClient(app) as client:
        yield client
    runtime = app.state.runtime_manager.maybe()
    if runtime is not None:
        runtime.store.close()
