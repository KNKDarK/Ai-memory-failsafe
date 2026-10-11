"""Shared builders for tests.

Keeping fixture data in one place makes the tests read as behaviour
specifications rather than construction noise.
"""

from __future__ import annotations

from typing import Any

from backend.agent.environment import SimulatedEnvironment
from backend.domain import CauseStatus, FailureCategory, MemoryStatus
from backend.memory.models import FailureMemory


def make_memory(
    *,
    id: str = "mem1",
    task: str = "Deploy the application",
    task_type: str = "deploy_service",
    action: str = "deploy",
    failure: str = "deployment failed: missing configuration DATABASE_URL",
    root_cause: str = "Required configuration was missing before the action.",
    failure_category: FailureCategory = FailureCategory.MISSING_CONFIGURATION,
    cause_status: CauseStatus = CauseStatus.CONFIRMED,
    lesson: str = "Validate required configuration before deploying.",
    prevention: str = "Validate and load configuration before the risky action.",
    prevention_actions: list[str] | None = None,
    tags: list[str] | None = None,
    evidence: list[str] | None = None,
    confidence: float = 0.8,
    status: MemoryStatus = MemoryStatus.ACTIVE,
    success_count: int = 0,
    failure_count: int = 0,
    helpful_count: int = 0,
    unhelpful_count: int = 0,
    occurrence_count: int = 1,
    **extra: Any,
) -> FailureMemory:
    return FailureMemory(
        id=id,
        task=task,
        task_type=task_type,
        action=action,
        failure=failure,
        root_cause=root_cause,
        failure_category=failure_category,
        cause_status=cause_status,
        lesson=lesson,
        prevention=prevention,
        prevention_actions=prevention_actions
        if prevention_actions is not None
        else ["validate_config:DATABASE_URL"],
        tags=tags or ["configuration"],
        evidence=evidence or [root_cause],
        confidence=confidence,
        status=status,
        success_count=success_count,
        failure_count=failure_count,
        helpful_count=helpful_count,
        unhelpful_count=unhelpful_count,
        occurrence_count=occurrence_count,
        **extra,
    )


def deploy_env(**overrides: Any) -> SimulatedEnvironment:
    """The headline demo environment: DATABASE_URL absent but in the secret store."""
    base: dict[str, Any] = dict(
        id="test-deploy",
        config={"APP_ENV": "production"},
        secrets={"DATABASE_URL": "postgres://secret-local"},
        faults={"deploy_requires": {"app": {"env": ["DATABASE_URL"]}}},
    )
    base.update(overrides)
    return SimulatedEnvironment(**base)


def build_env(**overrides: Any) -> SimulatedEnvironment:
    """A build that requires pandas, which is available but not installed."""
    base: dict[str, Any] = dict(
        id="test-build",
        config={"APP_ENV": "ci"},
        registry={"pandas": "2.2.0"},
        faults={"build_requires": ["pandas"]},
    )
    base.update(overrides)
    return SimulatedEnvironment(**base)
