"""Tests for ``backend.agent.orchestrator`` and ``backend.evaluation.replay_engine``."""

from __future__ import annotations

import pytest

from backend.agent.environment import SimulatedEnvironment, default_environment
from backend.agent.models import PlanStep
from backend.agent.orchestrator import (
    AgentOrchestrator,
    ExecutionTrace,
    MemoryAttributionRecorder,
    StepTraceRecorder,
    run_task_with_trace,
)
from backend.config import Settings
from backend.domain import OutcomeType
from backend.evaluation.replay_engine import MemoryReplayLab, MetricDelta, replay_task


# --------------------------------------------------------------------------- #
# AgentOrchestrator — basic execution
# --------------------------------------------------------------------------- #

class TestAgentOrchestrator:
    """Instrumented wrapper around ``FailureMemoryAgent``."""

    def _make_env(self) -> SimulatedEnvironment:
        return SimulatedEnvironment(
            id="test-env",
            config={"APP_ENV": "ci"},
            registry={"pandas": "2.2.0"},
            faults={"build_requires": ["pandas"]},
        )

    def test_baseline_mode_produces_trace(self) -> None:
        orch = AgentOrchestrator()
        trace = orch.run_task(
            "Build the project",
            env=self._make_env(),
            mode="baseline",
            max_attempts=1,
        )
        assert isinstance(trace, ExecutionTrace)
        assert trace.execution_mode == "simulated"
        assert not trace.memory_enabled
        assert trace.total_attempts >= 1

    def test_memory_mode_produces_trace(self) -> None:
        orch = AgentOrchestrator()
        trace = orch.run_task(
            "Build the project",
            env=self._make_env(),
            mode="memory",
            max_attempts=1,
        )
        assert isinstance(trace, ExecutionTrace)
        assert trace.memory_enabled is True
        assert trace.total_attempts >= 1

    def test_trace_contains_step_traces(self) -> None:
        orch = AgentOrchestrator()
        env = default_environment()
        trace = orch.run_task(
            "Deploy the app",
            env=env,
            mode="baseline",
            max_attempts=1,
        )
        assert len(trace.steps) > 0
        step = trace.steps[0]
        assert isinstance(step, StepTraceRecorder)
        assert hasattr(step, "step_number")
        assert hasattr(step, "action")
        assert hasattr(step, "tool_call")
        assert hasattr(step, "output")
        assert hasattr(step, "error")

    def test_trace_execution_time_is_positive(self) -> None:
        orch = AgentOrchestrator()
        trace = orch.run_task(
            "Build the project",
            mode="baseline",
            max_attempts=1,
        )
        assert trace.execution_time_ms >= 0

    def test_custom_settings_passthrough(self) -> None:
        settings = Settings(default_max_attempts=3)
        orch = AgentOrchestrator(settings=settings)
        trace = orch.run_task(
            "Build the project",
            mode="baseline",
            max_attempts=1,
        )
        assert isinstance(trace, ExecutionTrace)

    def test_run_task_with_trace_convenience(self) -> None:
        trace = run_task_with_trace("Build the project", mode="baseline")
        assert isinstance(trace, ExecutionTrace)
        assert not trace.memory_enabled


# --------------------------------------------------------------------------- #
# MemoryAttributionRecorder — rejection reasons
# --------------------------------------------------------------------------- #

class TestMemoryAttributionRecorder:
    """Captures how retrieved lessons were used."""

    def test_all_fields_present(self) -> None:
        attr = MemoryAttributionRecorder(
            lesson_id="mem-1",
            lesson_text="install pandas first",
            retrieval_strategy="bm25",
            similarity_score=0.75,
            confidence_score=0.85,
            retrieved=True,
            applied=False,
            rejection_reason="below_confidence_gate",
            is_root_cause_verified=True,
        )
        assert attr.lesson_id == "mem-1"
        assert attr.retrieved is True
        assert attr.applied is False
        assert attr.rejection_reason == "below_confidence_gate"
        assert attr.is_root_cause_verified is True

    def test_frozen_dataclass(self) -> None:
        attr = MemoryAttributionRecorder(lesson_id="x", lesson_text="y")
        with pytest.raises(AttributeError):
            attr.lesson_id = "new"  # type: ignore[assignment]


# --------------------------------------------------------------------------- #
# ExecutionTrace — frozen dataclass
# --------------------------------------------------------------------------- #

class TestExecutionTrace:
    def test_frozen_dataclass(self) -> None:
        trace = ExecutionTrace(execution_mode="simulated")
        with pytest.raises(AttributeError):
            trace.execution_time_ms = 999.0  # type: ignore[assignment]


# --------------------------------------------------------------------------- #
# MetricDelta — computed differences
# --------------------------------------------------------------------------- #

class TestMetricDelta:
    def test_to_dict(self) -> None:
        delta = MetricDelta(
            success_improved=True,
            attempts_saved=2,
            time_saved_ms=150.5,
            memories_applied_count=3,
        )
        d = delta.to_dict()
        assert d["success_improved"] is True
        assert d["attempts_saved"] == 2
        assert d["time_saved_ms"] == 150.5
        assert d["memories_applied_count"] == 3

    def test_default_values(self) -> None:
        delta = MetricDelta()
        d = delta.to_dict()
        assert d["success_improved"] is False
        assert d["attempts_saved"] == 0


# --------------------------------------------------------------------------- #
# MemoryReplayLab — side-by-side comparison
# --------------------------------------------------------------------------- #

class TestMemoryReplayLab:
    def test_run_replay_produces_response(self) -> None:
        lab = MemoryReplayLab()
        result = lab.run_replay(
            scenario_id="test_scenario",
            task_input="Build the project",
            max_attempts=1,
        )
        assert hasattr(result, "replay_id")
        assert hasattr(result, "baseline")
        assert hasattr(result, "treatment")
        assert hasattr(result, "delta")

    def test_baseline_and_treatment_modes(self) -> None:
        lab = MemoryReplayLab()
        result = lab.run_replay(
            scenario_id="test_mode",
            task_input="Build the project",
            max_attempts=1,
        )
        assert result.baseline.execution_mode == "simulated"
        assert not result.baseline.memory_enabled
        assert result.treatment.memory_enabled is True

    def test_delta_computed_from_real_results(self) -> None:
        lab = MemoryReplayLab()
        # Use a scenario where baseline fails and memory succeeds.
        env = SimulatedEnvironment(
            id="delta_test",
            config={"APP_ENV": "ci"},
            registry={"pandas": "2.2.0"},
            faults={"build_requires": ["pandas"]},
        )
        result = lab.run_replay(
            scenario_id="delta_scenario",
            task_input="Build the project",
            environment=env,
            max_attempts=1,
        )
        assert "success_improved" in result.delta
        assert "attempts_saved" in result.delta

    def test_trace_has_step_traces(self) -> None:
        lab = MemoryReplayLab()
        result = lab.run_replay(
            scenario_id="trace_test",
            task_input="Build the project",
            max_attempts=1,
        )
        assert len(result.baseline.steps) > 0 or len(result.treatment.steps) > 0

    def test_convenience_function(self) -> None:
        result = replay_task(
            scenario_id="convenience_test",
            task_input="Build the project",
            max_attempts=1,
        )
        assert hasattr(result, "delta")


# --------------------------------------------------------------------------- #
# Integration — orchestrator + replay together
# --------------------------------------------------------------------------- #

class TestOrchestratorIntegration:
    def test_shared_orchestrator_across_replay(self) -> None:
        """Replay Lab should reuse a single orchestrator for both arms."""
        orch = AgentOrchestrator()
        lab = MemoryReplayLab(orchestrator=orch)
        result1 = lab.run_replay(
            scenario_id="shared_1",
            task_input="Build the project",
            max_attempts=1,
        )
        result2 = lab.run_replay(
            scenario_id="shared_2",
            task_input="Deploy the app",
            max_attempts=1,
        )
        assert result1.replay_id != result2.replay_id
