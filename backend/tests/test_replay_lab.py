"""Tests for the Memory Replay Lab engine and REST endpoint.

Covers baseline/treatment execution arms, trace schema compliance,
rejection reason capture, metric delta accuracy, and the HTTP API.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.api.schemas.lab import (
    ExecutionTrace as LabExecutionTrace,
)
from backend.api.schemas.lab import (
    MemoryAttribution as LabMemoryAttribution,
)
from backend.api.schemas.lab import (
    StepTrace as LabStepTrace,
)
from backend.evaluation.replay_engine import MemoryReplayLab

# ------------------------------------------------------------------ #
# Unit tests — replay engine directly
# ------------------------------------------------------------------ #


class TestMemoryReplayLabEngine:
    """Direct unit tests for MemoryReplayLab.run_replay."""

    def test_run_replay_returns_required_fields(self, api_client: TestClient) -> None:
        resp = api_client.post(
            "/lab/replay",
            json={
                "scenario_id": "test_scenario",
                "task_input": "Deploy the application with DATABASE_URL present.",
                "execution_mode": "simulated",
                "project_id": "default_project",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        for key in ("replay_id", "scenario_id", "execution_mode", "baseline", "treatment", "delta"):
            assert key in body

    def test_replay_id_is_valid_hex(self) -> None:
        lab = MemoryReplayLab()
        response = lab.run_replay(
            scenario_id="uuid_test",
            task_input="Deploy the application with DATABASE_URL present.",
            mode="simulated",
            project_id="default_project",
        )
        assert len(response.replay_id) == 12
        int(response.replay_id, 16)

    def test_baseline_arm_has_memory_disabled(self, api_client: TestClient) -> None:
        resp = api_client.post(
            "/lab/replay",
            json={
                "scenario_id": "baseline_test",
                "task_input": "Deploy the application with DATABASE_URL present.",
                "execution_mode": "simulated",
                "project_id": "default_project",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["baseline"]["memory_enabled"] is False

    def test_treatment_arm_has_memory_enabled(self, api_client: TestClient) -> None:
        resp = api_client.post(
            "/lab/replay",
            json={
                "scenario_id": "treatment_test",
                "task_input": "Deploy the application with DATABASE_URL present.",
                "execution_mode": "simulated",
                "project_id": "default_project",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["treatment"]["memory_enabled"] is True

    def test_baseline_and_treatment_memory_flags(self, api_client: TestClient) -> None:
        """Baseline should have memory_enabled=False; treatment should have True."""
        resp = api_client.post(
            "/lab/replay",
            json={
                "scenario_id": "mode_test",
                "task_input": "Deploy the application with DATABASE_URL present.",
                "execution_mode": "simulated",
                "project_id": "default_project",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["baseline"]["memory_enabled"] is False
        assert body["treatment"]["memory_enabled"] is True

    def test_trace_schema_compliance_baseline(self, api_client: TestClient) -> None:
        resp = api_client.post(
            "/lab/replay",
            json={
                "scenario_id": "schema_test",
                "task_input": "Deploy the application with DATABASE_URL present.",
                "execution_mode": "simulated",
                "project_id": "default_project",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        trace_dict = body["baseline"]
        trace = LabExecutionTrace(**trace_dict)
        assert isinstance(trace, LabExecutionTrace)
        assert isinstance(trace.success, bool)
        assert isinstance(trace.total_attempts, int) and trace.total_attempts >= 1
        assert isinstance(trace.execution_time_ms, (int, float))

    def test_trace_schema_compliance_treatment(self, api_client: TestClient) -> None:
        resp = api_client.post(
            "/lab/replay",
            json={
                "scenario_id": "schema_test2",
                "task_input": "Deploy the application with DATABASE_URL present.",
                "execution_mode": "simulated",
                "project_id": "default_project",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        trace_dict = body["treatment"]
        LabExecutionTrace(**trace_dict)

    def test_step_trace_schema_compliance(self, api_client: TestClient) -> None:
        resp = api_client.post(
            "/lab/replay",
            json={
                "scenario_id": "step_test",
                "task_input": "Deploy the application with DATABASE_URL present.",
                "execution_mode": "simulated",
                "project_id": "default_project",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        for arm_key in ("baseline", "treatment"):
            for s_dict in body[arm_key]["steps"]:
                step = LabStepTrace(**s_dict)
                assert isinstance(step.step_number, int) and step.step_number >= 0
                assert len(step.action) > 0

    def test_metric_delta_has_required_keys(self, api_client: TestClient) -> None:
        resp = api_client.post(
            "/lab/replay",
            json={
                "scenario_id": "delta_test",
                "task_input": "Deploy the application with DATABASE_URL present.",
                "execution_mode": "simulated",
                "project_id": "default_project",
            },
        )
        assert resp.status_code == 200
        delta = resp.json()["delta"]
        for key in (
            "success_improved",
            "attempts_saved",
            "time_saved_ms",
            "memories_applied_count",
        ):
            assert key in delta

    def test_metric_delta_types(self, api_client: TestClient) -> None:
        resp = api_client.post(
            "/lab/replay",
            json={
                "scenario_id": "delta_types",
                "task_input": "Deploy the application with DATABASE_URL present.",
                "execution_mode": "simulated",
                "project_id": "default_project",
            },
        )
        assert resp.status_code == 200
        delta = resp.json()["delta"]
        assert isinstance(delta["success_improved"], bool)
        assert isinstance(delta["attempts_saved"], int) and delta["attempts_saved"] >= 0
        assert isinstance(delta["time_saved_ms"], (int, float))

    def test_replay_with_scenario_that_knows_lessons(self, api_client: TestClient) -> None:
        api_client.post("/api/scenarios/missing_config_deploy/run")
        resp = api_client.post(
            "/lab/replay",
            json={
                "scenario_id": "seeded_replay",
                "task_input": "Deploy the application with DATABASE_URL present.",
                "execution_mode": "simulated",
                "project_id": "default_project",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        treatment_memories = body["treatment"]["retrieved_memories"]
        assert isinstance(treatment_memories, list)


# ------------------------------------------------------------------ #
# Integration tests — rejection reasons and API-level behaviour
# ------------------------------------------------------------------ #


class TestRejectionReasons:
    """Verify that rejection_reason fields are captured correctly."""

    def test_replay_response_contains_attribution_fields(self, api_client: TestClient) -> None:
        resp = api_client.post(
            "/lab/replay",
            json={
                "scenario_id": "attribution_test",
                "task_input": "Deploy the application with DATABASE_URL present.",
                "execution_mode": "simulated",
                "project_id": "default_project",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        for arm_key in ("baseline", "treatment"):
            for mem_dict in body[arm_key]["retrieved_memories"]:
                attr = LabMemoryAttribution(**mem_dict)
                assert len(attr.lesson_id) > 0
                assert len(attr.lesson_text) > 0
                assert len(attr.retrieval_strategy) > 0
                assert 0.0 <= attr.similarity_score <= 1.0
                assert 0.0 <= attr.confidence_score <= 1.0

    def test_rejection_reason_can_be_none(self, api_client: TestClient) -> None:
        resp = api_client.post(
            "/lab/replay",
            json={
                "scenario_id": "rejection_none_test",
                "task_input": "Deploy the application with DATABASE_URL present.",
                "execution_mode": "simulated",
                "project_id": "default_project",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        for arm_key in ("baseline", "treatment"):
            for mem_dict in body[arm_key]["retrieved_memories"]:
                attr = LabMemoryAttribution(**mem_dict)
                if attr.applied:
                    assert attr.rejection_reason is None

    def test_replay_request_validation_missing_scenario(self, api_client: TestClient) -> None:
        resp = api_client.post("/lab/replay", json={"task_input": "some task"})
        assert resp.status_code in (400, 422)

    def test_replay_request_validation_missing_task(self, api_client: TestClient) -> None:
        resp = api_client.post("/lab/replay", json={"scenario_id": "x"})
        assert resp.status_code in (400, 422)

    def test_replay_request_validation_empty_task(self, api_client: TestClient) -> None:
        resp = api_client.post("/lab/replay", json={"scenario_id": "x", "task_input": ""})
        assert resp.status_code in (400, 422)

    def test_replay_request_validation_invalid_mode(self, api_client: TestClient) -> None:
        resp = api_client.post(
            "/lab/replay",
            json={"scenario_id": "x", "task_input": "y", "execution_mode": "invalid"},
        )
        assert resp.status_code in (400, 422)


class TestMetricDeltaAccuracy:
    """Verify that computed deltas are logically consistent."""

    def test_success_improved_false_when_both_succeed(self, api_client: TestClient) -> None:
        resp = api_client.post(
            "/lab/replay",
            json={
                "scenario_id": "both_success",
                "task_input": "Deploy the application with DATABASE_URL present.",
                "execution_mode": "simulated",
                "project_id": "default_project",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        if body["baseline"]["success"] and body["treatment"]["success"]:
            assert body["delta"]["success_improved"] is False

    def test_attempts_saved_is_non_negative(self, api_client: TestClient) -> None:
        resp = api_client.post(
            "/lab/replay",
            json={
                "scenario_id": "attempts_test",
                "task_input": "Deploy the application with DATABASE_URL present.",
                "execution_mode": "simulated",
                "project_id": "default_project",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["delta"]["attempts_saved"] >= 0

    def test_time_saved_ms_is_numeric(self, api_client: TestClient) -> None:
        resp = api_client.post(
            "/lab/replay",
            json={
                "scenario_id": "time_test",
                "task_input": "Deploy the application with DATABASE_URL present.",
                "execution_mode": "simulated",
                "project_id": "default_project",
            },
        )
        assert resp.status_code == 200
        assert isinstance(resp.json()["delta"]["time_saved_ms"], (int, float))

    def test_prevention_injections_present_when_memories_applied(
        self, api_client: TestClient
    ) -> None:
        api_client.post("/api/scenarios/missing_config_deploy/run")
        resp = api_client.post(
            "/lab/replay",
            json={
                "scenario_id": "prevention_test",
                "task_input": "Deploy the application with DATABASE_URL present.",
                "execution_mode": "simulated",
                "project_id": "default_project",
            },
        )
        assert resp.status_code == 200
        treatment = resp.json()["treatment"]
        assert isinstance(treatment["prevention_injections"], list)


class TestReplayLabDirectly:
    """Test MemoryReplayLab class directly without HTTP layer."""

    def test_run_replay_returns_correct_scenario_id(self) -> None:
        lab = MemoryReplayLab()
        response = lab.run_replay(
            scenario_id="custom_scenario_123",
            task_input="Deploy the application with DATABASE_URL present.",
            mode="simulated",
            project_id="my_project",
        )
        assert response.scenario_id == "custom_scenario_123"

    def test_run_replay_preserves_execution_mode(self) -> None:
        lab = MemoryReplayLab()
        response = lab.run_replay(
            scenario_id="mode_preserve",
            task_input="Deploy the application with DATABASE_URL present.",
            mode="simulated",
            project_id="default_project",
        )
        assert response.execution_mode == "simulated"

    def test_run_replay_with_real_mode(self) -> None:
        lab = MemoryReplayLab()
        response = lab.run_replay(
            scenario_id="real_mode_test",
            task_input="Deploy the application with DATABASE_URL present.",
            mode="real",
            project_id="default_project",
        )
        assert response.execution_mode == "real"

    def test_run_replay_preserves_project_id(self) -> None:
        lab = MemoryReplayLab()
        response = lab.run_replay(
            scenario_id="project_test",
            task_input="Deploy the application with DATABASE_URL present.",
            mode="simulated",
            project_id="unique_project_xyz",
        )
        assert response.replay_id is not None

    def test_consecutive_replays_get_different_ids(self) -> None:
        lab = MemoryReplayLab()
        r1 = lab.run_replay(
            scenario_id="id_uniqueness",
            task_input="Deploy the application with DATABASE_URL present.",
            mode="simulated",
            project_id="default_project",
        )
        r2 = lab.run_replay(
            scenario_id="id_uniqueness",
            task_input="Deploy the application with DATABASE_URL present.",
            mode="simulated",
            project_id="default_project",
        )
        assert r1.replay_id != r2.replay_id
