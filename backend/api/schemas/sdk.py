"""Pydantic schemas for the v1 Developer SDK endpoints.

These models power the public-facing lesson query, failure recording, and
feedback APIs that external agents or tooling can call against a running
failure-memory instance.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class QueryLessonsRequest(BaseModel):
    """Search for relevant past failure lessons."""

    model_config = ConfigDict(extra="forbid")

    task_description: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        description="The current task or prompt to find relevant past failures for.",
    )
    project_id: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Project identifier to scope the search within a single project's memories.",
    )
    agent_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Agent requesting lessons; used for per-agent statistics and cross-agent sharing.",
    )
    min_confidence: float = Field(
        default=0.65,
        ge=0.0,
        le=1.0,
        description=(
            "Minimum confidence threshold for returned lessons. "
            "Lessons below this are filtered out (default 0.65)."
        ),
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Maximum number of lessons to return (default 5).",
    )


class LessonDTO(BaseModel):
    """A single lesson returned by the query-lessons endpoint."""

    model_config = ConfigDict(extra="forbid")

    lesson_id: str = Field(
        ...,
        min_length=1,
        description="Unique identifier of the failure memory.",
    )
    failure_mode: str = Field(
        ...,
        min_length=1,
        max_length=512,
        description="High-level classification of the original failure (e.g. 'missing_dependency').",
    )
    lesson_text: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        description="The actionable lesson extracted from the past failure.",
    )
    prevention_action: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        description="Concrete step the agent should take to avoid repeating this failure.",
    )
    confidence_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence that this lesson is reliable and applicable (0-1).",
    )
    verified: bool = Field(
        ...,
        description="Whether the root cause of this lesson's source failure is confirmed.",
    )


class QueryLessonsResponse(BaseModel):
    """Response body for a lessons query."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(
        ...,
        description="The task description that was searched against.",
    )
    lessons_found: int = Field(
        ...,
        ge=0,
        description="Total number of lessons returned (may be less than top_k).",
    )
    lessons: list[LessonDTO] = Field(
        default_factory=list,
        description="Ranked list of relevant past failure lessons.",
    )


class RecordFailureRequest(BaseModel):
    """Report a task failure so the system can extract and store a lesson."""

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Project identifier for grouping failures.",
    )
    agent_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Agent that encountered the failure.",
    )
    task_input: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        description="The original task or prompt that led to this failure.",
    )
    action_trace: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Ordered sequence of tool calls and their results leading up to the failure."
        ),
    )
    error_message: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        description="The error or exception message that caused this failure.",
    )


class RecordFailureResponse(BaseModel):
    """Result of recording a new failure and extracting a lesson."""

    model_config = ConfigDict(extra="forbid")

    lesson_id: str = Field(
        ...,
        min_length=1,
        description="Unique identifier of the newly created or merged lesson.",
    )
    root_cause: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        description="The identified root cause of this failure.",
    )
    lesson_extracted: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        description="The actionable lesson extracted from this failure event.",
    )
    confidence_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Initial confidence score for the newly created lesson (0-1).",
    )
    is_verified: bool = Field(
        ...,
        description="Whether the root cause was confirmed by evidence.",
    )


class FeedbackRequest(BaseModel):
    """Submit feedback on a previously retrieved lesson to update its effectiveness."""

    model_config = ConfigDict(extra="forbid")

    lesson_id: str = Field(
        ...,
        min_length=1,
        description="Identifier of the lesson being rated.",
    )
    agent_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Agent providing the feedback.",
    )
    task_success: bool = Field(
        ...,
        description="Whether the task succeeded after applying this lesson.",
    )
    project_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        description=(
            "Optional project identifier for per-project feedback aggregation. "
            "If omitted, feedback is global across projects."
        ),
    )
