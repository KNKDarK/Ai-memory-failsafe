"""Ranking of retrieved memories.

The final score blends four signals so retrieval is explainable:

``score = w_sim * similarity + w_conf * confidence + w_recency * recency
          + w_feedback * feedback``

and the result is multiplied by a status penalty (outdated/incorrect memories
are down-weighted rather than silently trusted).
"""

from __future__ import annotations

import math
from datetime import datetime

from backend.domain import ensure_utc, utcnow
from backend.memory.models import (
    FailureMemory,
    RetrievalComponents,
    status_penalty,
)


def recency_score(
    moment: datetime | None,
    *,
    now: datetime | None = None,
    half_life_days: float = 30.0,
) -> float:
    """Exponential decay in [0, 1]; ``half_life_days`` is the half-life."""
    if moment is None:
        return 0.0
    now = ensure_utc(now or utcnow())
    age_days = max(0.0, (now - ensure_utc(moment)).total_seconds() / 86400.0)
    if half_life_days <= 0:
        return 1.0
    return float(math.pow(0.5, age_days / half_life_days))


def feedback_score(memory: FailureMemory) -> float:
    """Laplace-smoothed helpfulness in [0, 1] (0.5 when never rated)."""
    helpful = memory.helpful_count
    unhelpful = memory.unhelpful_count
    return (helpful + 1.0) / (helpful + unhelpful + 2.0)


class MemoryRanker:
    """Combines retrieval signals into a single, explainable score."""

    def __init__(self, settings) -> None:
        self.w_similarity = settings.weight_similarity
        self.w_confidence = settings.weight_confidence
        self.w_recency = settings.weight_recency
        self.w_feedback = settings.weight_feedback
        self.half_life_days = settings.recency_half_life_days

    def score(
        self,
        memory: FailureMemory,
        similarity: float,
        *,
        now: datetime | None = None,
    ) -> tuple[float, RetrievalComponents]:
        now = ensure_utc(now or utcnow())
        similarity = max(0.0, min(1.0, similarity))
        confidence = memory.effective_confidence
        recency = recency_score(
            memory.last_used_at or memory.created_at, now=now, half_life_days=self.half_life_days
        )
        feedback = feedback_score(memory)

        raw = (
            self.w_similarity * similarity
            + self.w_confidence * confidence
            + self.w_recency * recency
            + self.w_feedback * feedback
        )
        penalty = status_penalty(memory.status)
        final = raw * penalty

        components = RetrievalComponents(
            similarity=round(similarity, 4),
            confidence=round(confidence, 4),
            recency=round(recency, 4),
            feedback=round(feedback, 4),
            status_penalty=round(penalty, 4),
        )
        return round(final, 6), components

    def explain(
        self,
        memory: FailureMemory,
        components: RetrievalComponents,
        matched_terms: list[str],
        similarity_mode: str,
    ) -> str:
        """Human-readable justification for why a memory ranked where it did."""
        parts = [
            f"matched {len(matched_terms)} term(s)"
            + (f" ({', '.join(matched_terms[:6])})" if matched_terms else ""),
            f"text similarity {components.similarity:.2f} ({similarity_mode})",
            f"confidence {components.confidence:.2f}",
            f"recency {components.recency:.2f}",
            f"feedback {components.feedback:.2f}",
        ]
        if components.status_penalty < 1.0:
            parts.append(f"status penalty x{components.status_penalty:.2f} ({memory.status.value})")
        return "; ".join(parts)
