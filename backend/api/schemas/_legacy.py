"""Request schemas for the HTTP API.

Only *requests* are modelled here; responses reuse the domain Pydantic models
plus the small serialisers in :mod:`backend.api.serializers`, so the API can
never drift from the internal representation of a run or a memory.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.agent.environment import SimulatedEnvironment
from backend.config import get_settings
from backend.domain import FeedbackVerdict, MemoryStatus

# Keys of user-supplied environment maps are bounded separately from values so
# a pathological key cannot bypass value-length limits.
_MAX_ENV_KEY_LENGTH = 256


def _validate_task(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("task must not be blank")
    return stripped


def _validate_agent_id(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("agent_id must not be blank")
    if len(stripped) > 128:
        raise ValueError("agent_id must be at most 128 characters")
    return stripped


def _check_env_structure(
    value: Any, depth: int, max_depth: int, max_items: int, max_length: int
) -> None:
    """Recursively bound the size and depth of a user-supplied structure.

    Enforces, for every node: nesting depth, per-container item count, string
    length, and key length. Raises ``ValueError`` (-> HTTP 422) on the first
    violation so a deeply nested or oversized payload can never reach the
    simulated environment or the agent loop.
    """
    if depth > max_depth:
        raise ValueError(f"environment structure exceeds the maximum nesting depth of {max_depth}")
    if isinstance(value, dict):
        if len(value) > max_items:
            raise ValueError(f"environment mapping exceeds the maximum of {max_items} entries")
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > _MAX_ENV_KEY_LENGTH:
                raise ValueError(
                    f"environment keys must be strings of at most {_MAX_ENV_KEY_LENGTH} characters"
                )
            _check_env_structure(item, depth + 1, max_depth, max_items, max_length)
    elif isinstance(value, list):
        if len(value) > max_items:
            raise ValueError(f"environment list exceeds the maximum of {max_items} items")
        for item in value:
            _check_env_structure(item, depth + 1, max_depth, max_items, max_length)
    elif isinstance(value, str):
        if len(value) > max_length:
            raise ValueError(f"environment string values exceed the maximum length of {max_length}")
    elif value is not None and not isinstance(value, int | float | bool):
        raise ValueError(f"unsupported value type in environment: {type(value).__name__}")


class EnvironmentSpec(BaseModel):
    """An optional override for the sandboxed environment.

    Everything here is in-memory/simulated; providing it never grants access to
    the host, the network, or the filesystem.
    """

    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(default=None, max_length=256)
    config: dict[str, str] = Field(default_factory=dict)
    secrets: dict[str, str] = Field(default_factory=dict)
    packages: dict[str, str] = Field(default_factory=dict)
    registry: dict[str, str] = Field(default_factory=dict)
    services: dict[str, dict[str, Any]] = Field(default_factory=dict)
    faults: dict[str, Any] = Field(default_factory=dict)

    @field_validator("config", "secrets", "packages", "registry")
    @classmethod
    def _flat_maps_are_bounded(cls, value: dict[str, str]) -> dict[str, str]:
        limits = get_settings()
        if len(value) > limits.max_env_items:
            raise ValueError(
                f"environment mapping exceeds the maximum of {limits.max_env_items} entries"
            )
        for key, item in value.items():
            if len(key) > _MAX_ENV_KEY_LENGTH:
                raise ValueError(
                    f"environment keys must be strings of at most {_MAX_ENV_KEY_LENGTH} characters"
                )
            if len(item) > limits.max_env_value_length:
                raise ValueError(
                    "environment string values exceed the maximum length of "
                    f"{limits.max_env_value_length}"
                )
        return value

    @field_validator("services", "faults")
    @classmethod
    def _nested_structures_are_bounded(cls, value: dict[str, Any]) -> dict[str, Any]:
        limits = get_settings()
        _check_env_structure(
            value,
            depth=0,
            max_depth=limits.max_env_depth,
            max_items=limits.max_env_items,
            max_length=limits.max_env_value_length,
        )
        return value

    def to_environment(self) -> SimulatedEnvironment:
        env = SimulatedEnvironment(
            id=self.id or "custom",
            config=dict(self.config),
            secrets=dict(self.secrets),
            packages=dict(self.packages),
            services=dict(self.services),
            faults=dict(self.faults),
        )
        if self.registry:
            env.registry = dict(self.registry)
        return env


class RunTaskRequest(BaseModel):
    """Run a single task against the persistent store."""

    model_config = ConfigDict(extra="forbid")

    task: str = Field(min_length=1, max_length=2000)
    mode: Literal["baseline", "naive", "memory"] = "memory"
    agent_id: str = Field(default="default", min_length=1, max_length=128)
    max_attempts: int = Field(default=2, ge=1, le=6)
    environment: EnvironmentSpec | None = None

    @field_validator("task")
    @classmethod
    def _task_not_blank(cls, value: str) -> str:
        return _validate_task(value)

    @field_validator("agent_id")
    @classmethod
    def _agent_id_not_blank(cls, value: str) -> str:
        return _validate_agent_id(value)


class CompareTasksRequest(BaseModel):
    """Run the same task in baseline and memory mode under identical conditions."""

    model_config = ConfigDict(extra="forbid")

    task: str = Field(min_length=1, max_length=2000)
    agent_id: str = Field(default="default", min_length=1, max_length=128)
    max_attempts: int = Field(default=2, ge=1, le=6)
    environment: EnvironmentSpec | None = None

    @field_validator("task")
    @classmethod
    def _task_not_blank(cls, value: str) -> str:
        return _validate_task(value)

    @field_validator("agent_id")
    @classmethod
    def _agent_id_not_blank(cls, value: str) -> str:
        return _validate_agent_id(value)


class CrossAgentRunRequest(BaseModel):
    """Let one agent learn a lesson and another agent reuse it."""

    model_config = ConfigDict(extra="forbid")

    task: str = Field(min_length=1, max_length=2000)
    learner_agent_id: str = Field(default="agent-a", min_length=1, max_length=128)
    consumer_agent_id: str = Field(default="agent-b", min_length=1, max_length=128)
    max_attempts: int = Field(default=2, ge=1, le=6)
    environment: EnvironmentSpec | None = None

    @field_validator("task")
    @classmethod
    def _task_not_blank(cls, value: str) -> str:
        return _validate_task(value)

    @field_validator("learner_agent_id", "consumer_agent_id")
    @classmethod
    def _agent_ids_not_blank(cls, value: str) -> str:
        return _validate_agent_id(value)


class RetrievalPreviewRequest(BaseModel):
    """Preview which memories would be retrieved for a task (no execution)."""

    model_config = ConfigDict(extra="forbid")

    task: str | None = Field(default=None, max_length=2000)
    scenario_id: str | None = None
    agent_id: str | None = Field(default=None, max_length=128)
    cross_agent: bool = True
    limit: int = Field(default=5, ge=1, le=50)

    @field_validator("task")
    @classmethod
    def _task_not_blank(cls, value: str | None) -> str | None:
        return None if value is None else _validate_task(value)

    @field_validator("agent_id")
    @classmethod
    def _agent_id_not_blank(cls, value: str | None) -> str | None:
        return None if value is None else _validate_agent_id(value)


class FeedbackRequest(BaseModel):
    """Attach a human/system verdict to a memory."""

    model_config = ConfigDict(extra="forbid")

    verdict: FeedbackVerdict
    comment: str = Field(default="", max_length=2000)


class StatusRequest(BaseModel):
    """Change a memory's lifecycle status."""

    model_config = ConfigDict(extra="forbid")

    status: MemoryStatus


class EvaluationRunRequest(BaseModel):
    """Run the evaluation benchmark, optionally limited to a subset of scenarios."""

    model_config = ConfigDict(extra="forbid")

    scenarios: list[str] | None = None


class LLMEvaluationRequest(BaseModel):
    """Request body for running the LLM-based evaluation benchmark."""

    model_config = ConfigDict(extra="forbid")

    scenarios: list[str] | None = Field(default=None, max_length=64)
    repetitions: int = Field(default=1, ge=1, le=10)
    modes: list[Literal["baseline", "naive", "memory"]] | None = Field(default=None, max_length=3)
