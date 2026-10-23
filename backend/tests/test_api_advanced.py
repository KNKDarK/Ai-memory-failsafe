"""API coverage for cross-agent learning and adaptive strategy selection."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.api.routes import create_app
from backend.config import Settings

_BUILD_ENV = {
    "faults": {"build_requires": ["pandas"]},
    "registry": {"pandas": "2.2.0"},
}


def test_cross_agent_endpoint_shares_a_verified_lesson(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/tasks/cross-agent",
        json={
            "task": "Build the project",
            "learner_agent_id": "agent-a",
            "consumer_agent_id": "agent-b",
            "max_attempts": 2,
            "environment": _BUILD_ENV,
        },
    )
    assert response.status_code == 200
    body = response.json()

    assert body["learner"]["final_success"] is True
    assert body["consumer"]["final_success"] is True
    assert body["shared_memory_ids"]
    assert body["cross_agent_learning_observed"] is True
    assert set(body["reused_memory_ids"]).issubset(body["shared_memory_ids"])

    agents = api_client.get("/api/agents").json()
    by_agent = {item["agent_id"]: item for item in agents["agents"]}
    assert by_agent["agent-a"]["memories_created"] == 1
    assert by_agent["agent-b"]["memories_used"] == 1
    assert agents["cross_agent_reuse_events"] >= 1

    detail = api_client.get("/api/agents/agent-b").json()
    assert detail["agent"]["agent_id"] == "agent-b"
    assert detail["memories"]

    listed = api_client.get("/api/memories", params={"agent_id": "agent-a"}).json()
    assert listed["total"] == 1
    assert listed["items"][0]["agent_id"] == "agent-a"

    preview = api_client.post(
        "/api/retrieval/preview",
        json={"task": "Build the project", "agent_id": "agent-b"},
    ).json()
    assert preview["agent_id"] == "agent-b"
    assert preview["selected_ids"]


def test_unknown_agent_returns_404(api_client: TestClient) -> None:
    assert api_client.get("/api/agents/nobody").status_code == 404


def test_strategy_endpoint_reports_candidates_and_next_selection(
    api_client: TestClient,
) -> None:
    body = api_client.get("/api/retrieval/strategies").json()
    assert body["retrieval_method"] == "auto"
    assert body["adaptive"] is False
    assert set(body["candidates"]) == {"tfidf", "bm25", "embedding", "hybrid"}
    assert "generic" in body["next_selection"]


def test_adaptive_api_records_and_resets_strategy_stats(tmp_path) -> None:
    app = create_app(
        Settings(
            memory_database=":memory:",
            embedding_provider="hashing",
            llm_provider="deterministic",
            retrieval_method="adaptive",
            evaluation_report_path=str(tmp_path / "evaluation_report.json"),
            llm_benchmark_output_dir=str(tmp_path / "llm_benchmarks"),
        )
    )
    with TestClient(app) as client:
        run = client.post(
            "/api/tasks/run",
            json={
                "task": "Build the project",
                "mode": "memory",
                "max_attempts": 2,
                "agent_id": "agent-a",
                "environment": _BUILD_ENV,
            },
        )
        assert run.status_code == 200
        run_body = run.json()
        assert run_body["strategy_selections"]
        strategy = run_body["strategy_selections"][0]["strategy"]

        strategies = client.get("/api/retrieval/strategies").json()
        assert strategies["adaptive"] is True
        assert strategies["stats"]
        assert strategies["stats"][0]["strategy"] == strategy
        assert strategies["next_selection"]["build_project"]["strategy"] in set(
            strategies["candidates"]
        )

        cleared = client.post("/api/retrieval/strategies/reset").json()
        assert cleared["cleared"] >= 1
        assert client.get("/api/retrieval/strategies").json()["stats"] == []
    runtime = app.state.runtime_manager.maybe()
    if runtime is not None:
        runtime.store.close()
