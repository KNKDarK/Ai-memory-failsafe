"""Root-cause detection and lesson extraction."""

from __future__ import annotations

from backend.agent.environment import SimulatedEnvironment, default_environment
from backend.agent.executor import AgentExecutor
from backend.agent.models import ExecutionRecord, Plan, PlanStep, StepTrace, ToolResult
from backend.analysis.failure_analyzer import FailureAnalyzer
from backend.analysis.root_cause import analyze_root_cause
from backend.domain import CauseStatus, FailureCategory, OutcomeType
from backend.tests.factories import deploy_env


def _execute(plan: Plan, env: SimulatedEnvironment, settings) -> ExecutionRecord:
    return AgentExecutor(settings).execute(plan, env, mode="baseline")


def _single_step(tool: str, args: dict, task: str = "do the thing") -> Plan:
    return Plan(
        task=task,
        task_type="generic",
        steps=[PlanStep(id="s1", tool=tool, args=args)],
    )


def test_missing_config_is_confirmed_and_actionable(settings) -> None:
    plan = _single_step("deploy", {"target": "app"}, task="Deploy the application")
    record = _execute(plan, deploy_env(), settings)

    analysis = FailureAnalyzer(settings).analyze(record)
    assert analysis.failure_category is FailureCategory.MISSING_CONFIGURATION
    assert analysis.cause_status is CauseStatus.CONFIRMED
    assert analysis.action == "deploy"
    assert "DATABASE_URL" in analysis.root_cause
    assert any(a.startswith("validate_config:") for a in analysis.prevention_actions)
    assert any(a.startswith("load_config:") for a in analysis.prevention_actions)


def test_missing_config_file_is_confirmed_and_generalizes(settings) -> None:
    """A missing *configuration file* must become a reusable lesson.

    Regression test for the read_file(config/prod.json) ENOENT payload: the
    analyzer must explain *why* (no prerequisite check), not merely restate the
    symptom, and must not encode a one-off fix like "create config/prod.json".
    """
    plan = _single_step("read_file", {"path": "config/prod.json"}, task="Deploy the web service")
    record = _execute(plan, default_environment(), settings)

    analysis = FailureAnalyzer(settings).analyze(record)
    assert analysis.failure_category is FailureCategory.MISSING_CONFIGURATION
    assert analysis.cause_status is CauseStatus.CONFIRMED
    assert analysis.confidence >= 0.9
    assert "config/prod.json" in analysis.root_cause
    # The prevention generalizes to other missing files/secrets...
    assert any(a.startswith("validate_config:") for a in analysis.prevention_actions)
    assert "prerequisite" in analysis.prevention.lower()
    # ...and never bakes in the single file that happened to fail.
    assert "config/prod.json" not in analysis.prevention
    assert "config/prod.json" not in analysis.lesson


def test_native_enoent_code_is_recognised(settings) -> None:
    """An imported trace using the native ENOENT code is analysed, not ignored."""
    step = PlanStep(id="s1", tool="read_file", args={"path": "config/staging.json"})
    result = ToolResult(
        tool="read_file",
        ok=False,
        error="No such file or directory: 'config/staging.json'",
        error_code="ENOENT",
        metadata={"path": "config/staging.json", "missing": ["config/staging.json"]},
    )
    record = ExecutionRecord(
        execution_id="imported",
        task="Deploy the staging service",
        task_type="deploy_service",
        plan=Plan(task="Deploy the staging service", task_type="deploy_service", steps=[step]),
        traces=[StepTrace(index=0, step=step, result=result)],
        outcome=OutcomeType.TOOL_FAILURE,
        success=False,
        error="ENOENT",
        error_code="ENOENT",
    )
    root = analyze_root_cause(record)
    assert root.category is FailureCategory.MISSING_CONFIGURATION
    assert root.status is CauseStatus.CONFIRMED
    assert "config/staging.json" in root.cause


def test_missing_non_config_file_is_not_forced_into_missing_configuration(settings) -> None:
    """Only config-like paths generalise to missing_configuration."""
    plan = _single_step("read_file", {"path": "src/app.py"}, task="Read the source file")
    record = _execute(plan, default_environment(), settings)

    analysis = FailureAnalyzer(settings).analyze(record)
    assert analysis.failure_category is FailureCategory.UNKNOWN


def test_transient_api_failure_is_a_hypothesis(settings) -> None:
    env = SimulatedEnvironment(
        services={"billing_api": {"required_env": []}},
        faults={"api_modes": {"billing_api": "transient"}},
    )
    plan = _single_step("call_api", {"service": "billing_api"}, task="Call the billing api")
    record = _execute(plan, env, settings)

    analysis = FailureAnalyzer(settings).analyze(record)
    assert analysis.failure_category is FailureCategory.INVALID_API_RESPONSE
    assert analysis.cause_status is CauseStatus.HYPOTHESIS
    assert analysis.confidence <= 0.75
    assert any("retry" in a or "backoff" in a for a in analysis.prevention_actions)


def test_timeout_is_confirmed_with_a_timeout_prevention(settings) -> None:
    env = SimulatedEnvironment(
        services={"billing_api": {"required_env": []}},
        faults={"timeout_tools": ["call_api"], "required_timeout_seconds": 30},
    )
    plan = _single_step("call_api", {"service": "billing_api"}, task="Call the billing api")
    record = _execute(plan, env, settings)
    assert record.outcome is OutcomeType.TIMEOUT

    analysis = FailureAnalyzer(settings).analyze(record)
    assert analysis.failure_category is FailureCategory.TOOL_TIMEOUT
    assert analysis.cause_status is CauseStatus.CONFIRMED
    assert "configure_timeout:call_api:30" in analysis.prevention_actions


def test_silent_deploy_is_task_failure_not_tool_failure(settings) -> None:
    env = deploy_env(
        config={"APP_ENV": "production", "DATABASE_URL": "postgres://ok"},
        faults={"deploy_requires": {"app": {"env": ["DATABASE_URL"], "silent": True}}},
    )
    plan = Plan(
        task="Deploy the application",
        task_type="deploy_service",
        steps=[
            PlanStep(id="deploy", tool="deploy", args={"target": "app"}),
            PlanStep(id="verify", tool="verify_deployment", args={"target": "app"}),
        ],
    )
    record = _execute(plan, env, settings)
    assert record.outcome is OutcomeType.TASK_FAILURE
    # The deploy tool itself succeeded; the goal post-condition failed.
    assert record.traces[0].result.ok is True
    assert record.traces[-1].result.ok is False

    analysis = FailureAnalyzer(settings).analyze(record)
    assert analysis.failure_category is FailureCategory.INCORRECT_ASSUMPTION
    assert analysis.cause_status is CauseStatus.HYPOTHESIS
    assert analysis.prevention_actions == ["verify_outcome:app"]


def test_preventive_step_is_not_blamed_for_the_failure(settings) -> None:
    """A failing advisory step must not mask the real risky-action failure."""
    plan = Plan(
        task="Deploy the application",
        task_type="deploy_service",
        steps=[
            PlanStep(
                id="pv",
                tool="validate_config",
                args={"required": ["DATABASE_URL"]},
                is_prevention=True,
            ),
            PlanStep(id="deploy", tool="deploy", args={"target": "app"}),
        ],
    )
    record = _execute(plan, deploy_env(), settings)

    root = analyze_root_cause(record)
    assert root.primary.tool == "deploy"
    assert root.category is FailureCategory.MISSING_CONFIGURATION
    # Evidence from the preventive diagnostic is still merged in.
    assert any("DATABASE_URL" in e for e in root.evidence)


def test_no_failing_step_yields_unknown_hypothesis() -> None:
    record = ExecutionRecord(
        execution_id="ok",
        task="nothing fails",
        plan=Plan(task="nothing fails", task_type="generic", steps=[]),
        traces=[],
        outcome=OutcomeType.SUCCESS,
        success=True,
    )
    root = analyze_root_cause(record)
    assert root.category is FailureCategory.UNKNOWN
    assert root.status is CauseStatus.HYPOTHESIS
    assert root.confidence <= 0.4


def test_default_environment_has_no_faults(settings) -> None:
    plan = _single_step("call_api", {"service": "inventory_api"}, task="Call inventory api")
    record = _execute(plan, default_environment(), settings)
    assert record.success is True
