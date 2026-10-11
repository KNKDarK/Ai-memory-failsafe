"""Failure analyzer: orchestrates root-cause detection and lesson extraction.

An optional, explicitly-enabled LLM may *refine* the wording of a diagnosis, but
it can never upgrade a hypothesis into a confirmed cause: confirmation is tied
to machine-checkable evidence and stays under the rule-based analyzer's control.
"""

from __future__ import annotations

import logging

from backend.agent.models import ExecutionRecord
from backend.analysis.lesson_extractor import extract_lesson
from backend.analysis.models import FailureAnalysis
from backend.analysis.root_cause import analyze_root_cause
from backend.domain import CauseStatus
from backend.llm.provider import LLMProvider, make_llm_provider
from backend.security import SecretRedactor, build_default_redactor

logger = logging.getLogger("failure_memory.analyzer")


class FailureAnalyzer:
    def __init__(
        self,
        settings=None,
        *,
        llm: LLMProvider | None = None,
        redactor: SecretRedactor | None = None,
    ) -> None:
        if settings is None:
            from backend.config import Settings

            settings = Settings.from_env()
        self.settings = settings
        self.redactor = redactor or build_default_redactor(settings)
        self.llm = llm if llm is not None else make_llm_provider(settings)

    # ------------------------------------------------------------------ #
    def analyze(self, execution: ExecutionRecord) -> FailureAnalysis:
        root = analyze_root_cause(execution)
        lesson = extract_lesson(root, execution)
        failure_trace = execution.failed_step

        failure_text = (
            failure_trace.result.error
            if failure_trace and failure_trace.result.error
            else (execution.error or "task did not reach its goal")
        )

        analysis = FailureAnalysis(
            execution_id=execution.execution_id,
            task=execution.task,
            task_type=execution.task_type,
            action=str(lesson["action"]),
            failure=self._clean(failure_text),
            failure_category=root.category,
            root_cause=self._clean(root.cause),
            cause_status=root.status,
            confidence=root.confidence,
            evidence=[self._clean(e) for e in root.evidence],
            lesson=self._clean(str(lesson["lesson"])),
            prevention=self._clean(str(lesson["prevention"])),
            prevention_actions=[str(a) for a in lesson["prevention_actions"]],
            tags=[str(t) for t in lesson["tags"]],
            alternatives=root.alternatives,
            analyzer="rule_based",
        )

        refined = self._maybe_refine(analysis)
        return refined or analysis

    # ------------------------------------------------------------------ #
    def _maybe_refine(self, analysis: FailureAnalysis) -> FailureAnalysis | None:
        """Optionally refine wording with a real LLM (never despite evidence)."""
        if not getattr(self.llm, "is_real", False):
            return None
        prompt = (
            "You are analysing an AI agent failure for a reusable failure-memory. "
            "From the structured facts below ONLY (do not invent facts), identify:\n"
            "1. the immediate symptom (what was observed);\n"
            "2. the underlying root cause (why it happened); it must explain, not "
            "merely restate the symptom (e.g. 'file not found' is a symptom, not a "
            "root cause);\n"
            "3. a generalizable lesson (a rule that also holds for other tasks);\n"
            "4. a prevention strategy (a reusable process improvement, never a "
            "one-off fix — 'create config/prod.json' is a one-off, but 'validate "
            "deployment prerequisites before execution' is reusable).\n\n"
            "Return JSON with keys root_cause, lesson, prevention (all strings) and "
            "confidence (0..1). Do not upgrade a hypothesis into a confirmed cause.\n\n"
            f"task: {analysis.task}\n"
            f"failed_action: {analysis.action}\n"
            f"failure: {analysis.failure}\n"
            f"category: {analysis.failure_category.value}\n"
            f"rule_based_root_cause: {analysis.root_cause}\n"
            f"cause_status: {analysis.cause_status.value}\n"
            f"evidence: {analysis.evidence}\n"
        )
        try:
            payload = self.llm.complete_json(prompt)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 - provider boundary, must never crash analysis
            logger.warning(
                "LLM refinement unavailable (%s); using rule-based analysis",
                type(exc).__name__,
            )
            return None

        root_cause = str(payload.get("root_cause") or analysis.root_cause).strip()
        lesson = str(payload.get("lesson") or analysis.lesson).strip()
        prevention = str(payload.get("prevention") or analysis.prevention).strip()
        try:
            llm_confidence = float(payload.get("confidence", analysis.confidence))
        except (TypeError, ValueError):
            llm_confidence = analysis.confidence
        llm_confidence = max(0.0, min(1.0, llm_confidence))

        # Evidence still governs confirmation. A hypothesis may only have its
        # confidence nudged slightly, never raised to certainty.
        if analysis.cause_status is CauseStatus.HYPOTHESIS:
            confidence = min(max(analysis.confidence, llm_confidence), 0.75)
        else:
            confidence = round((analysis.confidence + llm_confidence) / 2.0, 4)

        return analysis.model_copy(
            update={
                "root_cause": self._clean(root_cause) or analysis.root_cause,
                "lesson": self._clean(lesson) or analysis.lesson,
                "prevention": self._clean(prevention) or analysis.prevention,
                "confidence": confidence,
                "analyzer": "llm_refined",
            }
        )

    # ------------------------------------------------------------------ #
    def _clean(self, text: str | None) -> str:
        if text is None:
            return ""
        sanitized = self.redactor.redact(str(text))
        return sanitized[: self.settings.max_memory_text_length]
