"""Structured output schemas for LLM-based planning and evaluation.

All schemas use Pydantic for validation so malformed model output is caught
before it reaches the execution layer.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class LLMPlanStep(BaseModel):
    """One step in an LLM-generated plan."""

    model_config = ConfigDict(extra="forbid")

    tool: str
    description: str = ""
    args: dict[str, object] = Field(default_factory=dict)
    reason: str = ""


class LLMPlanOutput(BaseModel):
    """Structured plan output expected from the LLM."""

    model_config = ConfigDict(extra="forbid")

    task_type: str = ""
    strategy: str = ""
    steps: list[LLMPlanStep] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class LLMMemoryAssessment(BaseModel):
    """How the LLM assesses a retrieved memory."""

    model_config = ConfigDict(extra="forbid")

    memory_id: str
    relevant: bool
    trustworthy: bool
    reason: str = ""
    apply_actions: list[str] = Field(default_factory=list)


class LLMTaskAssessment(BaseModel):
    """Full structured output for LLM task planning with memory."""

    model_config = ConfigDict(extra="forbid")

    plan: LLMPlanOutput
    memory_assessments: list[LLMMemoryAssessment] = Field(default_factory=list)
    overall_reasoning: str = ""
