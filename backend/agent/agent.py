"""Agent orchestration: the complete failure-memory lifecycle.

``Task -> Plan -> Retrieve -> Execute -> Detect Failure -> Analyze -> Extract
Lesson -> Store Memory -> (next attempt) Retrieve -> Improve``

Two modes are supported:

* ``baseline``  - no retrieval and no learning; the agent cannot improve.
* ``memory``    - retrieves relevant memories before each attempt, applies
  applicable preventions, learns from failures, and records memory feedback.

The mode is explicit so baseline and memory-enabled runs can be compared under
identical conditions.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from backend.agent.environment import SimulatedEnvironment
from backend.agent.executor import AgentExecutor
from backend.agent.models import (
    ExecutionRecord,
    Plan,
    Recommendation,
    TaskRun,
)
from backend.agent.planner import TaskPlanner, detect_task_type
from backend.analysis.failure_analyzer import FailureAnalyzer
from backend.analysis.models import FailureAnalysis
from backend.domain import MemoryStatus, OutcomeType, utcnow
from backend.memory.models import FailureMemory, RetrievalQuery, RetrievalResult
from backend.memory.retriever import MemoryRetriever
from backend.memory.store import MemoryStore

logger = logging.getLogger("failure_memory.agent")


@dataclass(frozen=True)
class MemoryPolicy:
    """Controls whether the agent may read from / write to failure memory.

    ``validate`` distinguishes the *naive* arm (retrieve and apply everything,
    ignoring status, confidence, relevance, contradiction suppression, and the
    similarity floor) from the *validated* arm (the shipped ``memory`` mode,
    which only applies trustworthy, relevant memories above the gates).
    """

    retrieve: bool
    learn: bool
    validate: bool = True


BASELINE_POLICY = MemoryPolicy(retrieve=False, learn=False)
NAIVE_POLICY = MemoryPolicy(retrieve=True, learn=True, validate=False)
MEMORY_POLICY = MemoryPolicy(retrieve=True, learn=True, validate=True)

_POLICY_BY_MODE: dict[str, MemoryPolicy] = {
    "baseline": BASELINE_POLICY,
    "naive": NAIVE_POLICY,
    "memory": MEMORY_POLICY,
}


class FailureMemoryAgent:
    def __init__(
        self,
        store: MemoryStore,
        settings=None,
        *,
        analyzer: FailureAnalyzer | None = None,
        planner: TaskPlanner | None = None,
        executor: AgentExecutor | None = None,
        retriever: MemoryRetriever | None = None,
    ) -> None:
        if settings is None:
            from backend.config import Settings

            settings = Settings.from_env()
        from backend.config import Settings

        if not isinstance(settings, Settings):
            settings = Settings.from_env()
        self.settings = settings
        self.store = store
        self.planner = planner or TaskPlanner()
        self.executor = executor or AgentExecutor(settings)
        self.analyzer = analyzer or FailureAnalyzer(settings)
        self.retriever = retriever

    # ------------------------------------------------------------------ #
    def run_task(
        self,
        task: str,
        env: SimulatedEnvironment | None = None,
        *,
        mode: str = "memory",
        max_attempts: int | None = None,
        policy: MemoryPolicy | None = None,
    ) -> TaskRun:
        if env is None:
            from backend.agent.environment import default_environment

            env = default_environment()
        task = (task or "").strip()
        if not task:
            raise ValueError("task must not be empty")

        policy = policy or _POLICY_BY_MODE.get(mode, MEMORY_POLICY)
        max_attempts = max(1, max_attempts or self.settings.default_max_attempts)
        task_type = detect_task_type(task)

        run = TaskRun(
            run_id=uuid.uuid4().hex,
            task=task,
            task_type=task_type,
            mode=mode,  # type: ignore[arg-type]
            environment_id=env.id,
            max_attempts=max_attempts,
            started_at=utcnow(),
        )

        previous_failures: list[ExecutionRecord] = []

        for attempt_index in range(1, max_attempts + 1):
            base_plan = self.planner.plan(task, env)
            recommendations: list[Recommendation] = []
            retrieved: list[RetrievalResult] = []
            plan: Plan = base_plan

            if policy.retrieve:
                retrieved = self._retrieve(task, task_type, base_plan, validate=policy.validate)
                recommendations = self._build_recommendations(
                    retrieved, task_type, base_plan, validate=policy.validate
                )
                plan, applied_ids = self.planner.apply_preventions(base_plan, recommendations)
                run.retrieved_memory_ids = [
                    r.memory.id for r in retrieved if r.selected or not policy.validate
                ]
            else:
                applied_ids = []

            record = self.executor.execute(
                plan,
                env,
                mode=mode,
                attempt_number=attempt_index,
                recommendations=recommendations,
                retrieved=retrieved,
                applied_memory_ids=applied_ids,
            )
            run.attempts.append(record)

            for memory_id in applied_ids:
                if memory_id not in run.memory_ids_applied:
                    run.memory_ids_applied.append(memory_id)
                if policy.retrieve:
                    self.store.record_use(memory_id, success=record.success)

            if record.success:
                run.final_success = True
                run.final_outcome = OutcomeType.SUCCESS
                if applied_ids and previous_failures:
                    run.prevented_failure = True
                    run.prevention_evidence = (
                        f"attempt {attempt_index} succeeded after applying memory "
                        f"{', '.join(memory_id[:8] for memory_id in applied_ids)} "
                        f"following {len(previous_failures)} failure(s)"
                    )
                break

            run.final_outcome = record.outcome
            previous_failures.append(record)

            if policy.learn:
                analysis = self.analyzer.analyze(record)
                run.analyses.append(analysis)
                memory_id, created = self._learn(analysis, record, task_type)
                if memory_id:
                    target = run.memory_ids_created if created else run.memory_ids_reinforced
                    if memory_id not in target:
                        target.append(memory_id)
                run.notes.append(
                    f"learned from attempt {attempt_index}: "
                    f"{'created' if created else 'reinforced'} memory {memory_id[:8]} "
                    f"({analysis.failure_category.value}, "
                    f"{analysis.cause_status.value}, confidence {analysis.confidence:.2f})"
                )

        run.finished_at = utcnow()
        return run

    # ------------------------------------------------------------------ #
    def analyze(self, execution: ExecutionRecord) -> FailureAnalysis:
        return self.analyzer.analyze(execution)

    def preview_retrieval(
        self, task: str, env: SimulatedEnvironment | None = None
    ) -> list[RetrievalResult]:
        """Retrieve memories for a task *without* executing it.

        Returns every candidate with its ``selected`` flag and ranking
        explanation, so callers (the evaluation probe and the API's
        retrieval-explanation endpoint) can show exactly why a memory was or was
        not injected.
        """
        task = (task or "").strip()
        if not task:
            raise ValueError("task must not be empty")
        if env is None:
            from backend.agent.environment import default_environment

            env = default_environment()
        task_type = detect_task_type(task)
        plan = self.planner.plan(task, env)
        return self._retrieve(task, task_type, plan)

    def _retrieve(
        self, task: str, task_type: str, plan: Plan, *, validate: bool = True
    ) -> list[RetrievalResult]:
        if self.retriever is None:
            return []
        tools = [step.tool for step in plan.steps]
        # The naive arm deliberately removes every retrieval gate: inactive
        # (outdated/incorrect) memories are candidates and there is no score
        # floor, so the only thing left is raw ranking.
        query = RetrievalQuery(
            text=task,
            task_type=task_type,
            action=tools[0] if tools else None,
            limit=self.settings.retrieval_limit,
            min_score=self.settings.retrieval_min_score if validate else 0.0,
            include_inactive=not validate,
        )
        return self.retriever.retrieve(query)

    def _build_recommendations(
        self,
        retrieved: list[RetrievalResult],
        task_type: str,
        plan: Plan,
        *,
        validate: bool = True,
    ) -> list[Recommendation]:
        planned_tools = {step.tool for step in plan.steps}
        recommendations: list[Recommendation] = []
        for result in retrieved:
            if validate and not result.selected:
                continue
            memory = result.memory

            if not validate:
                # Naive memory: apply whatever was retrieved, unconditionally.
                recommendations.append(
                    Recommendation(
                        memory_id=memory.id,
                        prevention=memory.prevention,
                        prevention_actions=list(memory.prevention_actions),
                        confidence=round(memory.effective_confidence, 4),
                        applicable=True,
                        applied=False,
                        reason="naive memory: applied without validation",
                    )
                )
                continue

            reasons: list[str] = []
            applicable = True

            if memory.status is not MemoryStatus.ACTIVE:
                applicable = False
                reasons.append(
                    f"memory status is {memory.status.value} (only active memories are applied)"
                )

            if memory.effective_confidence < self.settings.min_confidence_to_apply:
                applicable = False
                reasons.append(
                    f"effective confidence {memory.effective_confidence:.2f} below "
                    f"threshold {self.settings.min_confidence_to_apply:.2f}"
                )

            relevant = (
                memory.task_type == task_type
                or memory.action in planned_tools
                or result.similarity >= 0.5
            )
            if not relevant:
                applicable = False
                reasons.append("not relevant to the current task")

            recommendations.append(
                Recommendation(
                    memory_id=memory.id,
                    prevention=memory.prevention,
                    prevention_actions=list(memory.prevention_actions),
                    confidence=round(memory.effective_confidence, 4),
                    applicable=applicable,
                    applied=False,
                    reason=("; ".join(reasons) if reasons else "relevant and trustworthy"),
                )
            )
        return recommendations

    def _learn(
        self, analysis: FailureAnalysis, execution: ExecutionRecord, task_type: str
    ) -> tuple[str, bool]:
        memory = FailureMemory(
            id=uuid.uuid4().hex,
            task=analysis.task,
            task_type=task_type or analysis.task_type,
            action=analysis.action,
            failure=analysis.failure,
            failure_category=analysis.failure_category,
            root_cause=analysis.root_cause,
            cause_status=analysis.cause_status,
            evidence=analysis.evidence,
            lesson=analysis.lesson,
            prevention=analysis.prevention,
            prevention_actions=analysis.prevention_actions,
            tags=analysis.tags,
            confidence=analysis.confidence,
            source_execution_id=execution.execution_id,
        )
        merged, created = self.store.merge_or_store(memory)
        return merged.id, created
