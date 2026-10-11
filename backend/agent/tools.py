"""Safe, deterministic tools for the simulated agent.

Every tool operates only on an in-memory :class:`SimulatedEnvironment`. None of
them read real environment variables, open sockets, touch the filesystem, or
run subprocesses. Faults are injected explicitly via ``environment.faults`` so
tests and the evaluation harness can create failures that are fully
reproducible.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.agent.environment import SimulatedEnvironment
from backend.agent.models import ToolResult
from backend.domain import OutcomeType

# --------------------------------------------------------------------------- #
# Error codes (mapped to failure categories by the analyzer)
# --------------------------------------------------------------------------- #
ERR_MISSING_CONFIG = "missing_config"
ERR_MISSING_DEPENDENCY = "missing_dependency"
ERR_INVALID_API_RESPONSE = "invalid_api_response"
ERR_TIMEOUT = "timeout"
ERR_INVALID_OUTPUT = "invalid_output"
ERR_PERMISSION_DENIED = "permission_denied"
ERR_RESOURCE_EXHAUSTED = "resource_exhausted"
ERR_VERIFICATION_FAILED = "verification_failed"
ERR_TRANSIENT = "transient_tool_failure"
ERR_UNKNOWN_TOOL = "unknown_tool"
ERR_INVALID_ARGS = "invalid_arguments"
ERR_TOOL_ERROR = "tool_error"
ERR_MISSING_FILE = "missing_file"
ERR_TEST_FAILURE = "test_failure"

_DURATIONS: dict[str, int] = {
    "check_env": 4,
    "validate_config": 6,
    "check_dependency": 5,
    "install_dependency": 25,
    "run_build": 40,
    "run_tests": 35,
    "call_api": 30,
    "start_service": 20,
    "deploy": 45,
    "verify_deployment": 3,
    "write_file": 4,
    "read_file": 3,
    "wait_for": 10,
    "noop": 1,
}
_DEFAULT_DURATION = 10
_TIMEOUT_MS = 5000


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, str]
    func: Callable[..., ToolResult]


def _result(
    tool: str,
    *,
    ok: bool,
    output: Any = None,
    error: str | None = None,
    error_code: str | None = None,
    evidence: list[str] | None = None,
    outcome: OutcomeType | None = None,
    metadata: dict[str, Any] | None = None,
    duration_ms: int | None = None,
) -> ToolResult:
    resolved_outcome = outcome or (OutcomeType.SUCCESS if ok else OutcomeType.TOOL_FAILURE)
    return ToolResult(
        tool=tool,
        ok=ok,
        outcome_type=resolved_outcome,
        output=output,
        error=error,
        error_code=error_code,
        evidence=evidence or [],
        metadata=metadata or {},
        duration_ms=_DURATIONS.get(tool, _DEFAULT_DURATION) if duration_ms is None else duration_ms,
    )


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [str(item) for item in value]


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #
def check_env(env: SimulatedEnvironment, name: str = "") -> ToolResult:
    """Check whether an environment variable is present (never reveals values)."""
    present = name in env.config
    return _result(
        "check_env",
        ok=True,
        output={"name": name, "present": present},
        evidence=[f"environment variable '{name}' is {'present' if present else 'missing'}"],
        metadata={"present": present},
    )


def validate_config(env: SimulatedEnvironment, required: Any = None) -> ToolResult:
    """Validate that required environment variables are present before a risky action."""
    required_list = _as_list(required)
    missing = [name for name in required_list if name not in env.config]
    if missing:
        return _result(
            "validate_config",
            ok=False,
            error=f"missing required environment variables: {', '.join(missing)}",
            error_code=ERR_MISSING_CONFIG,
            evidence=[f"required environment variable '{m}' is not set" for m in missing],
            metadata={"missing": missing, "required": required_list},
        )
    env.set_flag("config_valid")
    return _result(
        "validate_config",
        ok=True,
        output={"validated": required_list},
        evidence=[f"all {len(required_list)} required environment variables are present"],
        metadata={"required": required_list},
    )


def check_dependency(env: SimulatedEnvironment, package: str = "") -> ToolResult:
    installed = package in env.packages
    return _result(
        "check_dependency",
        ok=True,
        output={"package": package, "installed": installed, "version": env.packages.get(package)},
        evidence=[f"package '{package}' is {'installed' if installed else 'not installed'}"],
        metadata={"installed": installed},
    )


def install_dependency(
    env: SimulatedEnvironment, package: str = "", version: str | None = None
) -> ToolResult:
    if package not in env.registry:
        metadata: dict[str, object] = {"package": package}
        if package:
            # The lesson extractor reads result metadata["missing"] to name the
            # package in the machine-actionable prevention action; without this
            # a MISSING_DEPENDENCY lesson would fall back to a "<required-package>"
            # placeholder that the planner cannot act on.
            metadata["missing"] = [package]
        return _result(
            "install_dependency",
            ok=False,
            error=f"package '{package}' is not available in the registry",
            error_code=ERR_MISSING_DEPENDENCY,
            evidence=[f"registry lookup failed for '{package}'"],
            metadata=metadata,
        )
    resolved = version or env.registry[package]
    env.packages[package] = resolved
    env.set_flag(f"installed:{package}")
    return _result(
        "install_dependency",
        ok=True,
        output={"package": package, "version": resolved},
        evidence=[f"installed {package}=={resolved}"],
        metadata={"package": package, "version": resolved},
    )


def run_build(env: SimulatedEnvironment) -> ToolResult:
    required = _as_list(env.faults.get("build_requires", []))
    missing = [p for p in required if p not in env.packages]
    if missing:
        return _result(
            "run_build",
            ok=False,
            error=f"build failed: missing dependencies {', '.join(missing)}",
            error_code=ERR_MISSING_DEPENDENCY,
            evidence=[
                f"dependency '{p}' is required by the build but not installed" for p in missing
            ],
            metadata={"missing": missing},
        )
    env.set_flag("built")
    return _result(
        "run_build", ok=True, output={"status": "build ok"}, evidence=["build completed"]
    )


def load_config(env: SimulatedEnvironment, name: str = "") -> ToolResult:
    """Materialise a configuration value from the simulated secret store.

    This mirrors a real "fetch the secret before deploying" step and is the
    actionable fix for a missing-configuration lesson.
    """
    if name not in env.secrets:
        return _result(
            "load_config",
            ok=False,
            error=f"configuration '{name}' is not available in the secret store",
            error_code=ERR_MISSING_CONFIG,
            evidence=[f"secret store has no entry for '{name}'"],
            metadata={"missing": [name]},
        )
    env.config[name] = env.secrets[name]
    env.set_flag(f"config_loaded:{name}")
    return _result(
        "load_config",
        ok=True,
        output={"name": name, "loaded": True},
        evidence=[f"loaded configuration '{name}' from the secret store"],
        metadata={"name": name},
    )


def run_tests(env: SimulatedEnvironment, suite: str = "default") -> ToolResult:
    failing = _as_list(env.faults.get("failing_suites", []))
    if suite in failing:
        return _result(
            "run_tests",
            ok=False,
            error=f"test suite '{suite}' failed",
            error_code=ERR_TEST_FAILURE,
            evidence=[f"test suite '{suite}' reported failing assertions"],
            metadata={"suite": suite},
        )
    env.set_flag("tests_passed")
    return _result(
        "run_tests",
        ok=True,
        output={"suite": suite, "passed": True},
        evidence=[f"test suite '{suite}' passed"],
    )


def call_api(
    env: SimulatedEnvironment,
    service: str = "",
    retries: int = 0,
    backoff: bool = False,
    timeout_seconds: int = 5,
) -> ToolResult:
    """Call a simulated external service.

    ``retries`` + ``backoff`` together are the *prevention* learned from a
    transient-failure lesson: with them, a transient service recovers.
    ``timeout_seconds`` is the prevention for a timeout lesson.
    """
    env.bump(f"call_api:{service}")
    behaviour = dict(env.services.get(service, {}))
    mode = env.faults.get("api_modes", {}).get(service, behaviour.get("mode", "ok"))

    if mode == "ok":
        env.set_flag(f"api_ok:{service}")
        return _result(
            "call_api",
            ok=True,
            output={"service": service, "status": 200, "data": {"ok": True}},
            evidence=[f"{service} responded with HTTP 200"],
            metadata={"service": service},
        )
    if mode == "invalid_payload":
        return _result(
            "call_api",
            ok=False,
            outcome=OutcomeType.INVALID_OUTPUT,
            output="<malformed payload>",
            error=f"{service} returned a body that is not valid JSON",
            error_code=ERR_INVALID_OUTPUT,
            evidence=[f"{service} HTTP 200 but response body failed JSON parsing"],
            metadata={"service": service, "status": 200},
        )
    if mode == "flaky_invalid_payload":
        if retries >= 1:
            env.set_flag(f"api_ok:{service}")
            return _result(
                "call_api",
                ok=True,
                output={"service": service, "status": 200, "data": {"ok": True}, "recovered": True},
                evidence=[f"{service} returned valid data after a configured retry"],
                metadata={"service": service, "recovered": True},
            )
        return _result(
            "call_api",
            ok=False,
            outcome=OutcomeType.INVALID_OUTPUT,
            output="<malformed payload>",
            error=f"{service} returned a malformed payload and no retry was configured",
            error_code=ERR_INVALID_OUTPUT,
            evidence=[f"{service} returned a body that failed JSON parsing"],
            metadata={"service": service, "status": 200},
        )
    if mode in {"transient", "transient_failure"}:
        if retries >= 1 and backoff:
            env.set_flag(f"api_ok:{service}")
            return _result(
                "call_api",
                ok=True,
                output={"service": service, "status": 200, "data": {"ok": True}, "recovered": True},
                evidence=[f"{service} recovered after retry with backoff"],
                metadata={"service": service, "recovered": True},
            )
        return _result(
            "call_api",
            ok=False,
            error=f"{service} returned HTTP 503 (transient) without retry/backoff",
            error_code=ERR_INVALID_API_RESPONSE,
            evidence=[f"{service} transient HTTP 503; no retry/backoff applied"],
            metadata={"service": service, "status": 503, "transient": True},
        )
    if mode == "permanent_failure":
        return _result(
            "call_api",
            ok=False,
            error=f"{service} returned HTTP 500 persistently",
            error_code=ERR_INVALID_API_RESPONSE,
            evidence=[f"{service} returned HTTP 500 on every attempt"],
            metadata={"service": service, "status": 500, "transient": False},
        )
    env.set_flag(f"api_ok:{service}")
    return _result("call_api", ok=True, output={"service": service, "status": 200})


def start_service(env: SimulatedEnvironment, service: str = "") -> ToolResult:
    config_spec = dict(env.services.get(service, {}))
    required_env = _as_list(config_spec.get("required_env", []))
    required_pkgs = _as_list(config_spec.get("required_packages", []))
    missing_env = [name for name in required_env if name not in env.config]
    missing_pkgs = [p for p in required_pkgs if p not in env.packages]
    if missing_env:
        return _result(
            "start_service",
            ok=False,
            error=f"cannot start {service}: missing configuration {', '.join(missing_env)}",
            error_code=ERR_MISSING_CONFIG,
            evidence=[f"{service} failed to start because '{m}' is not set" for m in missing_env],
            metadata={"service": service, "missing": missing_env},
        )
    if missing_pkgs:
        return _result(
            "start_service",
            ok=False,
            error=f"cannot start {service}: missing dependencies {', '.join(missing_pkgs)}",
            error_code=ERR_MISSING_DEPENDENCY,
            evidence=[f"{service} requires package '{p}'" for p in missing_pkgs],
            metadata={"service": service, "missing": missing_pkgs},
        )
    env.set_flag(f"service_running:{service}")
    return _result(
        "start_service",
        ok=True,
        output={"service": service, "running": True},
        evidence=[f"{service} is running"],
    )


def deploy(env: SimulatedEnvironment, target: str = "app") -> ToolResult:
    """A composite, high-risk action used by the headline demo scenario."""
    spec = dict(env.faults.get("deploy_requires", {}).get(target, {}))
    required_env = _as_list(spec.get("env", ["DATABASE_URL"]))
    required_pkgs = _as_list(spec.get("packages", []))
    missing_env = [name for name in required_env if name not in env.config]
    missing_pkgs = [p for p in required_pkgs if p not in env.packages]
    if missing_env:
        return _result(
            "deploy",
            ok=False,
            error=f"deployment of '{target}' failed: missing configuration {', '.join(missing_env)}",
            error_code=ERR_MISSING_CONFIG,
            evidence=[f"deployment aborted because '{m}' is not set" for m in missing_env],
            metadata={"target": target, "missing": missing_env},
        )
    if missing_pkgs:
        return _result(
            "deploy",
            ok=False,
            error=f"deployment of '{target}' failed: missing dependencies {', '.join(missing_pkgs)}",
            error_code=ERR_MISSING_DEPENDENCY,
            evidence=[f"deployment requires package '{p}'" for p in missing_pkgs],
            metadata={"target": target, "missing": missing_pkgs},
        )
    if spec.get("silent"):
        # The action reports success but does not actually change state: the
        # goal post-condition will fail, exercising task-failure detection.
        return _result(
            "deploy",
            ok=True,
            output={"target": target, "deployed": False, "silent": True},
            evidence=[f"deployment of '{target}' reported success but did not change state"],
            metadata={"target": target, "silent": True},
        )
    env.set_flag(f"deployed:{target}")
    return _result(
        "deploy",
        ok=True,
        output={"target": target, "deployed": True},
        evidence=[f"deployment of '{target}' completed"],
        metadata={"target": target},
    )


def verify_deployment(env: SimulatedEnvironment, target: str = "app") -> ToolResult:
    if env.has_flag(f"deployed:{target}"):
        return _result(
            "verify_deployment",
            ok=True,
            output={"target": target, "verified": True},
            evidence=[f"verified '{target}' is deployed"],
        )
    return _result(
        "verify_deployment",
        ok=False,
        outcome=OutcomeType.TASK_FAILURE,
        error=f"task goal not achieved: '{target}' is not deployed",
        error_code=ERR_VERIFICATION_FAILED,
        evidence=["post-condition check failed: no deployment flag was set"],
        metadata={"target": target},
    )


def write_file(env: SimulatedEnvironment, path: str = "", content: str = "") -> ToolResult:
    env.files[path] = content
    env.set_flag(f"wrote:{path}")
    return _result("write_file", ok=True, output={"path": path}, evidence=[f"wrote file '{path}'"])


def read_file(env: SimulatedEnvironment, path: str = "") -> ToolResult:
    if path not in env.files:
        return _result(
            "read_file",
            ok=False,
            error=f"file '{path}' does not exist",
            error_code=ERR_MISSING_FILE,
            evidence=[f"read failed: '{path}' not found"],
            # `missing` lets the lesson extractor name the path in the
            # machine-actionable prevention instead of a placeholder.
            metadata={"path": path, "missing": [path]},
        )
    return _result("read_file", ok=True, output={"path": path, "content": env.files[path]})


def wait_for(env: SimulatedEnvironment, seconds: int = 1) -> ToolResult:
    return _result(
        "wait_for", ok=True, output={"waited_seconds": seconds}, evidence=[f"waited {seconds}s"]
    )


def noop(env: SimulatedEnvironment) -> ToolResult:
    return _result("noop", ok=True, output={}, evidence=["no-op"])


# --------------------------------------------------------------------------- #
# Registry + dispatcher
# --------------------------------------------------------------------------- #
TOOL_REGISTRY: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in [
        ToolSpec("check_env", "Check whether an env var is present", {"name": "str"}, check_env),
        ToolSpec(
            "validate_config",
            "Validate required env vars before a risky action",
            {"required": "str[]"},
            validate_config,
        ),
        ToolSpec(
            "check_dependency",
            "Check if a package is installed",
            {"package": "str"},
            check_dependency,
        ),
        ToolSpec(
            "install_dependency",
            "Install a package from the registry",
            {"package": "str", "version": "str?"},
            install_dependency,
        ),
        ToolSpec("run_build", "Build the project", {}, run_build),
        ToolSpec(
            "load_config",
            "Load a configuration value from the secret store",
            {"name": "str"},
            load_config,
        ),
        ToolSpec("run_tests", "Run a test suite", {"suite": "str"}, run_tests),
        ToolSpec(
            "call_api",
            "Call an external API (retries/backoff/timeout supported)",
            {"service": "str", "retries": "int", "backoff": "bool", "timeout_seconds": "int"},
            call_api,
        ),
        ToolSpec("start_service", "Start a service", {"service": "str"}, start_service),
        ToolSpec("deploy", "Deploy a target", {"target": "str"}, deploy),
        ToolSpec(
            "verify_deployment",
            "Verify a target is actually deployed",
            {"target": "str"},
            verify_deployment,
        ),
        ToolSpec("write_file", "Write a file", {"path": "str", "content": "str"}, write_file),
        ToolSpec("read_file", "Read a file", {"path": "str"}, read_file),
        ToolSpec("wait_for", "Wait for N seconds", {"seconds": "int"}, wait_for),
        ToolSpec("noop", "Do nothing", {}, noop),
    ]
}


def invoke_tool(
    env: SimulatedEnvironment, name: str, args: dict[str, Any] | None = None, *, attempt: int = 1
) -> ToolResult:
    """Invoke a tool, applying any configured fault injection first."""
    args = dict(args or {})
    spec = TOOL_REGISTRY.get(name)
    if spec is None:
        return _result(
            name,
            ok=False,
            error=f"unknown tool '{name}'",
            error_code=ERR_UNKNOWN_TOOL,
            evidence=[f"tool '{name}' is not in the permitted registry"],
        )

    timeouts = _as_list(env.faults.get("timeout_tools", []))
    if name in timeouts:
        required_timeout = int(env.faults.get("required_timeout_seconds", 30))
        provided_timeout = int(args.get("timeout_seconds", 5) or 5)
        if provided_timeout < required_timeout:
            return _result(
                name,
                ok=False,
                outcome=OutcomeType.TIMEOUT,
                error=(
                    f"tool '{name}' timed out after {provided_timeout}s "
                    f"(budget {required_timeout}s)"
                ),
                error_code=ERR_TIMEOUT,
                evidence=[
                    f"'{name}' did not respond within its {provided_timeout}s timeout window"
                ],
                duration_ms=_TIMEOUT_MS,
                metadata={
                    "timeout_seconds": provided_timeout,
                    "required_timeout_seconds": required_timeout,
                },
            )

    invalid_tools = _as_list(env.faults.get("invalid_output_tools", []))
    if name in invalid_tools:
        return _result(
            name,
            ok=False,
            outcome=OutcomeType.INVALID_OUTPUT,
            output="<unparseable output>",
            error=f"tool '{name}' produced output that failed validation",
            error_code=ERR_INVALID_OUTPUT,
            evidence=[f"'{name}' returned a malformed result"],
        )

    denied = _as_list(env.faults.get("permission_denied_tools", []))
    if name in denied:
        return _result(
            name,
            ok=False,
            error=f"tool '{name}' was denied by the sandbox policy",
            error_code=ERR_PERMISSION_DENIED,
            evidence=[f"permission denied while invoking '{name}'"],
        )

    fail_once = env.faults.get("fail_tools_once", {})
    remaining = int(fail_once.get(name, 0) or 0)
    if remaining > 0:
        fail_once[name] = remaining - 1
        env.faults["fail_tools_once"] = fail_once
        return _result(
            name,
            ok=False,
            error=f"tool '{name}' failed transiently (attempt {attempt})",
            error_code=ERR_TRANSIENT,
            evidence=[f"'{name}' raised a transient error on attempt {attempt}"],
        )

    try:
        return spec.func(env, **args)
    except TypeError:
        return _result(
            name,
            ok=False,
            outcome=OutcomeType.INVALID_OUTPUT,
            error=f"invalid arguments for tool '{name}': {sorted(args)}",
            error_code=ERR_INVALID_ARGS,
            evidence=[f"'{name}' rejected the provided arguments"],
        )
    except Exception as exc:  # noqa: BLE001 - sandbox boundary, never crash the agent
        return _result(
            name,
            ok=False,
            error=f"{type(exc).__name__}: {exc}",
            error_code=ERR_TOOL_ERROR,
            evidence=[f"'{name}' raised an unexpected error"],
        )
