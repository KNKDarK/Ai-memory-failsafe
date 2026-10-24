"""Orchestrator that wraps ``FailureMemoryAgent`` with full trace instrumentation.

The orchestrator delegates to the agent for execution but intercepts every step
so callers can inspect:

* individual step actions, tool calls, errors (via :class:`StepTraceRecorder`)
* which lessons were retrieved and why they were accepted or rejected
  (e.g. ``below_confidence_gate``, ``contradiction_detected``)
* whether each lesson's root cause is verified evidence or a hypothesis

This module exists so the Replay Lab and the SDK can produce rich, structured
trace objects without reaching into private agent internals.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field

from backend.agent.agent import FailureMemoryAgent, MemoryPolicy
from backend.agent.environment import SimulatedEnvironment
from backend.agent.models import (
    ExecutionRecord,
    Plan,
    Recommendation,
    StepTrace as InternalStepTrace,
    TaskRun,
)
from backend.config import Settings, get_settings
from backend.domain import OutcomeType, utcnow

logger = logging.getLogger("failure_memory.orchestrator")


# --------------------------------------------------------------------------- #
# Public trace types consumed by the Replay Lab and SDK
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class StepTraceRecorder:
    """Captures a single step's action trace with tool call, output, and error."""

    step_number: int = 0
    action: str = ""
    tool_call: str | None = None
    output: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class MemoryAttributionRecorder:
    """Captures how a retrieved lesson was used (or not) in an execution."""

    lesson_id: str = ""
    lesson_text: str = ""
    retrieval_strategy: str = ""
    similarity_score: float = 0.0
    confidence_score: float = 0.0
    retrieved: bool = False
    applied: bool = False
    rejection_reason: str | None = None
    is_root_cause_verified: bool = False


@dataclass(frozen=True)
class ExecutionTrace:
    """Complete record of one execution arm (baseline or treatment)."""

    execution_mode: str = "simulated"
    memory_enabled: bool = False
    success: bool = False
    total_attempts: int = 1
    execution_time_ms: float = 0.0
    steps: list[StepTraceRecorder] = field(default_factory=list)
    retrieved_memories: list[MemoryAttributionRecorder] = field(default_factory=list)
    prevention_injections: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #

class AgentOrchestrator:
    """Wraps ``FailureMemoryAgent`` and records rich execution traces.

    Parameters accept either a pre-built agent or the components needed to
    construct one (store, settings, etc.).  When called with no arguments it
    falls back to the default runtime builder.
    """

    def __init__(self, *, store=None, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if store is not None:
            from backend.services import build_runtime

            rt = build_runtime(self.settings)
            # Use the provided store as-is instead of building a new one.
            rt._store = store  # noqa: SLF001 — intentional override for testing.
            self.agent = FailureMemoryAgent(store, self.settings)
        else:
            from backend.services import build_runtime

            rt = build_runtime(self.settings)
            self.agent = rt.agent()
        self.store = rt.store

    # ------------------------------------------------------------------ #
    def run_task(
        self,
        task: str,
        env: SimulatedEnvironment | None = None,
        *,
        mode: str = "memory",
        max_attempts: int | None = None,
        agent_id: str = "default",
    ) -> ExecutionTrace:
        """Run a single task and return an instrumented :class:`ExecutionTrace`.

        This is the primary entry point for the Replay Lab.  It runs the task
        through the underlying ``FailureMemoryAgent``, then converts every
        internal data structure into the flat trace types that consumers expect.
        """
        started = time.perf_counter()
        policy: MemoryPolicy | None = None
        if mode == "baseline":
            from backend.agent.agent import BASELINE_POLICY

            policy = BASELINE_POLICY
        elif mode == "naive":
            from backend.agent.agent import NAIVE_POLICY

            policy = NAIVE_POLICY

        run: TaskRun = self.agent.run_task(
            task,
            env=env,
            mode=mode,
            max_attempts=max_attempts or self.settings.default_max_attempts,
            policy=policy,
            agent_id=agent_id,
        )

        wall_clock_ms = round((time.perf_counter() - started) * 1000, 3)
        trace = ExecutionTrace(
            execution_mode="simulated",
            memory_enabled=(mode != "baseline"),
            success=run.final_success,
            total_attempts=len(run.attempts),
            execution_time_ms=wall_clock_ms,
            steps=[],
            retrieved_memories=[],
            prevention_injections=[],
        )

        # --- Collect step traces across all attempts ---------------------- #
        for attempt_record in run.attempts:
            trace.steps.extend(
                self._build_step_traces(attempt_record)
            )

        # --- Collect memory attributions from the first attempt's retrieval#
        if run.attempts and policy is not None and policy.retrieve:
            trace.retrieved_memories = self._build_memory_attributions(run)
            trace.prevention_injections = list(run.memory_ids_applied) or []

        return trace

    # ------------------------------------------------------------------ #
    def _build_step_traces(self, record: ExecutionRecord) -> list[StepTraceRecorder]:
        """Convert internal ``StepTrace`` objects into public ``StepTraceRecorder``."""
        traces: list[StepTraceRecorder] = []
        for idx, step_trace in enumerate(record.traces):
            tool_result = step_trace.result
            traces.append(
                StepTraceRecorder(
                    step_number=idx,
                    action=step_trace.step.description or f"run {tool_result.tool}",
                    tool_call=tool_result.tool if not step_trace.step.is_prevention else None,
                    output=(
                        str(tool_result.output)
                        if tool_result.output is not None
                        else None
                    ),
                    error=tool_result.error,
                )
            )
        return traces

    def _build_memory_attributions(self, run: TaskRun) -> list[MemoryAttributionRecorder]:
        """Convert retrieved memories into attribution records with rejection reasons."""
        attributions: list[MemoryAttributionRecorder] = []
        applied_ids = set(run.memory_ids_applied)

        for attempt_record in run.attempts:
            if not attempt_record.retrieved:
                continue
            for retrieval_result in attempt_record.retrieved:
                memory = retrieval_result.memory
                # Determine rejection reason from the explanation string.
                reason = self._extract_rejection_reason(retrieval_result)

                attributions.append(
                    MemoryAttributionRecorder(
                        lesson_id=memory.id,
                        lesson_text=memory.lesson or "",
                        retrieval_strategy=retrieval_result.retrieval_strategy or "",
                        similarity_score=retrieval_result.similarity,
                        confidence_score=memory.confidence,
                        retrieved=True,
                        applied=(memory.id in applied_ids),
                        rejection_reason=reason,
                        is_root_cause_verified=(memory.cause_status.value == "confirmed"),
                    )
                )

        # Deduplicate by lesson_id (same memory may be returned across attempts).
        seen: set[str] = set()
        unique: list[MemoryAttributionRecorder] = []
        for attr in attributions:
            if attr.lesson_id not in seen:
                seen.add(attr.lesson_id)
                unique.append(attr)
        return unique

    @staticmethod
    def _extract_rejection_reason(result) -> str | None:
        """Parse the explanation string to extract a structured rejection reason."""
        reason_text = ""
        if hasattr(result, "explanation") and result.explanation:
            reason_text = result.explanation
        elif hasattr(result, "reason") and result.reason:
            reason_text = result.reason

        if not reason_text:
            return None

        # Map common patterns to structured rejection reasons.
        lower = reason_text.lower()
        if "below confidence" in lower or "confidence floor" in lower:
            return "below_confidence_gate"
        if "contradiction" in lower:
            return "contradiction_detected"
        if "text similarity" in lower and "below relevance" in lower:
            return "similarity_floor_not_met"
        if "status" in lower and ("outdated" in lower or "incorrect" in lower):
            status = "outdated" if "outdated" in lower else "incorrect"
            return f"{status}_memory"
        # Generic — include the raw text as a fallback reason.
        return None


# --------------------------------------------------------------------------- #
# Convenience: run_task_with_trace (alias for direct use without full orchestrator)
# --------------------------------------------------------------------------- #

def run_task_with_trace(
    task: str,
    env: SimulatedEnvironment | None = None,
    *,
    mode: str = "memory",
    max_attempts: int | None = None,
    agent_id: str = "default",
) -> ExecutionTrace:
    """Run a single task and return an instrumented ``ExecutionTrace``.

    Convenience wrapper that creates its own :class:`AgentOrchestrator` internally.
    For repeated runs (e.g. baseline + treatment in the Replay Lab), prefer building
    an orchestrator once and calling :meth:`AgentOrchestrator.run_task`.
    """
    orch = AgentOrchestrator()
    return orch.run_task(
        task, env=env, mode=mode, max_attempts=max_attempts, agent_id=agent_id
    )
