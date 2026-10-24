"""Schemas package — Replay Lab and Developer SDK models plus legacy API schemas.

Re-exports everything from submodules so existing imports like
``from backend.api import schemas; schemas.EnvironmentSpec`` continue to work
without changes.
"""

from __future__ import annotations

# Legacy request schemas (preserved for backward compatibility)
from backend.api.schemas._legacy import (
    LLMEvaluationRequest,
    _MAX_ENV_KEY_LENGTH,
    _check_env_structure,
    _validate_agent_id,
    _validate_task,
    CompareTasksRequest,
    CrossAgentRunRequest,
    EnvironmentSpec,
    EvaluationRunRequest,
    FeedbackRequest,
    FeedbackRequest as LegacyFeedbackRequest,  # noqa: F401
    RetrievalPreviewRequest,
    RunTaskRequest,
    StatusRequest,
)

# Replay Lab schemas
from backend.api.schemas.lab import (
    ExecutionTrace,
    MemoryAttribution,
    ReplayRunRequest,
    ReplayRunResponse,
    StepTrace,
)

# Developer SDK schemas
from backend.api.schemas.sdk import (
    FeedbackRequest as SdkFeedbackRequest,  # noqa: F401
    LessonDTO,
    QueryLessonsRequest,
    QueryLessonsResponse,
    RecordFailureRequest,
    RecordFailureResponse,
)

__all__ = [
    # Legacy
    "_MAX_ENV_KEY_LENGTH",
    "_check_env_structure",
    "_validate_agent_id",
    "_validate_task",
    "CompareTasksRequest",
    "CrossAgentRunRequest",
    "EnvironmentSpec",
    "EvaluationRunRequest",
    "FeedbackRequest",
    "LegacyFeedbackRequest",
    "LLMEvaluationRequest",
    "RetrievalPreviewRequest",
    "RunTaskRequest",
    "StatusRequest",
    # Replay Lab
    "ExecutionTrace",
    "MemoryAttribution",
    "ReplayRunRequest",
    "ReplayRunResponse",
    "StepTrace",
    # Developer SDK
    "LessonDTO",
    "QueryLessonsRequest",
    "QueryLessonsResponse",
    "RecordFailureRequest",
    "RecordFailureResponse",
    "SdkFeedbackRequest",
]
