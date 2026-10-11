"""Structured failure-memory models.

A failure memory is *not* just an error string. It captures the task, the failed
action, the evidence, a probable root cause (explicitly marked as confirmed or a
hypothesis), an actionable lesson, a prevention strategy, a confidence score,
and the observed outcomes of applying it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.domain import (
    CauseStatus,
    FailureCategory,
    FeedbackVerdict,
    MemoryStatus,
    ensure_utc,
    utcnow,
)

SCHEMA_VERSION = 1

_STATUS_PENALTY: dict[MemoryStatus, float] = {
    MemoryStatus.ACTIVE: 1.0,
    MemoryStatus.OUTDATED: 0.5,
    MemoryStatus.INCORRECT: 0.05,
    MemoryStatus.ARCHIVED: 0.0,
}


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def status_penalty(status: MemoryStatus) -> float:
    """Multiplier applied to a memory's trust based on its lifecycle status."""
    return _STATUS_PENALTY.get(status, 1.0)


class MemoryFeedback(BaseModel):
    """A piece of human or system feedback about a memory."""

    model_config = ConfigDict(extra="forbid")

    id: str
    memory_id: str
    verdict: FeedbackVerdict
    comment: str = ""
    execution_id: str | None = None
    applied: bool = False
    created_at: datetime = Field(default_factory=utcnow)

    @field_validator("created_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class FailureMemory(BaseModel):
    """A single reusable failure lesson."""

    model_config = ConfigDict(extra="forbid")

    id: str
    schema_version: int = SCHEMA_VERSION

    # --- What failed -----------------------------------------------------
    task: str
    task_type: str = "generic"
    action: str = ""
    failure: str
    failure_category: FailureCategory = FailureCategory.UNKNOWN

    # --- Why it failed ---------------------------------------------------
    root_cause: str
    cause_status: CauseStatus = CauseStatus.HYPOTHESIS
    evidence: list[str] = Field(default_factory=list)

    # --- What to do differently -----------------------------------------
    lesson: str
    prevention: str
    prevention_actions: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    # --- Trust -----------------------------------------------------------
    confidence: float = 0.5
    status: MemoryStatus = MemoryStatus.ACTIVE

    # --- Usage statistics ------------------------------------------------
    occurrence_count: int = 1
    use_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    helpful_count: int = 0
    unhelpful_count: int = 0

    # --- Provenance / lifecycle -----------------------------------------
    source_execution_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    last_used_at: datetime | None = None

    @field_validator("created_at", "updated_at", "last_used_at")
    @classmethod
    def _aware_dt(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_utc(value)

    @field_validator("task", "failure", "root_cause", "lesson", "prevention")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("field must not be blank")
        return value.strip()

    @field_validator("confidence")
    @classmethod
    def _valid_confidence(cls, value: float) -> float:
        return _clamp(float(value))

    @field_validator("evidence", "prevention_actions", "tags")
    @classmethod
    def _clean_list(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for item in value:
            if item is None:
                continue
            text = str(item).strip()
            if text and text not in cleaned:
                cleaned.append(text)
        return cleaned

    @field_validator(
        "occurrence_count",
        "use_count",
        "success_count",
        "failure_count",
        "helpful_count",
        "unhelpful_count",
    )
    @classmethod
    def _non_negative(cls, value: int) -> int:
        return max(0, int(value))

    # --- Derived values --------------------------------------------------
    @property
    def effective_confidence(self) -> float:
        """Confidence adjusted by observed use outcomes and memory status.

        We treat ``confidence`` as the mean of a Beta prior with two pseudo
        observations, add real success/failure counts, and take the posterior
        mean. A status penalty then down-weights outdated/incorrect memories.
        This makes a memory that has repeatedly *caused* failures lose trust
        even if it was stored with high initial confidence.
        """
        prior_weight = 2.0
        alpha = prior_weight * self.confidence + self.success_count + self.helpful_count
        beta = prior_weight * (1.0 - self.confidence) + self.failure_count + self.unhelpful_count
        posterior = alpha / (alpha + beta) if (alpha + beta) > 0 else self.confidence
        return _clamp(posterior * status_penalty(self.status))

    @property
    def label(self) -> str:
        """Short human-readable summary used in logs and the UI."""
        return f"{self.task_type}:{self.action} -> {self.failure_category.value}"


class RetrievalQuery(BaseModel):
    """Input to the memory retriever."""

    model_config = ConfigDict(extra="forbid")

    text: str = ""
    task_type: str | None = None
    action: str | None = None
    tags: list[str] = Field(default_factory=list)
    limit: int = 5
    min_score: float = 0.0
    include_inactive: bool = False


class RetrievalComponents(BaseModel):
    """Score breakdown so a retrieval decision can be explained."""

    model_config = ConfigDict(extra="forbid")

    similarity: float = 0.0
    confidence: float = 0.0
    recency: float = 0.0
    feedback: float = 0.0
    status_penalty: float = 1.0


class RetrievalResult(BaseModel):
    """A ranked memory plus *why* it was selected."""

    model_config = ConfigDict(extra="forbid")

    memory: FailureMemory
    rank: int = 0
    score: float = 0.0
    similarity: float = 0.0
    components: RetrievalComponents = Field(default_factory=RetrievalComponents)
    matched_terms: list[str] = Field(default_factory=list)
    selected: bool = True
    reason: str = ""
    retrieval_mode: Literal[
        "hashing_embedding",
        "tfidf_fallback",
        "neural_embedding",
        "bm25_lexical",
        "hybrid_lexical_embedding",
    ] = "tfidf_fallback"
