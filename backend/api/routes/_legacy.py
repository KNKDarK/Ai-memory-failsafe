"""HTTP API for the AI Agent Failure Memory backend.

Exposes the complete lifecycle (task -> plan -> execute -> detect -> analyse ->
learn -> store -> retrieve -> prevent) plus the evaluation harness, over a
small, documented JSON API. The default configuration is fully offline and
deterministic; no API key is required.

Run locally::

    uvicorn backend.api.routes:app --reload
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.agent.environment import SimulatedEnvironment, default_environment
from backend.api import schemas, serializers
from backend.api.middleware import BodySizeLimitMiddleware
from backend.config import Settings, get_settings
from backend.domain import MemoryStatus
from backend.evaluation.benchmark import Benchmark, run_scenario_detail
from backend.evaluation.scenarios import Scenario, build_scenarios, get_scenario
from backend.memory.lifecycle import (
    apply_lifecycle,
    lifecycle_report,
    policy_from_settings,
)
from backend.memory.retriever import find_contradictions
from backend.resources import detect_resources
from backend.security import SecretRedactor, build_default_redactor
from backend.services import Runtime, build_runtime

logger = logging.getLogger("failure_memory.api")

# Shared infrastructure (RuntimeManager, helpers, auth) lives here so
# submodules can import it without circular dependencies.
_api_router = APIRouter(prefix="/api")


# --------------------------------------------------------------------------- #
# Runtime management (with graceful degradation when the DB is unavailable)
# --------------------------------------------------------------------------- #
class RuntimeManager:
    """Holds the shared runtime, or a recorded error if it could not be built."""

    def __init__(self, settings: Settings, runtime: Runtime | None = None) -> None:
        self.settings = settings
        self._runtime = runtime
        self._error: str | None = None
        if runtime is None:
            try:
                self._runtime = build_runtime(settings)
            except Exception as exc:  # noqa: BLE001 - surfaced via /health, never fatal
                self._error = f"{type(exc).__name__}: {exc}"
                logger.warning("Runtime unavailable: %s", type(exc).__name__)

    @property
    def error(self) -> str | None:
        return self._error

    def available(self) -> bool:
        return self._runtime is not None

    def maybe(self) -> Runtime | None:
        return self._runtime

    def require(self) -> Runtime:
        if self._runtime is None:
            raise HTTPException(
                status_code=503,
                detail=(
                    "failure-memory storage is unavailable; "
                    "check MEMORY_DATABASE and its permissions"
                ),
            )
        return self._runtime


def _manager(request: Request) -> RuntimeManager:
    return request.app.state.runtime_manager


def _redactor(request: Request) -> SecretRedactor:
    return request.app.state.redactor


# --------------------------------------------------------------------------- #
# API access control (single-user local deployments)
# --------------------------------------------------------------------------- #
# A static bearer token read from API_AUTH_TOKEN protects the endpoints that
# execute tasks or mutate the failure memory. This is deliberately simple: it
# keeps external auth services out of a single-user local app while stopping
# anything that can reach the port (other processes, containers, LAN peers)
# from changing state without the token. It is NOT a deployment security
# boundary for public exposure -- see the "API security" README section.
def _extract_presented_token(request: Request) -> str | None:
    """Return the token presented by the client, or None if absent."""
    authorization = request.headers.get("authorization")
    if authorization:
        scheme, _, credential = authorization.partition(" ")
        if scheme.strip().lower() == "bearer" and credential.strip():
            return credential.strip()
    api_key = request.headers.get("x-api-key")
    if api_key and api_key.strip():
        return api_key.strip()
    return None


def _tokens_match(presented: str, expected: str) -> bool:
    """Constant-time token comparison that also hides length differences."""
    presented_digest = hashlib.sha256(presented.encode("utf-8")).digest()
    expected_digest = hashlib.sha256(expected.encode("utf-8")).digest()
    return secrets.compare_digest(presented_digest, expected_digest)


async def require_api_token(request: Request) -> None:
    """Protect a task-execution or memory-mutation endpoint.

    * ``API_AUTH_TOKEN`` unset/empty  -> no enforcement (open local dev mode).
    * Token missing                  -> 401 with ``WWW-Authenticate: Bearer``.
    * Token wrong                    -> 403.

    Neither the presented nor the configured token is ever logged or echoed.
    """
    expected = _manager(request).settings.api_auth_token
    if not expected:
        return
    presented = _extract_presented_token(request)
    if presented is None:
        raise HTTPException(
            status_code=401,
            detail="missing API token; send 'Authorization: Bearer <token>' or 'X-API-Key: <token>'",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not _tokens_match(presented, expected):
        raise HTTPException(status_code=403, detail="invalid API token")


def _scenario_or_404(scenario_id: str) -> Scenario:
    scenario = get_scenario(scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail=f"unknown scenario '{scenario_id}'")
    return scenario


def _scenario_summary(scenario: Scenario) -> dict:
    return {
        "id": scenario.id,
        "name": scenario.name,
        "category": scenario.category,
        "task": scenario.task,
        "description": scenario.description,
        "max_attempts": scenario.max_attempts,
        "simulated": scenario.simulated,
        "notes": scenario.notes,
        "seed_memory_count": len(scenario.seed_memories),
        "expected": {
            "baseline_success": scenario.expected_baseline_success,
            "memory_success": scenario.expected_memory_success,
            "prevention_expected": scenario.expect_prevention,
        },
    }


# --------------------------------------------------------------------------- #
# Meta
# --------------------------------------------------------------------------- #
@_api_router.get("/health")
def health(request: Request) -> dict:
    manager = _manager(request)
    payload = {
        "status": "ok" if manager.available() else "degraded",
        "memory_database_available": manager.available(),
        "error": manager.error,
        "environment": manager.settings.environment,
    }
    runtime = manager.maybe()
    if runtime is not None:
        payload["memory_count"] = runtime.store.count()
        payload["active_memory_count"] = runtime.store.count(include_inactive=False)
    return payload


@_api_router.get("/config")
def config(request: Request) -> dict:
    """Non-secret configuration summary for the dashboard."""
    settings = _manager(request).settings
    return {
        "environment": settings.environment,
        "offline": not settings.llm_enabled,
        "llm": {
            "provider": settings.llm_provider,
            "real_model": settings.llm_enabled,
        },
        "embedding": {"provider": settings.embedding_provider, "dim": settings.embedding_dim},
        "retrieval": {
            "limit": settings.retrieval_limit,
            "min_score": settings.retrieval_min_score,
            "min_similarity": settings.retrieval_min_similarity,
            "method": settings.retrieval_method,
            "adaptive_strategy_selection": settings.retrieval_method == "adaptive",
            "strategy_exploration": settings.retrieval_strategy_exploration,
        },
        "cross_agent": {
            "enabled": settings.cross_agent_learning,
            "min_confidence": settings.cross_agent_min_confidence,
        },
        "weights": {
            "similarity": settings.weight_similarity,
            "confidence": settings.weight_confidence,
            "recency": settings.weight_recency,
            "feedback": settings.weight_feedback,
        },
        "min_confidence_to_apply": settings.min_confidence_to_apply,
        "lifecycle": {
            "stale_after_days": settings.lifecycle_stale_after_days,
            "retire_after_days": settings.lifecycle_retire_after_days,
            "obsolete_failure_ratio": settings.lifecycle_obsolete_failure_ratio,
            "min_uses_for_obsolete": settings.lifecycle_min_uses_for_obsolete,
        },
        "default_max_attempts": settings.default_max_attempts,
        "redact_secrets": settings.redact_secrets,
    }


@_api_router.get("/resources")
def resources() -> dict:
    """Report current host/container capacity used for model throttling."""
    return detect_resources().as_dict()


# --------------------------------------------------------------------------- #
# Scenarios + self-contained demo
# --------------------------------------------------------------------------- #
@_api_router.get("/scenarios")
def list_scenarios() -> list[dict]:
    return [_scenario_summary(scenario) for scenario in build_scenarios()]


# Endpoints that execute tasks or mutate the failure memory require the API
# token when one is configured. Read-only endpoints (health, config, listings,
# retrieval preview) stay open so container health checks and dashboard reads
# keep working without credentials.
_PROTECTED = [Depends(require_api_token)]


@_api_router.post("/scenarios/{scenario_id}/run", dependencies=_PROTECTED)
def run_scenario(scenario_id: str, request: Request) -> dict:
    """Run one scenario twice (baseline and memory) on an isolated store."""
    scenario = _scenario_or_404(scenario_id)
    settings = _manager(request).settings
    redactor = _redactor(request)
    detail = run_scenario_detail(settings, scenario)

    return {
        "scenario": _scenario_summary(scenario),
        "baseline": serializers.run_dict(detail.baseline_run, redactor),
        "memory": serializers.run_dict(detail.memory_run, redactor),
        "retrieval": [serializers.retrieval_dict(result, redactor) for result in detail.probe],
        "metrics": {
            "baseline": detail.baseline_metrics,
            "memory": detail.memory_metrics,
        },
        "memory_stats": {
            "before": detail.memory_stats_before,
            "after": detail.memory_stats_after,
        },
        "seeded_memory_ids": detail.seeded_memory_ids,
    }


# --------------------------------------------------------------------------- #
# Live tasks (persistent store)
# --------------------------------------------------------------------------- #
@_api_router.post("/tasks/run", dependencies=_PROTECTED)
def run_task(payload: schemas.RunTaskRequest, request: Request) -> dict:
    runtime = _manager(request).require()
    redactor = _redactor(request)
    env: SimulatedEnvironment = (
        payload.environment.to_environment()
        if payload.environment is not None
        else default_environment()
    )
    run = runtime.agent().run_task(
        payload.task,
        env,
        mode=payload.mode,
        max_attempts=payload.max_attempts,
        agent_id=payload.agent_id,
    )
    return serializers.run_dict(run, redactor)


@_api_router.post("/tasks/compare", dependencies=_PROTECTED)
def compare_task(payload: schemas.CompareTasksRequest, request: Request) -> dict:
    """Run the same task in baseline and memory mode with identical environments."""
    runtime = _manager(request).require()
    redactor = _redactor(request)
    agent = runtime.agent()
    env = (
        payload.environment.to_environment()
        if payload.environment is not None
        else default_environment()
    )

    baseline = agent.run_task(
        payload.task,
        env.clone(),
        mode="baseline",
        max_attempts=payload.max_attempts,
        agent_id=payload.agent_id,
    )
    memory = agent.run_task(
        payload.task,
        env.clone(),
        mode="memory",
        max_attempts=payload.max_attempts,
        agent_id=payload.agent_id,
    )
    return {
        "task": payload.task,
        "agent_id": payload.agent_id,
        "max_attempts": payload.max_attempts,
        "baseline": serializers.run_dict(baseline, redactor),
        "memory": serializers.run_dict(memory, redactor),
    }


@_api_router.post("/tasks/cross-agent", dependencies=_PROTECTED)
def run_cross_agent_task(payload: schemas.CrossAgentRunRequest, request: Request) -> dict:
    """Agent A learns from a failure, then Agent B reuses the shared lesson.

    Both runs share the persistent store but use fresh, identical environments,
    so the consumer's improvement can only come from cross-agent memory.
    """
    runtime = _manager(request).require()
    redactor = _redactor(request)
    env = (
        payload.environment.to_environment()
        if payload.environment is not None
        else default_environment()
    )
    agent = runtime.agent()

    learner_run = agent.run_task(
        payload.task,
        env.clone(),
        mode="memory",
        max_attempts=payload.max_attempts,
        agent_id=payload.learner_agent_id,
    )
    learned_ids = list(
        dict.fromkeys(learner_run.memory_ids_created + learner_run.memory_ids_reinforced)
    )
    shared_ids = [
        memory_id
        for memory_id in learned_ids
        if (memory := runtime.store.get(memory_id)) is not None and memory.shared
    ]
    consumer_run = agent.run_task(
        payload.task,
        env.clone(),
        mode="memory",
        max_attempts=payload.max_attempts,
        agent_id=payload.consumer_agent_id,
    )
    reused_ids = [
        memory_id for memory_id in consumer_run.memory_ids_applied if memory_id in shared_ids
    ]

    return {
        "task": payload.task,
        "learner_agent_id": payload.learner_agent_id,
        "consumer_agent_id": payload.consumer_agent_id,
        "learner": serializers.run_dict(learner_run, redactor),
        "consumer": serializers.run_dict(consumer_run, redactor),
        "learned_memory_ids": learned_ids,
        "shared_memory_ids": shared_ids,
        "reused_memory_ids": reused_ids,
        "cross_agent_learning_observed": bool(reused_ids),
        "agent_stats": runtime.store.agent_stats(),
    }


# --------------------------------------------------------------------------- #
# Retrieval explanation
# --------------------------------------------------------------------------- #
@_api_router.post("/retrieval/preview")
def preview_retrieval(payload: schemas.RetrievalPreviewRequest, request: Request) -> dict:
    runtime = _manager(request).require()
    redactor = _redactor(request)
    if payload.scenario_id:
        scenario = _scenario_or_404(payload.scenario_id)
        task = (payload.task or scenario.task).strip()
        env = scenario.environment.clone()
    else:
        task = (payload.task or "").strip()
        env = default_environment()
    if not task:
        raise HTTPException(status_code=422, detail="provide a non-empty task or a scenario_id")

    results = runtime.agent().preview_retrieval(
        task,
        env,
        agent_id=payload.agent_id,
        cross_agent=payload.cross_agent,
    )
    serialized = [serializers.retrieval_dict(result, redactor) for result in results]
    selected = [item["memory"]["id"] for item in serialized if item["selected"]]
    return {
        "task": task,
        "agent_id": payload.agent_id,
        "retrieval_mode": results[0].retrieval_mode if results else None,
        "retrieval_strategy": results[0].retrieval_strategy if results else None,
        "selected_ids": selected,
        "candidate_count": len(serialized),
        "results": serialized[: payload.limit],
    }


# --------------------------------------------------------------------------- #
# Cross-agent learning
# --------------------------------------------------------------------------- #
@_api_router.get("/agents")
def list_agents(request: Request) -> dict:
    """Per-agent provenance, sharing, and cross-agent reuse counters."""
    runtime = _manager(request).require()
    return runtime.store.agent_stats()


@_api_router.get("/agents/{agent_id}")
def get_agent(agent_id: str, request: Request) -> dict:
    """One agent's counters plus every lesson it created, reinforced, or used."""
    runtime = _manager(request).require()
    redactor = _redactor(request)
    summary = runtime.store.agent_stats()
    record = next(
        (item for item in summary["agents"] if item["agent_id"] == agent_id),
        None,
    )
    if record is None:
        raise HTTPException(status_code=404, detail="agent not found")
    memories = [
        memory
        for memory in runtime.store.list(include_inactive=True)
        if memory.agent_id == agent_id
        or agent_id in memory.contributing_agent_ids
        or agent_id in memory.used_by_agent_ids
    ]
    return {
        "agent": record,
        "memories": [serializers.memory_dict(memory, redactor) for memory in memories],
    }


# --------------------------------------------------------------------------- #
# Automatic retrieval-strategy selection
# --------------------------------------------------------------------------- #
@_api_router.get("/retrieval/strategies")
def retrieval_strategies(request: Request) -> dict:
    """Show observed strategy outcomes and the next choice for each task type."""
    runtime = _manager(request).require()
    settings = _manager(request).settings
    embedder_available = runtime.embedder is not None
    stats = runtime.store.strategy_stats()
    known_task_types = {row["task_type"] for row in stats}
    known_task_types.update(
        memory.task_type for memory in runtime.store.list(include_inactive=True)
    )
    selections = {
        task_type: runtime.strategy_selector.choose(
            task_type, embedder_available=embedder_available
        )
        for task_type in sorted(known_task_types or {"generic"})
    }
    return {
        "retrieval_method": settings.retrieval_method,
        "adaptive": settings.retrieval_method == "adaptive",
        "exploration": settings.retrieval_strategy_exploration,
        "embedder_available": embedder_available,
        "candidates": list(
            runtime.strategy_selector.candidates(embedder_available=embedder_available)
        ),
        "stats": stats,
        "next_selection": selections,
    }


@_api_router.post("/retrieval/strategies/reset", dependencies=_PROTECTED)
def reset_retrieval_strategies(
    request: Request, task_type: str | None = Query(default=None)
) -> dict:
    """Clear learned strategy outcomes (all task types, or one)."""
    runtime = _manager(request).require()
    cleared = runtime.store.reset_strategy_stats(task_type)
    return {"cleared": cleared, "task_type": task_type}


# --------------------------------------------------------------------------- #
# Memories
# --------------------------------------------------------------------------- #
@_api_router.get("/memories")
def list_memories(
    request: Request,
    status: str | None = Query(default=None),
    task_type: str | None = Query(default=None),
    agent_id: str | None = Query(default=None),
    shared: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    include_inactive: bool = Query(default=True),
) -> dict:
    runtime = _manager(request).require()
    redactor = _redactor(request)
    parsed_status = None
    if status:
        try:
            parsed_status = MemoryStatus(status)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"invalid status '{status}'") from exc

    memories = runtime.store.list(
        status=parsed_status,
        task_type=task_type,
        agent_id=agent_id,
        shared=shared,
        limit=limit,
        offset=offset,
        include_inactive=include_inactive,
    )
    total = runtime.store.count(
        status=parsed_status,
        task_type=task_type,
        agent_id=agent_id,
        shared=shared,
        include_inactive=include_inactive,
    )
    return {
        "items": [serializers.memory_dict(memory, redactor) for memory in memories],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@_api_router.get("/memories/stats")
def memory_stats(request: Request) -> dict:
    runtime = _manager(request).require()
    settings = _manager(request).settings
    stats = runtime.store.stats()
    report = lifecycle_report(
        runtime.store.list(include_inactive=True), policy=policy_from_settings(settings)
    )
    report.pop("items", None)
    stats["lifecycle"] = report
    stats["retrieval_strategies"] = runtime.store.strategy_stats()
    return stats


@_api_router.get("/memories/contradictions")
def memory_contradictions(request: Request) -> dict:
    runtime = _manager(request).require()
    conflicts = find_contradictions(runtime.store.list())
    return {"count": len(conflicts), "conflicts": conflicts}


@_api_router.get("/memories/lifecycle")
def get_memory_lifecycle(request: Request) -> dict:
    """Dry run: label every memory and list the transitions the policy *would* apply."""
    runtime = _manager(request).require()
    settings = _manager(request).settings
    memories = runtime.store.list(include_inactive=True)
    return lifecycle_report(memories, policy=policy_from_settings(settings))


@_api_router.post("/memories/lifecycle/apply", dependencies=_PROTECTED)
def apply_memory_lifecycle(request: Request) -> dict:
    """Apply the deterministic lifecycle policy (active -> outdated -> incorrect -> archived)."""
    runtime = _manager(request).require()
    settings = _manager(request).settings
    result = apply_lifecycle(runtime.store, policy=policy_from_settings(settings))
    report = result.get("report")
    if isinstance(report, dict):
        report.pop("items", None)
    return result


@_api_router.get("/memories/{memory_id}")
def get_memory(memory_id: str, request: Request) -> dict:
    runtime = _manager(request).require()
    redactor = _redactor(request)
    memory = runtime.store.get(memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="memory not found")
    feedback = runtime.store.list_feedback(memory_id)
    return {
        "memory": serializers.memory_dict(memory, redactor),
        "feedback": [serializers.feedback_dict(item, redactor) for item in feedback],
    }


@_api_router.post("/memories/{memory_id}/feedback", dependencies=_PROTECTED)
def add_feedback(memory_id: str, payload: schemas.FeedbackRequest, request: Request) -> dict:
    runtime = _manager(request).require()
    redactor = _redactor(request)
    memory, feedback = runtime.store.add_feedback(
        memory_id, payload.verdict, comment=payload.comment
    )
    if memory is None:
        raise HTTPException(status_code=404, detail="memory not found")
    return {
        "memory": serializers.memory_dict(memory, redactor),
        "feedback": serializers.feedback_dict(feedback, redactor),
    }


@_api_router.patch("/memories/{memory_id}/status", dependencies=_PROTECTED)
def set_memory_status(memory_id: str, payload: schemas.StatusRequest, request: Request) -> dict:
    runtime = _manager(request).require()
    redactor = _redactor(request)
    memory = runtime.store.set_status(memory_id, payload.status)
    if memory is None:
        raise HTTPException(status_code=404, detail="memory not found")
    return {"memory": serializers.memory_dict(memory, redactor)}


@_api_router.delete("/memories/{memory_id}", dependencies=_PROTECTED)
def delete_memory(memory_id: str, request: Request) -> dict:
    runtime = _manager(request).require()
    deleted = runtime.store.delete(memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="memory not found")
    return {"deleted": True, "memory_id": memory_id}


# --------------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------------- #
@_api_router.post("/evaluation/run", dependencies=_PROTECTED)
def run_evaluation(payload: schemas.EvaluationRunRequest, request: Request) -> dict:
    settings = _manager(request).settings
    report = Benchmark(settings).run(payload.scenarios)
    target = Path(settings.evaluation_report_path)
    if target.parent and str(target.parent) not in {"", "."}:
        target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2))
    return report


@_api_router.get("/evaluation/report")
def get_evaluation_report(request: Request) -> dict:
    settings = _manager(request).settings
    target = Path(settings.evaluation_report_path)
    if not target.exists():
        raise HTTPException(
            status_code=404,
            detail="no evaluation report yet; run POST /api/evaluation/run first",
        )
    return json.loads(target.read_text())


# --------------------------------------------------------------------------- #
# LLM evaluation (real-model benchmark)
# --------------------------------------------------------------------------- #
@_api_router.post("/evaluation/llm/run", dependencies=_PROTECTED)
def run_llm_evaluation(payload: schemas.LLMEvaluationRequest, request: Request) -> dict:
    """Run the real-LLM evaluation benchmark (baseline / naive / memory arms).

    Requires a configured LLM provider; when none is available the response
    reports ``llm_enabled: false`` and the error instead of silently
    pretending to have evaluated with a model.
    """
    from backend.evaluation.llm_benchmark import run_llm_benchmark

    settings = _manager(request).settings
    return run_llm_benchmark(
        settings,
        scenario_ids=payload.scenarios,
        repetitions=payload.repetitions,
        modes=payload.modes,
        save=True,
    )


@_api_router.get("/evaluation/llm/reports")
def list_llm_evaluation_reports(request: Request) -> dict:
    """List saved LLM benchmark reports (newest first)."""
    from backend.evaluation.llm_benchmark import list_reports

    return {"reports": list_reports(_manager(request).settings)}


@_api_router.get("/evaluation/llm/reports/{run_id}")
def get_llm_evaluation_report(run_id: str, request: Request) -> dict:
    """Fetch one saved LLM benchmark report by run id."""
    from backend.evaluation.llm_benchmark import load_report

    report = load_report(_manager(request).settings, run_id)
    if report is None:
        raise HTTPException(status_code=404, detail="report not found")
    return report


# --------------------------------------------------------------------------- #
# App factory
# --------------------------------------------------------------------------- #
def create_app(settings: Settings | None = None, runtime: Runtime | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="AI Agent Failure Memory",
        version="0.1.0",
        description=(
            "Failure -> Cause -> Lesson -> Future Prevention memory for AI agents. "
            "Offline and deterministic by default."
        ),
    )
    # Added before CORS so CORS stays the outermost middleware and can decorate
    # 413 responses for browser clients.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_body_bytes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.settings = settings
    app.state.redactor = build_default_redactor(settings)
    app.state.runtime_manager = RuntimeManager(settings, runtime)
    if settings.api_auth_token:
        logger.info(
            "API token authentication enabled for task-execution and memory-mutation endpoints"
        )
    else:
        logger.info(
            "API token authentication disabled; set API_AUTH_TOKEN to protect mutation endpoints"
        )

    @app.get("/")
    def root() -> dict:
        return {
            "name": "AI Agent Failure Memory",
            "version": "0.1.0",
            "docs": "/docs",
            "api": "/api",
        }

    @app.exception_handler(ValueError)
    async def _value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(sqlite3.Error)
    async def _sqlite_handler(request: Request, exc: sqlite3.Error) -> JSONResponse:
        logger.warning("Storage error while handling %s: %s", request.url.path, type(exc).__name__)
        return JSONResponse(
            status_code=503,
            content={"detail": "failure-memory storage is temporarily unavailable"},
        )

    @app.exception_handler(RecursionError)
    async def _recursion_handler(request: Request, exc: RecursionError) -> JSONResponse:
        # A pathologically nested JSON body (beyond the parser's recursion
        # limit) is a client error, never a server crash.
        return JSONResponse(
            status_code=422,
            content={"detail": "request body is too deeply nested"},
        )

    app.include_router(_api_router)
    return app


app = create_app()
