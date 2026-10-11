"""Unit tests for deterministic task planning and memory-guided prevention.

The planner turns a task string into a base plan and translates a small,
explicit prevention vocabulary into auditable plan changes. These tests pin the
task-type routing, target/service detection, every prevention kind, and the
public :func:`parse_prevention_action` helper used by the API/UI.
"""

from __future__ import annotations

from backend.agent.environment import SimulatedEnvironment, default_environment
from backend.agent.models import Recommendation
from backend.agent.planner import (
    TaskPlanner,
    detect_package,
    detect_task_type,
    parse_prevention_action,
)


def _rec(memory_id: str, *actions: str) -> Recommendation:
    return Recommendation(
        memory_id=memory_id,
        prevention="prevent it",
        prevention_actions=list(actions),
        confidence=0.9,
        applicable=True,
        reason="relevant and trustworthy",
    )


def test_detect_task_type_routes_and_falls_back_to_generic() -> None:
    assert detect_task_type("Build the project") == "build_project"
    assert detect_task_type("Run the schema migration") == "run_migration"
    assert detect_task_type("Deploy the application") == "deploy_service"
    assert detect_task_type("Fetch data from the billing api") == "fetch_api_data"
    # No keyword matches at all: the deterministic fallback.
    assert detect_task_type("Tidy up the documentation") == "generic"
    assert detect_task_type("") == "generic"


def test_detect_task_type_routes_dependency_tasks_before_api() -> None:
    # "requests" contains "request", so dependency routing must win over
    # fetch_api_data (the regression this guard exists to prevent).
    assert (
        detect_task_type(
            "Check if the 'requests' library is installed, and if not, install it and run a test."
        )
        == "dependency_check"
    )
    assert detect_task_type("Install the missing dependencies") == "dependency_check"
    assert detect_task_type("Make sure pandas is installed") == "dependency_check"


def test_detect_package_variants() -> None:
    assert detect_package("Install pandas") == "pandas"
    assert detect_package("check if 'requests' is installed") == "requests"
    assert detect_package("The numpy library must be present") == "numpy"
    assert detect_package("install requests==2.31.0") == "requests"
    assert detect_package("Make sure pandas is installed") == "pandas"
    # Nothing package-like to extract: never guess a bare stop word.
    assert detect_package("Install the missing dependencies") == ""
    assert detect_package("check if it is installed") == ""
    assert detect_package("") == ""


def test_plan_dependency_check_builds_check_install_and_test_steps() -> None:
    plan = TaskPlanner().plan(
        "Check if the 'requests' library is installed, and if not, install it and run a test."
    )

    assert plan.task_type == "dependency_check"
    assert [step.tool for step in plan.steps] == [
        "check_dependency",
        "install_dependency",
        "run_tests",
    ]
    assert plan.steps[0].args["package"] == "requests"
    assert plan.steps[1].args["package"] == "requests"
    assert plan.steps[2].args["suite"] == "default"


def test_plan_dependency_check_without_named_package_skips_install() -> None:
    plan = TaskPlanner().plan("Install the missing dependencies")

    assert plan.task_type == "dependency_check"
    # No package to install, so the plan only observes and then tests.
    assert [step.tool for step in plan.steps] == ["check_dependency", "run_tests"]


def test_plan_builds_migration_and_generic_plans() -> None:
    planner = TaskPlanner()

    migration = planner.plan("Run the schema migration")
    assert migration.task_type == "run_migration"
    assert [step.tool for step in migration.steps] == ["noop"]

    generic = planner.plan("Tidy up the documentation")
    assert generic.task_type == "generic"
    assert [step.tool for step in generic.steps] == ["noop"]


def test_plan_detects_named_deploy_target() -> None:
    plan = TaskPlanner().plan("Deploy the payments service")
    assert plan.task_type == "deploy_service"
    assert plan.steps[0].args["target"] == "payments"


def test_plan_service_selection_falls_back() -> None:
    planner = TaskPlanner()

    env = SimulatedEnvironment(services={"orders_api": {}, "billing_api": {}})
    with_services = planner.plan("Fetch the daily summary", env)
    assert with_services.task_type == "fetch_api_data"
    # No service name/token appears in the task, so the first service wins.
    assert with_services.steps[0].args["service"] == "orders_api"

    without_env = planner.plan("Fetch the daily summary", None)
    assert without_env.steps[0].args["service"] == "billing_api"


def test_apply_preventions_without_recommendations_returns_an_unchanged_plan() -> None:
    planner = TaskPlanner()
    plan = planner.plan("Build the project")

    new_plan, applied = planner.apply_preventions(plan, [])

    assert applied == []
    assert new_plan.steps == plan.steps
    assert new_plan.strategy == "default"


def test_apply_preventions_builds_front_steps_and_api_fixes() -> None:
    planner = TaskPlanner()
    plan = planner.plan("Fetch data from the billing api", default_environment())
    recommendations = [
        _rec("mem1", "validate_config:DATABASE_URL", "load_config:DATABASE_URL"),
        _rec("mem2", "install_dependency:pandas", "call_api:retries=1:billing_api"),
        _rec("mem3", "configure_timeout:call_api:45"),
        _rec("mem4", "verify_outcome:checkout"),
        _rec("mem5", "advisory:do something"),  # unrecognised -> advisory only
    ]

    new_plan, applied = planner.apply_preventions(plan, recommendations)

    assert new_plan.strategy == "memory_guided"
    # The advisory-only memory changed nothing and is not counted as applied.
    assert applied == ["mem1", "mem2", "mem3", "mem4"]

    front_tools = [step.tool for step in new_plan.steps if step.is_prevention]
    assert front_tools[:2] == ["load_config", "validate_config"]
    assert "check_dependency" in front_tools
    assert "install_dependency" in front_tools

    api_step = next(step for step in new_plan.steps if step.tool == "call_api")
    assert api_step.args["retries"] == 1
    assert api_step.args["backoff"] is True
    assert api_step.args["timeout_seconds"] == 45

    # verify_outcome requested a target the base plan does not verify yet.
    verify = [step for step in new_plan.steps if step.tool == "verify_deployment"]
    assert any(step.args.get("target") == "checkout" for step in verify)

    assert [rec.applied for rec in recommendations] == [True, True, True, True, False]


def test_apply_preventions_handles_malformed_timeout() -> None:
    planner = TaskPlanner()
    plan = planner.plan("Fetch data from the billing api", default_environment())
    recommendations = [_rec("mem-timeout", "configure_timeout:call_api:not-a-number")]

    new_plan, applied = planner.apply_preventions(plan, recommendations)

    assert applied == ["mem-timeout"]
    api_step = next(step for step in new_plan.steps if step.tool == "call_api")
    # A non-numeric timeout falls back to the 30s default rather than crashing.
    assert api_step.args["timeout_seconds"] == 30


def test_parse_prevention_action_variants() -> None:
    # No parameters at all.
    assert parse_prevention_action("advisory") == ("advisory", {})

    # call_api carries comma-separated key=value pairs plus an optional service.
    kind, params = parse_prevention_action("call_api:retries=1,backoff=true:billing_api")
    assert kind == "call_api"
    assert params == {"service": "billing_api", "retries": "1", "backoff": "true"}

    # Everything else is reported as a single positional value.
    assert parse_prevention_action("validate_config:DATABASE_URL") == (
        "validate_config",
        {"value": "DATABASE_URL"},
    )
