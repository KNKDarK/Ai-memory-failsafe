"""Models produced by the failure-analysis layer."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from backend.domain import CauseStatus, FailureCategory, utcnow


class CauseCandidate(BaseModel):
    """A possible root cause with a supporting score and evidence."""

    model_config = ConfigDict(extra="forbid")

    category: FailureCategory
    cause: str
    confidence: float = 0.0
    confirmed: bool = False
    error_code: str | None = None
    tool: str | None = None
    evidence: list[str] = Field(default_factory=list)


class FailureAnalysis(BaseModel):
    """Structured result of analysing a failed attempt."""

    model_config = ConfigDict(extra="forbid")

    execution_id: str
    task: str
    task_type: str
    action: str
    failure: str
    failure_category: FailureCategory = FailureCategory.UNKNOWN

    root_cause: str
    cause_status: CauseStatus = CauseStatus.HYPOTHESIS
    confidence: float = 0.5
    evidence: list[str] = Field(default_factory=list)

    lesson: str
    prevention: str
    prevention_actions: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    alternatives: list[CauseCandidate] = Field(default_factory=list)
    analyzer: str = "rule_based"
    created_at: datetime = Field(default_factory=utcnow)
