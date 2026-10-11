"""HTTP API integration tests (Starlette TestClient)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.config import Settings
from backend.evaluation.scenarios import build_scenarios

EXPECTED_SCENARIO_COUNT = len(build_scenarios())


def test_root_and_health(api_client: TestClient) -> None:
    root = api_client.get("/")
    assert root.status_code == 200
    assert root.json()["name"] == "AI Agent Failure Memory"

    health = api_client.get("/api/health")
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "ok"
    assert body["memory_database_available"] is True
    assert body["memory_count"] == 0


def test_config_exposes_no_secrets(api_client: TestClient) -> None:
    response = api_client.get("/api/config")
    assert response.status_code == 200
    body = response.json()
    assert body["offline"] is True
    assert "api_key" not in response.text.lower()
    assert body["retrieval"]["min_similarity"] > 0


def test_scenarios_listing(api_client: TestClient) -> None:
    response = api_client.get("/api/scenarios")
    assert response.status_code == 200
    scenarios = response.json()
    assert len(scenarios) == EXPECTED_SCENARIO_COUNT
    assert all(item["simulated"] for item in scenarios)


def test_scenario_run_shows_prevention(api_client: TestClient) -> None:
    response = api_client.post("/api/scenarios/missing_config_deploy/run")
    assert response.status_code == 200
    body = response.json()
    assert body["scenario"]["id"] == "missing_config_deploy"
    assert body["baseline"]["final_success"] is False
    assert body["memory"]["final_success"] is True
    assert body["memory"]["prevented_failure"] is True
    assert body["memory"]["memory_ids_created"]
    assert body["memory"]["memory_ids_applied"]
    assert body["memory_stats"]["after"]["total_memories"] >= 1
    assert body["metrics"]["baseline"]["success"] is False
    assert body["metrics"]["memory"]["success"] is True


def test_unknown_scenario_returns_404(api_client: TestClient) -> None:
    assert api_client.post("/api/scenarios/nope/run").status_code == 404


def test_task_run_persists_a_learned_memory(api_client: TestClient) -> None:
    payload = {
        "task": "Build the project",
        "mode": "memory",
        "max_attempts": 2,
        "environment": {"faults": {"build_requires": ["pandas"]}, "registry": {"pandas": "2.2.0"}},
    }
    response = api_client.post("/api/tasks/run", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["final_success"] is True
    assert body["memory_ids_created"]

    listed = api_client.get("/api/memories").json()
    assert listed["total"] == 1
    memory = listed["items"][0]
    assert memory["failure_category"] == "missing_dependency"
    assert "effective_confidence" in memory


def test_task_run_rejects_empty_task(api_client: TestClient) -> None:
    assert api_client.post("/api/tasks/run", json={"task": ""}).status_code == 422
    assert api_client.post("/api/tasks/compare", json={"task": "  "}).status_code == 422


def test_task_compare(api_client: TestClient) -> None:
    payload = {
        "task": "Build the project",
        "max_attempts": 2,
        "environment": {"faults": {"build_requires": ["pandas"]}, "registry": {"pandas": "2.2.0"}},
    }
    response = api_client.post("/api/tasks/compare", json=payload)
    assert response.status_code == 200
    body = response.json()
    # Baseline cannot learn; memory mode learns on attempt 1 and prevents on attempt 2.
    assert body["baseline"]["final_success"] is False
    assert body["memory"]["final_success"] is True
    assert body["memory"]["prevented_failure"] is True
    assert body["memory"]["attempts"]


def _learn_one(api_client: TestClient) -> str:
    payload = {
        "task": "Build the project",
        "mode": "memory",
        "max_attempts": 2,
        "environment": {"faults": {"build_requires": ["pandas"]}, "registry": {"pandas": "2.2.0"}},
    }
    body = api_client.post("/api/tasks/run", json=payload).json()
    return body["memory_ids_created"][0]


def test_memory_detail_feedback_and_status(api_client: TestClient) -> None:
    memory_id = _learn_one(api_client)

    detail = api_client.get(f"/api/memories/{memory_id}")
    assert detail.status_code == 200
    assert detail.json()["memory"]["id"] == memory_id
    assert detail.json()["feedback"] == []

    feedback = api_client.post(
        f"/api/memories/{memory_id}/feedback", json={"verdict": "useful", "comment": "worked"}
    )
    assert feedback.status_code == 200
    assert feedback.json()["memory"]["helpful_count"] == 1
    assert feedback.json()["feedback"]["verdict"] == "useful"

    patched = api_client.patch(f"/api/memories/{memory_id}/status", json={"status": "outdated"})
    assert patched.status_code == 200
    assert patched.json()["memory"]["status"] == "outdated"

    assert api_client.get("/api/memories?status=outdated").json()["total"] == 1
    assert api_client.get("/api/memories?status=active").json()["total"] == 0


def test_memory_stats_and_contradictions(api_client: TestClient) -> None:
    _learn_one(api_client)
    stats = api_client.get("/api/memories/stats").json()
    assert stats["total_memories"] == 1
    assert stats["by_category"]["missing_dependency"] == 1

    contradictions = api_client.get("/api/memories/contradictions").json()
    assert contradictions["count"] == 0


def test_invalid_status_filter_is_rejected(api_client: TestClient) -> None:
    assert api_client.get("/api/memories?status=definitely-not-real").status_code == 422


def test_memory_stats_include_lifecycle(api_client: TestClient) -> None:
    _learn_one(api_client)
    stats = api_client.get("/api/memories/stats").json()
    lifecycle = stats["lifecycle"]
    assert lifecycle["total"] == 1
    assert lifecycle["counts"]["fresh"] == 1


def test_memory_lifecycle_dry_run_and_apply(api_client: TestClient) -> None:
    _learn_one(api_client)
    dry = api_client.get("/api/memories/lifecycle")
    assert dry.status_code == 200
    assert "counts" in dry.json()
    # A freshly learned memory is fresh, so applying the policy changes nothing.
    applied = api_client.post("/api/memories/lifecycle/apply")
    assert applied.status_code == 200
    assert applied.json()["applied"] == 0


def test_memory_exposes_uses_and_success_rate(api_client: TestClient) -> None:
    memory_id = _learn_one(api_client)
    memory = api_client.get(f"/api/memories/{memory_id}").json()["memory"]
    assert memory["uses"] == memory["use_count"]
    if memory["use_count"]:
        assert memory["success_rate"] == round(memory["success_count"] / memory["use_count"], 4)
    else:
        assert memory["success_rate"] is None


def test_api_accepts_naive_mode(api_client: TestClient) -> None:
    payload = {
        "task": "Build the project",
        "mode": "naive",
        "max_attempts": 2,
        "environment": {
            "faults": {"build_requires": ["pandas"]},
            "registry": {"pandas": "2.2.0"},
        },
    }
    body = api_client.post("/api/tasks/run", json=payload).json()
    assert body["mode"] == "naive"


def test_delete_memory(api_client: TestClient) -> None:
    memory_id = _learn_one(api_client)
    assert api_client.delete(f"/api/memories/{memory_id}").status_code == 200
    assert api_client.delete(f"/api/memories/{memory_id}").status_code == 404
    assert api_client.get(f"/api/memories/{memory_id}").status_code == 404


def test_feedback_for_missing_memory_is_404(api_client: TestClient) -> None:
    response = api_client.post("/api/memories/ghost/feedback", json={"verdict": "useful"})
    assert response.status_code == 404


def test_retrieval_preview_for_scenario(api_client: TestClient) -> None:
    _learn_one(api_client)
    response = api_client.post(
        "/api/retrieval/preview",
        json={"task": "Build the project", "scenario_id": "conflicting_memories"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["retrieval_mode"] == "hashing_embedding"
    assert isinstance(body["results"], list)


def test_retrieval_preview_requires_task_or_scenario(api_client: TestClient) -> None:
    assert api_client.post("/api/retrieval/preview", json={}).status_code == 422


def test_evaluation_run_and_report(api_client: TestClient) -> None:
    assert api_client.get("/api/evaluation/report").status_code == 404

    response = api_client.post("/api/evaluation/run", json={})
    assert response.status_code == 200
    report = response.json()
    assert report["scenario_count"] == EXPECTED_SCENARIO_COUNT
    assert report["scenarios_expectations_met"] == EXPECTED_SCENARIO_COUNT
    assert report["retrieval_relevance"]["application"]["precision"] == 1.0

    stored = api_client.get("/api/evaluation/report")
    assert stored.status_code == 200
    assert stored.json()["scenario_count"] == EXPECTED_SCENARIO_COUNT


def test_degraded_mode_when_database_unavailable(tmp_path) -> None:
    from backend.api.routes import create_app

    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    app = create_app(Settings(memory_database=str(blocker / "db.sqlite")))
    with TestClient(app, raise_server_exceptions=False) as client:
        health = client.get("/api/health").json()
        assert health["status"] == "degraded"
        assert health["memory_database_available"] is False
        assert client.get("/api/memories").status_code == 503
        assert client.get("/api/scenarios").status_code == 200  # still usable


def test_app_module_reexports_application() -> None:
    """Both documented launch commands must resolve to the same app factory."""
    from backend.api.routes import app as routes_app
    from backend.api.routes import create_app as routes_create_app
    from backend.app import app as module_app
    from backend.app import create_app as module_create_app

    assert module_app is routes_app
    assert module_create_app is routes_create_app
