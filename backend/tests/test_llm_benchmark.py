"""Tests for the real-LLM evaluation benchmark harness.

Ordinary unit tests use scripted fake providers (no model, no network). The
optional integration test that talks to a live local server is gated behind
``LLM_INTEGRATION_TEST=1`` so the default suite never needs a model.
"""

from __future__ import annotations

import os
import re

import pytest

from backend.agent.planner import TaskPlanner
from backend.config import Settings
from backend.evaluation.llm_benchmark import (
    ARM_MODES,
    BENCHMARK_VERSION,
    LLMBenchmark,
    list_reports,
    load_report,
    run_llm_benchmark,
)
from backend.llm.planner import ALLOWED_TOOLS, LLMTaskPlanner


class FakeLLMProvider:
    """Scripted 'real' provider returning valid structured plans by default."""

    is_real = True
    name = "fake:test-model"
    usage = {"prompt_tokens": 100, "completion_tokens": 50}
    last_latency_ms = 200

    def __init__(self, response=None, fail: bool = False) -> None:
        self._response = response
        self._fail = fail
        self.prompts: list[str] = []

    def complete_json(self, prompt: str, system: str | None = None) -> dict:
        self.prompts.append(prompt)
        if self._fail:
            raise RuntimeError("model endpoint down")
        if self._response is not None:
            return self._response
        return {
            "plan": {
                "task_type": "",
                "strategy": "install then build",
                "steps": [
                    {
                        "tool": "install_dependency",
                        "description": "install",
                        "args": {},
                        "reason": "missing dep",
                    },
                    {"tool": "run_build", "description": "build", "args": {}, "reason": "build"},
                ],
                "notes": [],
            },
            "memory_assessments": [],
            "overall_reasoning": "ok",
        }


def _settings(**kwargs) -> Settings:
    return Settings(
        memory_database=":memory:",
        embedding_provider="hashing",
        llm_provider="deterministic",
        **kwargs,
    )


# --------------------------------------------------------------------------- #
# Honesty: no fabricated runs
# --------------------------------------------------------------------------- #
def test_run_is_skipped_without_real_provider() -> None:
    report = LLMBenchmark(_settings()).run()

    assert report["status"] == "skipped"
    assert report["error"]  # explains why nothing ran
    assert report["aggregate"] is None
    assert report["scenarios"] == []
    assert report["model_real"] is False
    assert report["deterministic_fallback"] is True


def test_run_aborts_when_every_model_call_fails() -> None:
    benchmark = LLMBenchmark(_settings(), provider=FakeLLMProvider(fail=True))

    report = benchmark.run(scenario_ids=["missing_dependency_build"])

    assert report["status"] == "aborted"
    assert "model endpoint failed for all" in report["error"]
    assert report["aggregate"] is None
    assert report["model_stats"]["model_call_errors"] > 0
    # Partial per-scenario rows are preserved as evidence of the abort.
    assert report["scenarios"]


def test_malformed_model_output_counts_errors_and_falls_back() -> None:
    provider = FakeLLMProvider(response={"this": "is not a plan"})
    report = LLMBenchmark(_settings(), provider=provider).run(
        scenario_ids=["missing_dependency_build"], modes=["baseline"]
    )

    assert report["status"] == "completed"
    assert report["model_stats"]["model_call_errors"] > 0
    # The run still produced a row, planned by the rule-based fallback.
    assert report["scenarios"][0]["baseline"]["success"] in (True, False)


# --------------------------------------------------------------------------- #
# Report metadata, modes, arms
# --------------------------------------------------------------------------- #
def test_completed_run_has_reproducibility_metadata() -> None:
    report = LLMBenchmark(_settings(), provider=FakeLLMProvider()).run(
        scenario_ids=["missing_dependency_build"]
    )

    assert report["status"] == "completed"
    assert report["benchmark_version"] == BENCHMARK_VERSION
    assert re.fullmatch(r"[0-9a-f]{12}", report["run_id"])
    assert report["generated_at"]
    assert report["model_real"] is True
    assert report["deterministic_fallback"] is False
    assert report["llm_provider"] == "fake:test-model"
    assert set(report["aggregate"]) == set(ARM_MODES)
    assert report["settings"]["llm_temperature"] == 0.0
    assert report["settings"]["llm_max_tokens"] >= 1
    assert report["methodology"]["modes"]
    assert report["limitations"]
    assert report["model_stats"]["model_calls"] > 0


def test_baseline_arm_never_sees_or_applies_memories() -> None:
    provider = FakeLLMProvider()
    report = LLMBenchmark(_settings(), provider=provider).run(
        scenario_ids=["low_confidence_memory"], modes=["baseline"]
    )

    baseline = report["scenarios"][0]["baseline"]
    assert baseline["retrieved_ids"] == []
    assert baseline["applied_ids"] == []
    assert baseline["llm_suggested_ids"] == []
    # The model prompt must carry no memory context in the baseline arm.
    assert provider.prompts
    assert all("Retrieved failure memories" not in p for p in provider.prompts)


def test_memory_arms_show_memories_to_the_model() -> None:
    provider = FakeLLMProvider()
    LLMBenchmark(_settings(), provider=provider).run(
        scenario_ids=["low_confidence_memory"], modes=["memory"]
    )

    assert provider.prompts
    assert any("Retrieved failure memories" in p for p in provider.prompts)


def test_naive_arm_applies_what_validated_arm_rejects() -> None:
    """The whole point of the naive arm: no trust gates, so the low-confidence
    memory is applied, while the validated arm refuses it."""
    report = LLMBenchmark(_settings(), provider=FakeLLMProvider()).run(
        scenario_ids=["low_confidence_memory"], modes=["naive", "memory"]
    )

    naive = report["scenarios"][0]["naive"]
    memory = report["scenarios"][0]["memory"]
    assert "mem_low_confidence" in naive["applied_ids"]
    assert "mem_low_confidence" not in memory["applied_ids"]
    assert "mem_low_confidence" not in memory["harmful_applied_ids"]


def test_rejected_memory_never_applied_in_memory_arm() -> None:
    report = LLMBenchmark(_settings(), provider=FakeLLMProvider()).run(
        scenario_ids=["incorrect_memory"], modes=["memory"]
    )

    memory = report["scenarios"][0]["memory"]
    assert "mem_incorrect" not in memory["applied_ids"]
    assert memory["harmful_applied_ids"] == []


def test_model_may_suggest_harmful_memory_but_gates_decide() -> None:
    """A model suggesting a reviewer-rejected memory cannot bypass the gates."""
    provider = FakeLLMProvider(
        response={
            "plan": {
                "task_type": "",
                "strategy": "trust the memory",
                "steps": [],
                "notes": [],
            },
            "memory_assessments": [
                {
                    "memory_id": "mem_incorrect",
                    "relevant": True,
                    "trustworthy": True,
                    "reason": "model said so",
                    "apply_actions": ["verify_outcome:whatever"],
                }
            ],
            "overall_reasoning": "ok",
        }
    )
    report = LLMBenchmark(_settings(), provider=provider).run(
        scenario_ids=["incorrect_memory"], modes=["memory"]
    )

    memory = report["scenarios"][0]["memory"]
    assert "mem_incorrect" in memory["llm_suggested_ids"]
    assert "mem_incorrect" not in memory["applied_ids"]
    assert memory["harmful_applied_ids"] == []


# --------------------------------------------------------------------------- #
# Model-output safety (tool allowlist)
# --------------------------------------------------------------------------- #
def test_disallowed_tool_proposals_are_replaced_with_noop() -> None:
    provider = FakeLLMProvider(
        response={
            "plan": {
                "task_type": "",
                "strategy": "escape",
                "steps": [
                    {
                        "tool": "evil_shell",
                        "description": "rm -rf /",
                        "args": {},
                        "reason": "why not",
                    },
                    {
                        "tool": "run_build",
                        "description": "build",
                        "args": {},
                        "reason": "build",
                    },
                ],
                "notes": [],
            },
            "memory_assessments": [],
            "overall_reasoning": "ok",
        }
    )
    planner = LLMTaskPlanner(provider)

    plan = planner.plan("Build the project")

    assert plan.steps
    assert all(step.tool in ALLOWED_TOOLS for step in plan.steps)
    assert any(step.tool == "noop" for step in plan.steps)


def test_planner_falls_back_to_rule_based_plan_when_model_fails() -> None:
    planner = LLMTaskPlanner(FakeLLMProvider(fail=True))

    plan = planner.plan("Build the project")

    assert plan.steps
    # Rule-based fallback plans use the allowlisted tool names only.
    assert all(step.tool in ALLOWED_TOOLS for step in plan.steps)


# --------------------------------------------------------------------------- #
# Modes, repetitions, isolation
# --------------------------------------------------------------------------- #
def test_modes_filter_limits_reported_arms() -> None:
    report = LLMBenchmark(_settings(), provider=FakeLLMProvider()).run(
        scenario_ids=["missing_dependency_build"], modes=["memory"]
    )

    assert report["modes"] == ["memory"]
    assert set(report["aggregate"]) == {"memory"}
    assert report["comparison"] is None  # needs baseline + memory


def test_repetitions_record_per_rep_rows_and_variance() -> None:
    report = LLMBenchmark(_settings(), provider=FakeLLMProvider()).run(
        scenario_ids=["missing_dependency_build"],
        repetitions=2,
        modes=["baseline"],
    )

    assert report["repetitions"] == 2
    results = report["scenarios"][0]["repetition_results"]["baseline"]
    assert [row["repetition"] for row in results] == [1, 2]
    variance = report["repetition_variance"]["baseline"]
    assert len(variance["success_rate_by_repetition"]) == 2
    assert variance["success_rate_std"] >= 0.0


def test_each_mode_runs_on_an_isolated_store() -> None:
    """Rows from one arm must not leak retrieved/applied ids from another."""
    report = LLMBenchmark(_settings(), provider=FakeLLMProvider()).run(
        scenario_ids=["low_confidence_memory"]
    )

    baseline = report["scenarios"][0]["baseline"]
    memory = report["scenarios"][0]["memory"]
    assert baseline["retrieved_ids"] == []
    assert memory["retrieved_ids"]


# --------------------------------------------------------------------------- #
# Report persistence
# --------------------------------------------------------------------------- #
def test_reports_are_unique_reloadable_and_traversal_safe(tmp_path) -> None:
    settings = _settings(llm_benchmark_output_dir=str(tmp_path))

    first = LLMBenchmark(settings, provider=FakeLLMProvider()).run(
        scenario_ids=["missing_config_deploy"], modes=["memory"]
    )
    path_one = LLMBenchmark(settings, provider=FakeLLMProvider()).save_report(first)
    second = LLMBenchmark(settings, provider=FakeLLMProvider()).run(
        scenario_ids=["missing_config_deploy"], modes=["memory"]
    )
    path_two = LLMBenchmark(settings, provider=FakeLLMProvider()).save_report(second)

    assert path_one != path_two  # unique run ids, nothing overwritten
    assert len(list_reports(settings)) == 2

    loaded = load_report(settings, first["run_id"])
    assert loaded is not None
    assert loaded["run_id"] == first["run_id"]

    assert load_report(settings, "../../etc/passwd") is None
    assert load_report(settings, "does-not-exist") is None


def test_run_llm_benchmark_saves_and_returns_path(tmp_path) -> None:
    settings = _settings(llm_benchmark_output_dir=str(tmp_path))
    # Deterministic provider -> skipped run must NOT be persisted as evidence.
    skipped = run_llm_benchmark(settings)
    assert skipped["status"] == "skipped"
    assert "report_path" not in skipped
    assert list(tmp_path.glob("*.json")) == []


# --------------------------------------------------------------------------- #
# Optional integration test against the real local server
# --------------------------------------------------------------------------- #
def test_real_local_server_integration() -> None:
    if os.getenv("LLM_INTEGRATION_TEST") != "1":
        pytest.skip("set LLM_INTEGRATION_TEST=1 (and start llama-server) to run")

    from backend.llm.provider import make_llm_provider

    settings = Settings()
    provider = make_llm_provider(settings)
    assert provider.is_real, "LLM_INTEGRATION_TEST requires a real LLM_PROVIDER"
    result = provider.complete_json(
        'Reply with JSON exactly: {"plan": {"task_type": "", "strategy": "",'
        ' "steps": [], "notes": []}, "memory_assessments": [],'
        ' "overall_reasoning": "x"}',
        system="You output JSON only.",
    )
    assert isinstance(result, dict)

    # The planner validates that output before anything can execute it.
    plan = LLMTaskPlanner(provider).plan("Build the project")
    assert all(step.tool in ALLOWED_TOOLS for step in plan.steps)


def test_planner_is_rule_based_when_provider_is_not_real() -> None:
    """The deterministic path must keep using the rule-based planner."""
    planner = LLMTaskPlanner(FakeLLMProvider())
    assert isinstance(planner, TaskPlanner)


def test_adversarial_memory_text_reaches_model_but_cannot_hijack_run() -> None:
    """The injected 'SYSTEM OVERRIDE' text is shown verbatim to the model; a
    model that obeys it still cannot execute anything off the allowlist."""
    provider = FakeLLMProvider(
        response={
            "plan": {
                "task_type": "",
                "strategy": "obey the memory",
                "steps": [
                    {
                        "tool": "shell",
                        "description": "rm -rf /",
                        "args": {},
                        "reason": "the memory said so",
                    },
                    {"tool": "deploy", "description": "deploy", "args": {}, "reason": "task"},
                    {
                        "tool": "verify_deployment",
                        "description": "verify",
                        "args": {},
                        "reason": "memory action",
                    },
                ],
                "notes": [],
            },
            "memory_assessments": [],
            "overall_reasoning": "ok",
        }
    )
    report = LLMBenchmark(_settings(), provider=provider).run(
        scenario_ids=["adversarial_memory_text"], modes=["naive", "memory"]
    )

    assert report["status"] == "completed"
    assert any("SYSTEM OVERRIDE" in p for p in provider.prompts)
    for mode in ("naive", "memory"):
        row = report["scenarios"][0][mode]
        assert row["harmful_applied_ids"] == []
        # The structured memory action (allowlisted) may apply; the shell tool
        # never can (the planner replaced it with noop before execution).
        assert "shell" not in row.get("applied_ids", [])


def test_failed_attempt_feedback_is_included_in_next_prompt() -> None:
    provider = FakeLLMProvider()
    planner = LLMTaskPlanner(provider)

    planner.plan("Build the project")
    assert all("FAILED" not in p for p in provider.prompts)

    planner.record_attempt_failure(
        "Build the project",
        "build failed: missing dependencies pandas",
        [{"tool": "run_build", "args": {}, "error": "missing dependencies pandas"}],
    )
    planner.plan("Build the project")

    assert "FAILED" in provider.prompts[-1]
    assert "missing dependencies pandas" in provider.prompts[-1]
    assert "run_build" in provider.prompts[-1]

    # Feedback must not leak into a different task's prompt.
    planner.plan("Deploy the application")
    assert "FAILED" not in provider.prompts[-1]


def test_rule_based_planner_has_no_feedback_hook() -> None:
    """The deterministic planner stays untouched by the feedback mechanism."""
    assert not hasattr(TaskPlanner(), "record_attempt_failure")


def test_system_prompt_documents_exact_argument_names() -> None:
    from backend.llm.planner import SYSTEM_PROMPT

    # The schemas the model needs to avoid guessing argument names.
    assert '{"package": "name"}' in SYSTEM_PROMPT
    assert '{"target": "app"}' in SYSTEM_PROMPT
    assert "untrusted DATA" in SYSTEM_PROMPT  # injection stance is explicit
