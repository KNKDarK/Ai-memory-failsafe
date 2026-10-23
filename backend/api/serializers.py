"""Response serialisers.

They turn domain objects into JSON-ready dicts, add the derived fields the UI
needs (for example ``effective_confidence``), and run every string through the
secret redactor so nothing sensitive can leak through the API.
"""

from __future__ import annotations

from typing import Any

from backend.agent.models import ExecutionRecord, TaskRun
from backend.analysis.models import FailureAnalysis
from backend.memory.models import FailureMemory, MemoryFeedback, RetrievalResult
from backend.security import SecretRedactor


def memory_dict(memory: FailureMemory, redactor: SecretRedactor) -> dict[str, Any]:
    data = memory.model_dump(mode="json")
    data["effective_confidence"] = round(memory.effective_confidence, 4)
    data["label"] = memory.label
    # Derived usefulness fields for ranking UIs (never stored, always computed).
    data["uses"] = memory.use_count
    data["success_rate"] = (
        round(memory.success_count / memory.use_count, 4) if memory.use_count else None
    )
    return redactor.redact_mapping(data)


def feedback_dict(feedback: MemoryFeedback, redactor: SecretRedactor) -> dict[str, Any]:
    return redactor.redact_mapping(feedback.model_dump(mode="json"))


def retrieval_dict(result: RetrievalResult, redactor: SecretRedactor) -> dict[str, Any]:
    return {
        "memory": memory_dict(result.memory, redactor),
        "rank": result.rank,
        "score": result.score,
        "similarity": result.similarity,
        "components": result.components.model_dump(mode="json"),
        "matched_terms": list(result.matched_terms),
        "selected": result.selected,
        "reason": redactor.redact(result.reason),
        "retrieval_mode": result.retrieval_mode,
        "retrieval_strategy": result.retrieval_strategy,
    }


def execution_dict(record: ExecutionRecord, redactor: SecretRedactor) -> dict[str, Any]:
    data = record.model_dump(mode="json")
    data["failed_step"] = None
    failed = record.failed_step
    if failed is not None:
        data["failed_step"] = {
            "index": failed.index,
            "attempt": failed.attempt,
            "tool": failed.result.tool,
            "error": redactor.redact(failed.result.error or ""),
            "error_code": failed.result.error_code,
            "outcome_type": failed.result.outcome_type.value,
        }
    return redactor.redact_mapping(data)


def analysis_dict(analysis: FailureAnalysis, redactor: SecretRedactor) -> dict[str, Any]:
    return redactor.redact_mapping(analysis.model_dump(mode="json"))


def run_dict(run: TaskRun, redactor: SecretRedactor) -> dict[str, Any]:
    data = run.model_dump(mode="json")
    data["attempts_used"] = run.attempts_used
    data["duration_ms"] = sum(attempt.duration_ms for attempt in run.attempts)
    data["success"] = run.final_success
    return redactor.redact_mapping(data)
