"""Unit tests for the sandboxed tools and the fault-injecting dispatcher.

These exercise each tool's success and failure branches directly against an
in-memory :class:`SimulatedEnvironment`; no host, network, or filesystem access
is involved.
"""

from __future__ import annotations

from backend.agent import tools
from backend.agent.environment import SimulatedEnvironment
from backend.agent.models import ToolResult
from backend.agent.tools import ToolSpec, invoke_tool
from backend.domain import OutcomeType


def test_as_list_handles_none_string_and_iterable() -> None:
    assert tools._as_list(None) == []
    assert tools._as_list(" a, b ,,c ") == ["a", "b", "c"]
    assert tools._as_list(["x", 1]) == ["x", "1"]


def test_check_env_reports_presence() -> None:
    env = SimulatedEnvironment(config={"DATABASE_URL": "postgres://demo"})

    present = tools.check_env(env, "DATABASE_URL")
    assert present.ok is True
    assert present.output["present"] is True

    absent = tools.check_env(env, "MISSING")
    assert absent.ok is True
    assert absent.output["present"] is False


def test_validate_config_accepts_comma_separated_string() -> None:
    env = SimulatedEnvironment(config={"A": "1", "B": "2"})
    result = tools.validate_config(env, required="A, B")
    assert result.ok is True
    assert env.has_flag("config_valid")


def test_validate_config_reports_missing_variables() -> None:
    env = SimulatedEnvironment(config={"A": "1"})
    result = tools.validate_config(env, required=["A", "B"])
    assert result.ok is False
    assert result.error_code == tools.ERR_MISSING_CONFIG
    assert result.metadata["missing"] == ["B"]


def test_check_dependency_and_install() -> None:
    env = SimulatedEnvironment(registry={"pandas": "2.2.0"})

    assert tools.check_dependency(env, "pandas").output["installed"] is False
    installed = tools.install_dependency(env, "pandas")
    assert installed.ok is True
    assert env.packages["pandas"] == "2.2.0"

    recheck = invoke_tool(env, "check_dependency", {"package": "pandas"})
    assert recheck.output["installed"] is True

    unavailable = tools.install_dependency(env, "nope")
    assert unavailable.ok is False
    assert unavailable.error_code == tools.ERR_MISSING_DEPENDENCY
    # The lesson extractor needs the real package name to build an actionable
    # prevention action instead of the "<required-package>" placeholder.
    assert unavailable.metadata["missing"] == ["nope"]


def test_load_config_missing_and_present() -> None:
    env = SimulatedEnvironment(secrets={"DATABASE_URL": "postgres://secret"})

    missing = tools.load_config(env, "ABSENT")
    assert missing.ok is False
    assert missing.error_code == tools.ERR_MISSING_CONFIG

    loaded = tools.load_config(env, "DATABASE_URL")
    assert loaded.ok is True
    assert env.config["DATABASE_URL"] == "postgres://secret"
    assert env.has_flag("config_loaded:DATABASE_URL")


def test_run_tests_failure_and_success() -> None:
    env = SimulatedEnvironment(faults={"failing_suites": ["default"]})

    failed = tools.run_tests(env, "default")
    assert failed.ok is False
    assert failed.error_code == tools.ERR_TEST_FAILURE

    passed = tools.run_tests(env, "other")
    assert passed.ok is True
    assert env.has_flag("tests_passed")


def test_call_api_invalid_payload_is_invalid_output() -> None:
    env = SimulatedEnvironment(faults={"api_modes": {"svc": "invalid_payload"}})
    result = tools.call_api(env, "svc")
    assert result.ok is False
    assert result.outcome_type is OutcomeType.INVALID_OUTPUT
    assert result.error_code == tools.ERR_INVALID_OUTPUT


def test_call_api_unknown_mode_defaults_to_success() -> None:
    env = SimulatedEnvironment(faults={"api_modes": {"svc": "surprising_mode"}})
    result = tools.call_api(env, "svc")
    assert result.ok is True
    assert result.output["status"] == 200
    assert env.has_flag("api_ok:svc")


def test_call_api_transient_requires_retry_and_backoff() -> None:
    env = SimulatedEnvironment(faults={"api_modes": {"svc": "transient"}})

    no_retry = tools.call_api(env, "svc")
    assert no_retry.ok is False
    assert no_retry.error_code == tools.ERR_INVALID_API_RESPONSE

    recovered = tools.call_api(env, "svc", retries=1, backoff=True)
    assert recovered.ok is True
    assert recovered.metadata["recovered"] is True


def test_start_service_branches() -> None:
    env = SimulatedEnvironment(
        services={"worker": {"required_env": ["TOKEN"], "required_packages": ["pandas"]}},
        registry={"pandas": "2.2.0"},
    )

    missing_env = tools.start_service(env, "worker")
    assert missing_env.ok is False
    assert missing_env.error_code == tools.ERR_MISSING_CONFIG

    env.config["TOKEN"] = "t"
    missing_pkg = tools.start_service(env, "worker")
    assert missing_pkg.ok is False
    assert missing_pkg.error_code == tools.ERR_MISSING_DEPENDENCY

    env.packages["pandas"] = "2.2.0"
    started = tools.start_service(env, "worker")
    assert started.ok is True
    assert env.has_flag("service_running:worker")


def test_deploy_missing_package_branch() -> None:
    env = SimulatedEnvironment(
        faults={"deploy_requires": {"app": {"env": [], "packages": ["flask"]}}}
    )
    result = tools.deploy(env, "app")
    assert result.ok is False
    assert result.error_code == tools.ERR_MISSING_DEPENDENCY


def test_write_read_wait_and_noop_tools() -> None:
    env = SimulatedEnvironment()

    written = invoke_tool(env, "write_file", {"path": "a.txt", "content": "hi"})
    assert written.ok is True
    assert env.files["a.txt"] == "hi"

    missing = invoke_tool(env, "read_file", {"path": "nope"})
    assert missing.ok is False
    assert missing.error_code == tools.ERR_MISSING_FILE

    read = invoke_tool(env, "read_file", {"path": "a.txt"})
    assert read.ok is True
    assert read.output["content"] == "hi"

    waited = invoke_tool(env, "wait_for", {"seconds": 3})
    assert waited.ok is True
    assert waited.output["waited_seconds"] == 3

    nooped = invoke_tool(env, "noop")
    assert nooped.ok is True


def test_invoke_unknown_tool_is_rejected() -> None:
    result = invoke_tool(SimulatedEnvironment(), "does_not_exist")
    assert result.ok is False
    assert result.error_code == tools.ERR_UNKNOWN_TOOL


def test_invoke_injects_invalid_output_fault() -> None:
    env = SimulatedEnvironment(faults={"invalid_output_tools": ["run_build"]})
    result = invoke_tool(env, "run_build")
    assert result.ok is False
    assert result.outcome_type is OutcomeType.INVALID_OUTPUT
    assert result.error_code == tools.ERR_INVALID_OUTPUT


def test_invoke_injects_permission_denied_fault() -> None:
    env = SimulatedEnvironment(faults={"permission_denied_tools": ["deploy"]})
    result = invoke_tool(env, "deploy")
    assert result.ok is False
    assert result.error_code == tools.ERR_PERMISSION_DENIED


def test_invoke_fail_once_then_succeeds() -> None:
    env = SimulatedEnvironment(faults={"fail_tools_once": {"run_build": 1}})

    first = invoke_tool(env, "run_build", attempt=1)
    assert first.ok is False
    assert first.error_code == tools.ERR_TRANSIENT

    second = invoke_tool(env, "run_build", attempt=2)
    assert second.ok is True


def test_invoke_rejects_invalid_arguments() -> None:
    result = invoke_tool(SimulatedEnvironment(), "run_build", {"unexpected": True})
    assert result.ok is False
    assert result.outcome_type is OutcomeType.INVALID_OUTPUT
    assert result.error_code == tools.ERR_INVALID_ARGS


def test_invoke_wraps_unexpected_tool_exception(monkeypatch) -> None:
    def boom(env: SimulatedEnvironment) -> ToolResult:
        raise ValueError("kaboom")

    monkeypatch.setitem(
        tools.TOOL_REGISTRY,
        "boom",
        ToolSpec(name="boom", description="explodes", parameters={}, func=boom),
    )

    result = invoke_tool(SimulatedEnvironment(), "boom")
    assert result.ok is False
    assert result.error_code == tools.ERR_TOOL_ERROR
    assert "ValueError" in (result.error or "")
