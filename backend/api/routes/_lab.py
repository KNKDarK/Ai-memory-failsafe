"""Replay Lab REST endpoints.

Provides side-by-side baseline vs treatment execution comparisons over the
``/api/lab/*`` prefix.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request

logger = logging.getLogger("failure_memory.api.lab")

router = APIRouter(prefix="/lab", tags=["Replay Lab"])


# --------------------------------------------------------------------------- #
# Replay execution
# --------------------------------------------------------------------------- #

@router.post("/replay")
async def run_replay(request: Request) -> dict:
    """Run a baseline vs treatment replay comparison.

    Accepts a ``ReplayRunRequest`` body and returns a ``ReplayRunResponse``
    containing both execution arms plus computed metric deltas.
    """
    from backend.api.schemas.lab import ReplayRunRequest, ReplayRunResponse
    from backend.evaluation.replay_engine import MemoryReplayLab

    body = await request.json()
    payload = ReplayRunRequest(**body)

    runtime_manager = request.app.state.runtime_manager
    orchestrator = None
    if runtime_manager.available():
        rt = runtime_manager.require()
        from backend.agent.orchestrator import AgentOrchestrator

        orchestrator = AgentOrchestrator(store=rt.store, settings=rt.settings)

    lab = MemoryReplayLab(orchestrator=orchestrator)
    response: ReplayRunResponse = lab.run_replay(
        scenario_id=payload.scenario_id,
        task_input=payload.task_input,
        mode=payload.execution_mode,
        project_id=payload.project_id,
    )

    return {
        "replay_id": response.replay_id,
        "scenario_id": response.scenario_id,
        "execution_mode": response.execution_mode,
        "baseline": _trace_to_dict(response.baseline),
        "treatment": _trace_to_dict(response.treatment),
        "delta": response.delta,
    }


def _trace_to_dict(trace) -> dict:
    """Convert a LabExecutionTrace schema to a plain dict for JSON serialisation."""
    return {
        "execution_mode": trace.execution_mode,
        "memory_enabled": trace.memory_enabled,
        "success": trace.success,
        "total_attempts": trace.total_attempts,
        "execution_time_ms": trace.execution_time_ms,
        "steps": [
            {
                "step_number": s.step_number,
                "action": s.action,
                "tool_call": s.tool_call,
                "output": s.output,
                "error": s.error,
            }
            for s in trace.steps
        ],
        "retrieved_memories": [
            {
                "lesson_id": m.lesson_id,
                "lesson_text": m.lesson_text,
                "retrieval_strategy": m.retrieval_strategy,
                "similarity_score": m.similarity_score,
                "confidence_score": m.confidence_score,
                "retrieved": m.retrieved,
                "applied": m.applied,
                "rejection_reason": m.rejection_reason,
                "is_root_cause_verified": m.is_root_cause_verified,
            }
            for m in trace.retrieved_memories
        ],
        "prevention_injections": trace.prevention_injections,
    }


__all__ = ["router"]
