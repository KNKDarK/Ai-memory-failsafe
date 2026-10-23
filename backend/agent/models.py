"""Data models for agent execution, plans, traces, and recommendations."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.analysis.models import FailureAnalysis
from backend.domain import OutcomeType, utcnow
from backend.memory.models import RetrievalResult

ExecutionMode = Literal["baseline", "naive", "memory"]


class ToolResult(BaseModel):
    """Result of a single tool invocation."""

    model_config = ConfigDict(extra="forbid")

    tool: str
    ok: bool
    outcome_type: OutcomeType = OutcomeType.SUCCESS
    output: Any = None
    error: str | None = None
    error_code: str | None = None
    evidence: list[str] = Field(default_factory=list)
    duration_ms: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlanStep(BaseModel):
    """One step in an execution plan."""

    model_config = ConfigDict(extra="forbid")

    id: str
    tool: str
    description: str = ""
    args: dict[str, Any] = Field(default_factory=dict)
    is_prevention: bool = False
    prevention_source: str | None = None
    optional: bool = False


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str
    task_type: str
    steps: list[PlanStep] = Field(default_factory=list)
    goal_flags: list[str] = Field(default_factory=list)
    strategy: str = "default"
    notes: list[str] = Field(default_factory=list)


class StepTrace(BaseModel):
    """A recorded (tool call, result) pair, with attempt number."""

    model_config = ConfigDict(extra="forbid")

    index: int
    attempt: int = 1
    step: PlanStep
    result: ToolResult


class Recommendation(BaseModel):
    """A memory-derived preventive recommendation and whether it was applied."""

    model_config = ConfigDict(extra="forbid")

    memory_id: str
    prevention: str
    prevention_actions: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    applicable: bool = False
    applied: bool = False
    reason: str = ""
    followed: bool | None = None


class ExecutionRecord(BaseModel):
    """A complete, reproducible record of one task attempt."""

    model_config = ConfigDict(extra="forbid")

    execution_id: str
    task: str
    task_type: str = "generic"
    mode: ExecutionMode = "baseline"
    environment_id: str = "default"
    plan: Plan
    traces: list[StepTrace] = Field(default_factory=list)
    outcome: OutcomeType = OutcomeType.SUCCESS
    success: bool = False
    attempts: int = 1
    retries: int = 0
    error: str | None = None
    error_code: str | None = None
    applied_memory_ids: list[str] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    retrieved: list[RetrievalResult] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime = Field(default_factory=utcnow)
    duration_ms: int = 0
    fingerprint: str = ""

    @property
    def failed_step(self) -> StepTrace | None:
        for trace in reversed(self.traces):
            if not trace.result.ok:
                return trace
        return None


class TaskRun(BaseModel):
    """A full task run: one or more attempts, plus what memory was used/learned."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    task: str
    task_type: str = "generic"
    mode: ExecutionMode = "baseline"
    agent_id: str = "default"
    environment_id: str = "default"
    max_attempts: int = 1
    attempts: list[ExecutionRecord] = Field(default_factory=list)
    final_success: bool = False
    final_outcome: OutcomeType = OutcomeType.SUCCESS
    memory_ids_applied: list[str] = Field(default_factory=list)
    memory_ids_created: list[str] = Field(default_factory=list)
    memory_ids_reinforced: list[str] = Field(default_factory=list)
    retrieved_memory_ids: list[str] = Field(default_factory=list)
    # Memory ids the *model* was shown and suggested applying (LLM planner
    # arms only). The controller's trust gates decide what is actually
    # applied (``memory_ids_applied``); comparing the two is part of the
    # LLM benchmark's analysis.
    llm_suggested_memory_ids: list[str] = Field(default_factory=list)
    # Per-attempt automatic retrieval-strategy outcomes (adaptive mode only).
    strategy_selections: list[dict[str, Any]] = Field(default_factory=list)
    prevented_failure: bool = False
    prevention_evidence: str = ""
    analyses: list[FailureAnalysis] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime = Field(default_factory=utcnow)

    @property
    def attempts_used(self) -> int:
        return len(self.attempts)
