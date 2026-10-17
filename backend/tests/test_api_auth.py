"""API access-control tests.

Covers the static bearer-token mechanism protecting task-execution and
memory-mutation endpoints: enforcement when ``API_AUTH_TOKEN`` is configured,
the open development mode when it is not, header variants, status codes
(401/403), and the guarantee that the token never leaks into responses or logs.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from backend.api.routes import create_app
from backend.config import Settings

TOKEN = "unit-test-token-3f9a1c7d"

_TASK_PAYLOAD = {
    "task": "Build the project",
    "mode": "memory",
    "max_attempts": 2,
    "environment": {"faults": {"build_requires": ["pandas"]}, "registry": {"pandas": "2.2.0"}},
}


def _auth(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def secure_client(tmp_path) -> TestClient:
    app = create_app(
        Settings(
            memory_database=":memory:",
            embedding_provider="hashing",
            llm_provider="deterministic",
            evaluation_report_path=str(tmp_path / "evaluation_report.json"),
            llm_benchmark_output_dir=str(tmp_path / "llm_benchmarks"),
            api_auth_token=TOKEN,
        )
    )
    with TestClient(app) as client:
        yield client
    runtime = app.state.runtime_manager.maybe()
    if runtime is not None:
        runtime.store.close()


# --------------------------------------------------------------------------- #
# Development mode (no token configured) — existing behaviour preserved
# --------------------------------------------------------------------------- #
def test_mutations_stay_open_when_no_token_configured(api_client: TestClient) -> None:
    response = api_client.post("/api/tasks/run", json=_TASK_PAYLOAD)
    assert response.status_code == 200
    assert response.json()["memory_ids_created"]


# --------------------------------------------------------------------------- #
# Enforcement when a token is configured
# --------------------------------------------------------------------------- #
def test_task_run_without_token_is_401(secure_client: TestClient) -> None:
    response = secure_client.post("/api/tasks/run", json=_TASK_PAYLOAD)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert "token" in response.json()["detail"].lower()


def test_wrong_token_is_403(secure_client: TestClient) -> None:
    response = secure_client.post("/api/tasks/run", json=_TASK_PAYLOAD, headers=_auth("nope"))
    assert response.status_code == 403
    assert response.json()["detail"] == "invalid API token"


def test_wrong_x_api_key_is_403(secure_client: TestClient) -> None:
    response = secure_client.post(
        "/api/tasks/run", json=_TASK_PAYLOAD, headers={"X-API-Key": "nope"}
    )
    assert response.status_code == 403


def test_non_bearer_authorization_header_is_401(secure_client: TestClient) -> None:
    # Only the Bearer scheme counts; other schemes (Basic, ...) are ignored
    # and treated as "no credential presented".
    import base64

    credentials = base64.b64encode(b"user:pass").decode()
    response = secure_client.post(
        "/api/tasks/run",
        json=_TASK_PAYLOAD,
        headers={"Authorization": f"Basic {credentials}"},
    )
    assert response.status_code == 401


def test_empty_bearer_credential_is_401(secure_client: TestClient) -> None:
    response = secure_client.post(
        "/api/tasks/run", json=_TASK_PAYLOAD, headers={"Authorization": "Bearer "}
    )
    assert response.status_code == 401


def test_valid_bearer_token_runs_task_and_persists(secure_client: TestClient) -> None:
    response = secure_client.post("/api/tasks/run", json=_TASK_PAYLOAD, headers=_auth())
    assert response.status_code == 200
    body = response.json()
    assert body["final_success"] is True
    assert body["memory_ids_created"]

    listed = secure_client.get("/api/memories")  # reads stay open
    assert listed.status_code == 200
    assert listed.json()["total"] == 1


def test_valid_x_api_key_header_runs_task(secure_client: TestClient) -> None:
    response = secure_client.post(
        "/api/tasks/run", json=_TASK_PAYLOAD, headers={"X-API-Key": TOKEN}
    )
    assert response.status_code == 200


def test_all_mutation_endpoints_are_protected(secure_client: TestClient) -> None:
    requests = [
        ("POST", "/api/tasks/compare", {"task": "Build the project"}),
        ("POST", "/api/scenarios/missing_config_deploy/run", None),
        ("POST", "/api/memories/lifecycle/apply", None),
        ("POST", "/api/memories/ghost/feedback", {"verdict": "useful"}),
        ("PATCH", "/api/memories/ghost/status", {"status": "outdated"}),
        ("DELETE", "/api/memories/ghost", None),
        ("POST", "/api/evaluation/run", {}),
        ("POST", "/api/evaluation/llm/run", {}),
    ]
    for method, path, payload in requests:
        response = secure_client.request(method, path, json=payload)
        assert response.status_code == 401, f"{method} {path} was not protected"


def test_auth_check_precedes_resource_lookup(secure_client: TestClient) -> None:
    """With a valid token, a missing memory is a 404 — never a 401/403."""
    response = secure_client.post(
        "/api/memories/ghost/feedback", json={"verdict": "useful"}, headers=_auth()
    )
    assert response.status_code == 404


def test_feedback_and_status_mutations_work_with_token(secure_client: TestClient) -> None:
    created = secure_client.post("/api/tasks/run", json=_TASK_PAYLOAD, headers=_auth())
    memory_id = created.json()["memory_ids_created"][0]

    feedback = secure_client.post(
        f"/api/memories/{memory_id}/feedback",
        json={"verdict": "useful", "comment": "helped"},
        headers=_auth(),
    )
    assert feedback.status_code == 200

    patched = secure_client.patch(
        f"/api/memories/{memory_id}/status", json={"status": "outdated"}, headers=_auth()
    )
    assert patched.status_code == 200
    assert patched.json()["memory"]["status"] == "outdated"

    deleted = secure_client.delete(f"/api/memories/{memory_id}", headers=_auth())
    assert deleted.status_code == 200


# --------------------------------------------------------------------------- #
# Read-only surface stays open (health checks + dashboard reads)
# --------------------------------------------------------------------------- #
def test_reads_and_health_stay_open_with_token_configured(secure_client: TestClient) -> None:
    for path in ("/", "/api/health", "/api/config", "/api/scenarios", "/api/memories"):
        assert secure_client.get(path).status_code == 200, path
    assert secure_client.get("/api/memories/stats").status_code == 200
    assert secure_client.post("/api/retrieval/preview", json={}).status_code == 422  # reachable
    assert secure_client.get("/docs").status_code == 200


# --------------------------------------------------------------------------- #
# Secret hygiene: the token never appears in responses or logs
# --------------------------------------------------------------------------- #
def test_token_never_exposed_in_responses_or_logs(secure_client: TestClient, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    secure_client.get("/api/config")
    secure_client.post("/api/tasks/run", json=_TASK_PAYLOAD, headers=_auth())
    secure_client.post("/api/tasks/run", json=_TASK_PAYLOAD)  # 401 path
    secure_client.post("/api/tasks/run", json=_TASK_PAYLOAD, headers=_auth("wrong"))
    assert TOKEN not in secure_client.get("/api/config").text
    assert TOKEN not in caplog.text


def test_llm_evaluation_run_with_token_returns_honest_skip_report(
    secure_client: TestClient,
) -> None:
    """With no real provider configured, the endpoint must report 'skipped'
    instead of fabricating model results — and it still needs the token."""
    response = secure_client.post("/api/evaluation/llm/run", json={}, headers=_auth())
    assert response.status_code == 200
    report = response.json()
    assert report["status"] == "skipped"
    assert report["error"]
    assert report["aggregate"] is None
    # A skipped run leaves no report on disk behind.
    assert "report_path" not in report


def test_llm_report_reads_stay_open_when_auth_enabled(secure_client: TestClient) -> None:
    listing = secure_client.get("/api/evaluation/llm/reports")
    assert listing.status_code == 200
    assert listing.json()["reports"] == []

    missing = secure_client.get("/api/evaluation/llm/reports/nope")
    assert missing.status_code == 404
