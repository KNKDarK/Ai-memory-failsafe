"""Memory Replay Lab — side-by-side baseline vs treatment execution engine.

The ``MemoryReplayLab`` class runs a task (or evaluation scenario) twice under
identical conditions: once with memory disabled (**baseline**) and once with
memory enabled (**treatment**).  It captures full step traces, memory
attributions with rejection explanations, and measures real wall-clock duration
for each arm.

Metric deltas are computed from the actual execution results — nothing is
mocked or hardcoded.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any

from backend.agent.environment import SimulatedEnvironment
from backend.agent.orchestrator import AgentOrchestrator, ExecutionTrace
from backend.api.schemas.lab import (
    ExecutionTrace as LabExecutionTrace,
)
from backend.api.schemas.lab import (
    MemoryAttribution as LabMemoryAttribution,
)
from backend.api.schemas.lab import (
    ReplayRunResponse,
)
from backend.api.schemas.lab import (
    StepTrace as LabStepTrace,
)

logger = logging.getLogger("failure_memory.replay")


@dataclass(frozen=True)
class MetricDelta:
    """Computed differences between baseline and treatment execution arms."""

    success_improved: bool = False
    attempts_saved: int = 0
    time_saved_ms: float = 0.0
    memories_applied_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MemoryReplayLab:
    """Runs baseline and treatment tasks side-by-side with full trace capture."""

    def __init__(self, orchestrator: AgentOrchestrator | None = None) -> None:
        self.orchestrator = orchestrator or AgentOrchestrator()

    # ------------------------------------------------------------------ #
    def run_replay(
        self,
        scenario_id: str,
        task_input: str,
        mode: str = "simulated",
        project_id: str = "default_project",
        *,
        max_attempts: int | None = None,
        environment: SimulatedEnvironment | None = None,
    ) -> ReplayRunResponse:
        """Execute a side-by-side baseline vs treatment comparison.

        Parameters
        ----------
        scenario_id:
            Identifier of the evaluation scenario (or arbitrary task label).
        task_input:
            The task description / prompt used for both arms.
        mode:
            Execution environment — ``"simulated"`` (default) or ``"real"``.
        project_id:
            Project identifier for grouping replay runs.
        max_attempts:
            Maximum number of attempts per arm.  Falls back to the orchestrator's
            settings default when omitted.
        environment:
            Optional sandboxed environment override.  When provided it is cloned
            so both arms see identical conditions.

        Returns
        -------
        ReplayRunResponse with baseline and treatment :class:`LabExecutionTrace`
        objects plus a computed ``delta`` dict.
        """
        replay_id = uuid.uuid4().hex[:12]
        logger.info(
            "Replay run %s — scenario=%s mode=%s project=%s",
            replay_id,
            scenario_id,
            mode,
            project_id,
        )

        # Clone the environment so both arms see identical conditions.
        env_clone = environment.clone() if environment is not None else None

        # --- Baseline arm (memory disabled) ----------------------------- #
        baseline_trace = self._run_arm(
            task_input,
            env_clone,
            mode="baseline",
            max_attempts=max_attempts,
        )

        # --- Treatment arm (memory enabled) ---------------------------- #
        treatment_trace = self._run_arm(
            task_input,
            env_clone,
            mode="memory",
            max_attempts=max_attempts,
        )

        # --- Compute real metric deltas -------------------------------- #
        delta = self._compute_delta(baseline_trace, treatment_trace)

        return ReplayRunResponse(
            replay_id=replay_id,
            scenario_id=scenario_id,
            execution_mode=mode,
            baseline=self._to_lab_trace(baseline_trace),
            treatment=self._to_lab_trace(treatment_trace),
            delta=delta.to_dict(),
        )

    # ------------------------------------------------------------------ #
    def _run_arm(
        self,
        task_input: str,
        env: SimulatedEnvironment | None,
        *,
        mode: str,
        max_attempts: int | None = None,
    ) -> ExecutionTrace:
        """Execute one arm (baseline or treatment) and return an instrumented trace."""
        start = time.perf_counter()

        try:
            trace = self.orchestrator.run_task(
                task_input,
                env=env,
                mode=mode,
                max_attempts=max_attempts,
            )
        except Exception as exc:  # noqa: BLE001 — capture failure, don't crash the replay
            logger.error("Arm %s failed: %s", mode, exc)
            elapsed = round((time.perf_counter() - start) * 1000, 3)
            return ExecutionTrace(
                execution_mode=mode,
                memory_enabled=(mode != "baseline"),
                success=False,
                total_attempts=1,
                execution_time_ms=elapsed,
                steps=[],
                retrieved_memories=[],
                prevention_injections=[],
            )

        elapsed = round((time.perf_counter() - start) * 1000, 3)
        # Return a new frozen trace with the actual wall-clock duration.
        return ExecutionTrace(
            execution_mode=trace.execution_mode,
            memory_enabled=trace.memory_enabled,
            success=trace.success,
            total_attempts=trace.total_attempts,
            execution_time_ms=elapsed,
            steps=list(trace.steps),
            retrieved_memories=list(trace.retrieved_memories),
            prevention_injections=list(trace.prevention_injections),
        )

    @staticmethod
    def _compute_delta(baseline: ExecutionTrace, treatment: ExecutionTrace) -> MetricDelta:
        """Compute real metric deltas between two execution arms."""
        success_improved = (not baseline.success) and treatment.success
        attempts_saved = max(0, baseline.total_attempts - treatment.total_attempts)

        time_saved_ms = round(baseline.execution_time_ms - treatment.execution_time_ms, 3)

        # Count unique memories applied in the treatment arm.
        applied_ids: set[str] = set()
        for attr in treatment.retrieved_memories:
            if attr.applied:
                applied_ids.add(attr.lesson_id)
        # Also count prevention injections that may not appear in attributions.
        applied_ids.update(treatment.prevention_injections)

        return MetricDelta(
            success_improved=success_improved,
            attempts_saved=attempts_saved,
            time_saved_ms=time_saved_ms,
            memories_applied_count=len(applied_ids),
        )

    # ------------------------------------------------------------------ #
    @staticmethod
    def _to_lab_trace(trace: ExecutionTrace) -> LabExecutionTrace:
        """Convert an internal ``ExecutionTrace`` to a lab schema model."""
        return LabExecutionTrace(
            execution_mode=trace.execution_mode,
            memory_enabled=trace.memory_enabled,
            success=trace.success,
            total_attempts=trace.total_attempts,
            execution_time_ms=trace.execution_time_ms,
            steps=[
                LabStepTrace(
                    step_number=s.step_number,
                    action=s.action,
                    tool_call=s.tool_call,
                    output=s.output,
                    error=s.error,
                )
                for s in trace.steps
            ],
            retrieved_memories=[
                LabMemoryAttribution(
                    lesson_id=a.lesson_id,
                    lesson_text=a.lesson_text,
                    retrieval_strategy=a.retrieval_strategy,
                    similarity_score=a.similarity_score,
                    confidence_score=a.confidence_score,
                    retrieved=a.retrieved,
                    applied=a.applied,
                    rejection_reason=a.rejection_reason,
                    is_root_cause_verified=a.is_root_cause_verified,
                )
                for a in trace.retrieved_memories
            ],
            prevention_injections=list(trace.prevention_injections),
        )


# --------------------------------------------------------------------------- #
# Convenience: replay_task (one-liner)
# --------------------------------------------------------------------------- #


def replay_task(
    scenario_id: str,
    task_input: str,
    mode: str = "simulated",
    project_id: str = "default_project",
    *,
    max_attempts: int | None = None,
    environment: SimulatedEnvironment | None = None,
) -> ReplayRunResponse:
    """One-liner to run a baseline vs treatment replay comparison.

    Creates its own :class:`MemoryReplayLab` internally.  For repeated runs or
    shared orchestrators, prefer building the lab explicitly.
    """
    lab = MemoryReplayLab()
    return lab.run_replay(
        scenario_id=scenario_id,
        task_input=task_input,
        mode=mode,
        project_id=project_id,
        max_attempts=max_attempts,
        environment=environment,
    )
