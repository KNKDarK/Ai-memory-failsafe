"""Request resource-limit tests.

Covers the HTTP body-size cap (413), its content-type independence and
chunked-transfer bypass resistance, malformed and pathologically nested JSON
bodies, and the size/depth limits on user-supplied environment structures —
while confirming the existing task-length validation is preserved.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.api.middleware import BodySizeLimitMiddleware
from backend.api.routes import create_app
from backend.config import Settings

DEFAULT_LIMIT = 262144  # Settings.max_request_body_bytes default (256 KiB)


@pytest.fixture
def small_limit_client(tmp_path) -> TestClient:
    app = create_app(
        Settings(
            memory_database=":memory:",
            embedding_provider="hashing",
            llm_provider="deterministic",
            evaluation_report_path=str(tmp_path / "evaluation_report.json"),
            max_request_body_bytes=2048,
        )
    )
    with TestClient(app) as client:
        yield client
    runtime = app.state.runtime_manager.maybe()
    if runtime is not None:
        runtime.store.close()


# --------------------------------------------------------------------------- #
# Oversized bodies -> 413, for every content type
# --------------------------------------------------------------------------- #
def test_oversized_json_body_is_413(api_client: TestClient) -> None:
    payload = {"task": "x" * (DEFAULT_LIMIT + 4096)}
    response = api_client.post("/api/tasks/run", json=payload)
    assert response.status_code == 413
    body = response.json()
    assert body["limit"] == DEFAULT_LIMIT
    assert "maximum" in body["detail"]


def test_oversized_body_is_content_type_agnostic(api_client: TestClient) -> None:
    blob = b"x" * (DEFAULT_LIMIT + 4096)
    # Plain text, multipart, and malformed JSON bodies are capped identically:
    # the limit is enforced on the wire, before any content-type parsing.
    text = api_client.post("/api/tasks/run", content=blob, headers={"Content-Type": "text/plain"})
    assert text.status_code == 413

    multipart = api_client.post(
        "/api/tasks/run",
        files={"file": ("big.bin", blob, "application/octet-stream")},
    )
    assert multipart.status_code == 413

    malformed = api_client.post(
        "/api/tasks/run",
        content=blob,
        headers={"Content-Type": "application/json"},
    )
    assert malformed.status_code == 413  # capped before JSON parsing


def test_oversized_body_is_rejected_on_reads_too(api_client: TestClient) -> None:
    blob = b"x" * (DEFAULT_LIMIT + 4096)
    response = api_client.patch(
        "/api/memories/some-id/status", content=blob, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413


def test_body_under_limit_is_accepted(small_limit_client: TestClient) -> None:
    # ~1.9 KB body against a 2 KB cap: passes the middleware (and here even
    # schema validation), proving the limit is a size cap, not a blanket deny.
    payload = {"task": "x" * 1900}
    response = small_limit_client.post("/api/tasks/run", json=payload)
    assert response.status_code == 200


def test_body_just_over_limit_is_413(small_limit_client: TestClient) -> None:
    payload = {"task": "x" * 2100}
    response = small_limit_client.post("/api/tasks/run", json=payload)
    assert response.status_code == 413
    assert response.json()["limit"] == 2048


def test_limit_env_vars_are_parsed(monkeypatch) -> None:
    monkeypatch.setenv("MAX_REQUEST_BODY_BYTES", "8192")
    monkeypatch.setenv("MAX_ENV_DEPTH", "4")
    monkeypatch.setenv("MAX_ENV_ITEMS", "10")
    monkeypatch.setenv("MAX_ENV_VALUE_LENGTH", "128")
    settings = Settings.from_env()
    assert settings.max_request_body_bytes == 8192
    assert settings.max_env_depth == 4
    assert settings.max_env_items == 10
    assert settings.max_env_value_length == 128


# --------------------------------------------------------------------------- #
# Chunked / Content-Length-less bypass resistance (direct ASGI level)
# --------------------------------------------------------------------------- #
async def _call_asgi(
    app,
    *,
    method: str = "POST",
    path: str = "/api/tasks/run",
    headers: list[tuple[bytes, bytes]] | None = None,
    chunks: list[bytes] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "scheme": "http",
        "headers": headers or [],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
    }
    sent: list[dict[str, Any]] = []
    pending = list(chunks or [])

    async def receive() -> dict[str, Any]:
        if pending:
            body = pending.pop(0)
            return {
                "type": "http.request",
                "body": body,
                "more_body": bool(pending),
            }
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await app(scope, receive, send)
    return sent, []


def _echo_app(called: list[bytes]):
    async def inner(scope, receive, send):
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body", False):
                break
        called.append(body)
        payload = json.dumps({"received_bytes": len(body)}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(payload)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": payload})

    return inner


def test_chunked_body_without_content_length_is_capped() -> None:
    called: list[bytes] = []
    app = BodySizeLimitMiddleware(_echo_app(called), max_bytes=1024)
    sent, _ = asyncio.run(
        _call_asgi(
            app,
            headers=[(b"content-type", b"multipart/form-data; boundary=x")],
            chunks=[b"y" * 600, b"y" * 600],  # 1200 bytes total, no Content-Length
        )
    )
    assert sent[0]["status"] == 413
    assert called == []  # the inner application never saw the body


def test_chunked_body_under_limit_is_replayed_intact() -> None:
    called: list[bytes] = []
    app = BodySizeLimitMiddleware(_echo_app(called), max_bytes=1024)
    sent, _ = asyncio.run(
        _call_asgi(app, headers=[(b"content-type", b"application/json")], chunks=[b'{"a":', b"1}"])
    )
    assert sent[0]["status"] == 200
    assert called == [b'{"a":1}']


def test_declared_content_length_over_limit_never_reads_body() -> None:
    called: list[bytes] = []
    app = BodySizeLimitMiddleware(_echo_app(called), max_bytes=1024)
    # Declared 5 MB: refused immediately, without draining the stream.
    sent, _ = asyncio.run(_call_asgi(app, headers=[(b"content-length", b"5242880")], chunks=[]))
    assert sent[0]["status"] == 413
    assert called == []


def test_get_requests_pass_through_untouched() -> None:
    called: list[bytes] = []
    app = BodySizeLimitMiddleware(_echo_app(called), max_bytes=1024)
    sent, _ = asyncio.run(_call_asgi(app, method="GET", chunks=[]))
    # GET has no body semantics: the middleware must not block or rewrite it.
    assert sent[0]["status"] == 200


# --------------------------------------------------------------------------- #
# Malformed / deeply nested / oversized structures
# --------------------------------------------------------------------------- #
def test_malformed_json_is_rejected_cleanly(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/tasks/run", content=b'{"task": "x",,}', headers={"Content-Type": "application/json"}
    )
    assert response.status_code in (400, 422)
    assert response.status_code < 500


def test_pathologically_nested_json_body_is_rejected_cleanly(api_client: TestClient) -> None:
    # Beyond the JSON parser's recursion limit: must be a clean client error
    # (FastAPI's body-parse handler), not a 500 or a hung request.
    depth = 3000
    payload = (
        b'{"task":"x","environment":{"faults":' + b'{"a":' * depth + b"1" + b"}" * depth + b"}}}"
    )
    response = api_client.post(
        "/api/tasks/run", content=payload, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 400
    assert "parsing the body" in response.json()["detail"]


def test_nested_body_past_python_recursion_is_422(api_client: TestClient) -> None:
    # Deep (but parseable-by-stdlib) nesting: pydantic's JSON parser rejects it
    # with its own json_invalid error — still a clean 422, never a crash.
    # (A RecursionError safety handler additionally exists in create_app for
    # any recursion source outside the parser.)
    depth = 800
    payload = (
        b'{"task":"x","environment":{"faults":' + b'{"a":' * depth + b"1" + b"}" * depth + b"}}}"
    )
    response = api_client.post(
        "/api/tasks/run", content=payload, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert "json" in response.text.lower()


def test_recursion_error_safety_net_returns_422(tmp_path) -> None:
    """The RecursionError handler registered in create_app answers 422."""
    app = create_app(
        Settings(
            memory_database=":memory:",
            embedding_provider="hashing",
            llm_provider="deterministic",
            evaluation_report_path=str(tmp_path / "evaluation_report.json"),
        )
    )
    handler = app.exception_handlers.get(RecursionError)
    assert handler is not None
    response = asyncio.run(handler(None, RecursionError()))
    assert response.status_code == 422
    assert "deeply nested" in json.loads(response.body)["detail"]


def test_moderately_nested_environment_is_rejected(api_client: TestClient) -> None:
    faults: Any = 1
    for _ in range(30):  # parses fine, exceeds MAX_ENV_DEPTH
        faults = {"a": faults}
    response = api_client.post(
        "/api/tasks/run", json={"task": "x", "environment": {"faults": faults}}
    )
    assert response.status_code == 422
    assert "depth" in response.text


def test_too_many_environment_items_is_rejected(api_client: TestClient) -> None:
    faults = {f"key{i}": "v" for i in range(100)}  # over MAX_ENV_ITEMS (64)
    response = api_client.post(
        "/api/tasks/run", json={"task": "x", "environment": {"faults": faults}}
    )
    assert response.status_code == 422
    assert "maximum" in response.text


def test_oversized_environment_string_is_rejected(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/tasks/run",
        json={"task": "x", "environment": {"config": {"BIG": "y" * 5000}}},  # over 4096
    )
    assert response.status_code == 422
    assert "maximum length" in response.text


def test_non_string_flat_environment_value_is_rejected(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/tasks/run", json={"task": "x", "environment": {"config": {"A": {"nested": True}}}}
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------- #
# Existing validation preserved
# --------------------------------------------------------------------------- #
def test_task_length_limit_is_preserved(api_client: TestClient) -> None:
    response = api_client.post("/api/tasks/run", json={"task": "x" * 2001})
    assert response.status_code == 422
    assert "task" in response.text


def test_valid_environment_structure_still_accepted(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/tasks/run",
        json={
            "task": "Build the project",
            "mode": "memory",
            "max_attempts": 2,
            "environment": {
                "faults": {"build_requires": ["pandas"]},
                "registry": {"pandas": "2.2.0"},
            },
        },
    )
    assert response.status_code == 200
    assert response.json()["memory_ids_created"]


# --------------------------------------------------------------------------- #
# LLM evaluation request validation
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("repetitions", [0, -1, 11, 1000])
def test_llm_evaluation_repetitions_bounds_are_enforced(
    api_client: TestClient, repetitions: int
) -> None:
    response = api_client.post("/api/evaluation/llm/run", json={"repetitions": repetitions})
    assert response.status_code == 422


def test_llm_evaluation_rejects_unknown_mode(api_client: TestClient) -> None:
    response = api_client.post("/api/evaluation/llm/run", json={"modes": ["bogus"]})
    assert response.status_code == 422  # literal types are enforced


def test_llm_evaluation_rejects_oversized_scenario_list(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/evaluation/llm/run", json={"scenarios": [f"s{i}" for i in range(65)]}
    )
    assert response.status_code == 422


def test_llm_evaluation_rejects_unknown_body_fields(api_client: TestClient) -> None:
    response = api_client.post("/api/evaluation/llm/run", json={"extra": "value"})
    assert response.status_code == 422
