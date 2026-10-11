"""Shared domain enumerations and small value types.

Keeping these in one module avoids circular imports between the memory,
analysis, agent, and evaluation packages.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum


def utcnow() -> datetime:
    """Timezone-aware UTC now (single source of truth for timestamps)."""
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Normalise a datetime to timezone-aware UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class OutcomeType(StrEnum):
    """How an attempt ended.

    This distinction matters: a *tool failure* is a tool raising an error,
    while a *task failure* means the tools ran but the task goal was not met.
    """

    SUCCESS = "success"
    TASK_FAILURE = "task_failure"
    TOOL_FAILURE = "tool_failure"
    TIMEOUT = "timeout"
    INVALID_OUTPUT = "invalid_output"

    @property
    def is_failure(self) -> bool:
        return self is not OutcomeType.SUCCESS


class FailureCategory(StrEnum):
    """High-level classification used for lesson extraction and prevention."""

    MISSING_CONFIGURATION = "missing_configuration"
    MISSING_DEPENDENCY = "missing_dependency"
    INVALID_API_RESPONSE = "invalid_api_response"
    TOOL_TIMEOUT = "tool_timeout"
    INCORRECT_ASSUMPTION = "incorrect_assumption"
    PERMISSION_DENIED = "permission_denied"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    UNKNOWN = "unknown"


class CauseStatus(StrEnum):
    """Whether a root cause is verified evidence or a plausible hypothesis."""

    CONFIRMED = "confirmed"
    HYPOTHESIS = "hypothesis"


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    OUTDATED = "outdated"
    INCORRECT = "incorrect"
    ARCHIVED = "archived"


class FeedbackVerdict(StrEnum):
    USEFUL = "useful"
    UNHELPFUL = "unhelpful"
    OUTDATED = "outdated"
    INCORRECT = "incorrect"
