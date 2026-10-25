"""Pydantic schemas for the Memory Replay Lab.

These models power the replay-run endpoints that compare a simulated baseline
execution against a memory-enabled treatment run and report the delta between them.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StepTrace(BaseModel):
    """A single step inside an execution trace."""

    model_config = ConfigDict(extra="forbid")

    step_number: int = Field(..., ge=0, description="Zero-based index of the step in the plan.")
    action: str = Field(
        ...,
        min_length=1,
        max_length=512,
        description="Human-readable description of what this step attempted.",
    )
    tool_call: str | None = Field(
        default=None,
        max_length=1024,
        description="Name or identifier of the tool invoked (if any).",
    )
    output: str | None = Field(
        default=None,
        max_length=8192,
        description="Structured or plain-text result produced by this step.",
    )
    error: str | None = Field(
        default=None,
        max_length=4096,
        description="Error message if the step failed (None on success).",
    )


class MemoryAttribution(BaseModel):
    """Describes how a retrieved failure-memory lesson was used in an execution."""

    model_config = ConfigDict(extra="forbid")

    lesson_id: str = Field(
        ...,
        min_length=1,
        description="Unique identifier of the referenced failure memory.",
    )
    lesson_text: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        description="The extracted lesson text that was retrieved.",
    )
    retrieval_strategy: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Retrieval strategy used (e.g. 'bm25', 'tfidf', 'embedding', 'hybrid').",
    )
    similarity_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Similarity score between the current task and this memory.",
    )
    confidence_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence of the lesson at retrieval time.",
    )
    retrieved: bool = Field(
        ...,
        description="Whether this memory was surfaced by the retriever for this run.",
    )
    applied: bool = Field(
        ...,
        description="Whether this memory was injected into the execution plan.",
    )
    rejection_reason: str | None = Field(
        default=None,
        max_length=1024,
        description=(
            "Reason the lesson was retrieved but not applied (e.g. low confidence, "
            "contradiction, incorrect status)."
        ),
    )
    is_root_cause_verified: bool = Field(
        ...,
        description="Whether the root cause of this memory's source failure is confirmed.",
    )


class ExecutionTrace(BaseModel):
    """Complete record of one execution arm (baseline or treatment)."""

    model_config = ConfigDict(extra="forbid")

    execution_mode: Literal["simulated", "real"] = Field(
        ...,
        description="Whether the run was executed against a simulated sandbox or real tools.",
    )
    memory_enabled: bool = Field(
        ...,
        description="Whether failure-memory retrieval and injection were active.",
    )
    success: bool = Field(
        ...,
        description="Whether the task completed successfully.",
    )
    total_attempts: int = Field(
        ...,
        ge=1,
        description="Total number of attempts made to complete the task.",
    )
    execution_time_ms: float = Field(
        ...,
        ge=0.0,
        description="Wall-clock time for this execution arm in milliseconds.",
    )
    steps: list[StepTrace] = Field(
        default_factory=list,
        description="Ordered sequence of steps executed during this run.",
    )
    retrieved_memories: list[MemoryAttribution] = Field(
        default_factory=list,
        description="All memories considered for this execution with their attribution.",
    )
    prevention_injections: list[str] = Field(
        default_factory=list,
        max_length=64,
        description=("Prevention actions that were injected into the plan from retrieved lessons."),
    )


class ReplayRunRequest(BaseModel):
    """Payload to trigger a side-by-side replay comparison run."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Identifier of the evaluation scenario to replay.",
    )
    task_input: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        description="The task input or prompt used for both baseline and treatment runs.",
    )
    execution_mode: Literal["simulated", "real"] = Field(
        default="simulated",
        description="Execution environment mode (default: 'simulated').",
    )
    project_id: str = Field(
        default="default_project",
        min_length=1,
        max_length=256,
        description="Project identifier for grouping replay runs.",
    )


class ReplayRunResponse(BaseModel):
    """Result of a side-by-side baseline vs treatment replay comparison."""

    model_config = ConfigDict(extra="forbid")

    replay_id: str = Field(
        ...,
        min_length=1,
        description="Unique identifier for this replay run.",
    )
    scenario_id: str = Field(
        ...,
        description="Scenario that was replayed.",
    )
    execution_mode: Literal["simulated", "real"] = Field(
        ...,
        description="Execution mode used for the comparison.",
    )
    baseline: ExecutionTrace = Field(
        ...,
        description="Results from the no-memory baseline run.",
    )
    treatment: ExecutionTrace = Field(
        ...,
        description="Results from the memory-enabled treatment run.",
    )
    delta: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Computed differences between baseline and treatment (success rates, time deltas, "
            "prevention counts, etc.)."
        ),
    )
