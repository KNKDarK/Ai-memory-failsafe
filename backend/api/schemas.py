"""Request schemas for the HTTP API.

Only *requests* are modelled here; responses reuse the domain Pydantic models
plus the small serialisers in :mod:`backend.api.serializers`, so the API can
never drift from the internal representation of a run or a memory.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.agent.environment import SimulatedEnvironment
from backend.domain import FeedbackVerdict, MemoryStatus


def _validate_task(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("task must not be blank")
    return stripped


class EnvironmentSpec(BaseModel):
    """An optional override for the sandboxed environment.

    Everything here is in-memory/simulated; providing it never grants access to
    the host, the network, or the filesystem.
    """

    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    config: dict[str, str] = Field(default_factory=dict)
    secrets: dict[str, str] = Field(default_factory=dict)
    packages: dict[str, str] = Field(default_factory=dict)
    registry: dict[str, str] = Field(default_factory=dict)
    services: dict[str, dict[str, Any]] = Field(default_factory=dict)
    faults: dict[str, Any] = Field(default_factory=dict)

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
    max_attempts: int = Field(default=2, ge=1, le=6)
    environment: EnvironmentSpec | None = None

    @field_validator("task")
    @classmethod
    def _task_not_blank(cls, value: str) -> str:
        return _validate_task(value)


class CompareTasksRequest(BaseModel):
    """Run the same task in baseline and memory mode under identical conditions."""

    model_config = ConfigDict(extra="forbid")

    task: str = Field(min_length=1, max_length=2000)
    max_attempts: int = Field(default=2, ge=1, le=6)
    environment: EnvironmentSpec | None = None

    @field_validator("task")
    @classmethod
    def _task_not_blank(cls, value: str) -> str:
        return _validate_task(value)


class RetrievalPreviewRequest(BaseModel):
    """Preview which memories would be retrieved for a task (no execution)."""

    model_config = ConfigDict(extra="forbid")

    task: str | None = Field(default=None, max_length=2000)
    scenario_id: str | None = None
    limit: int = Field(default=5, ge=1, le=50)

    @field_validator("task")
    @classmethod
    def _task_not_blank(cls, value: str | None) -> str | None:
        return None if value is None else _validate_task(value)


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
