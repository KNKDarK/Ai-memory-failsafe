"""Plan execution with a reproducible trace.

The executor walks a plan step by step, invoking only registered sandbox tools.
It records every tool call (including retries) so a run can be replayed and
audited, and it distinguishes four failure kinds plus success:

* tool failure  - a tool returned an error
* timeout       - a tool exceeded its time budget
* invalid output- a tool produced unparseable/invalid data
* task failure  - the steps ran but the goal post-condition was not met

Preventive steps are *advisory*: if one fails (for example configuration is
still missing), execution continues so the real outcome is observed rather than
masked.
"""

from __future__ import annotations

import hashlib
import uuid

from backend.agent.environment import SimulatedEnvironment
from backend.agent.models import ExecutionRecord, Plan, StepTrace
from backend.agent.tools import invoke_tool
from backend.domain import OutcomeType, utcnow


def execution_fingerprint(record: ExecutionRecord) -> str:
    """A deterministic hash of task, mode, plan, and observed failure codes."""
    parts = [
        record.task,
        record.mode,
        record.task_type,
        record.environment_id,
        "|".join(f"{s.tool}:{sorted(s.args.items())}" for s in record.plan.steps),
        "|".join(
            f"{t.index}:{t.attempt}:{t.result.tool}:{t.result.outcome_type.value}:"
            f"{t.result.error_code or ''}"
            for t in record.traces
        ),
    ]
    return hashlib.sha256("||".join(parts).encode("utf-8")).hexdigest()[:16]


class AgentExecutor:
    def __init__(self, settings=None) -> None:
        if settings is None:
            from backend.config import Settings

            settings = Settings.from_env()
        self.settings = settings

    def execute(
        self,
        plan: Plan,
        env: SimulatedEnvironment,
        *,
        mode: str = "baseline",
        attempt_number: int = 1,
        execution_id: str | None = None,
        max_step_retries: int | None = None,
        recommendations: list | None = None,
        retrieved: list | None = None,
        applied_memory_ids: list[str] | None = None,
    ) -> ExecutionRecord:
        max_step_retries = (
            self.settings.max_retries_per_step if max_step_retries is None else max_step_retries
        )
        execution_id = execution_id or uuid.uuid4().hex
        started = utcnow()
        traces: list[StepTrace] = []
        total_duration = 0
        retries = 0
        outcome = OutcomeType.SUCCESS
        error: str | None = None
        error_code: str | None = None
        aborted = False

        for index, step in enumerate(plan.steps):
            attempt = 1
            while True:
                result = invoke_tool(env, step.tool, step.args, attempt=attempt)
                total_duration += result.duration_ms
                traces.append(StepTrace(index=index, attempt=attempt, step=step, result=result))

                if result.ok and result.outcome_type is OutcomeType.SUCCESS:
                    break

                if step.is_prevention:
                    # Advisory: record it and keep going so the true outcome is visible.
                    break

                if attempt <= max_step_retries:
                    attempt += 1
                    retries += 1
                    continue

                outcome = result.outcome_type
                error = result.error
                error_code = result.error_code
                aborted = True
                break

            if aborted:
                break

        record = ExecutionRecord(
            execution_id=execution_id,
            task=plan.task,
            task_type=plan.task_type,
            mode=mode,  # type: ignore[arg-type]
            environment_id=env.id,
            plan=plan,
            traces=traces,
            outcome=outcome,
            success=outcome is OutcomeType.SUCCESS,
            attempts=attempt_number,
            retries=retries,
            error=error,
            error_code=error_code,
            applied_memory_ids=list(applied_memory_ids or []),
            recommendations=list(recommendations or []),
            retrieved=list(retrieved or []),
            started_at=started,
            finished_at=utcnow(),
            duration_ms=total_duration,
        )
        record.fingerprint = execution_fingerprint(record)
        return record
