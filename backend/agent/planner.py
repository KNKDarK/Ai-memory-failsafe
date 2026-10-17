"""Task planning and memory-guided plan adjustment.

The planner is deterministic. It has two jobs:

1. Turn a task string into a base plan using a fixed vocabulary of task types.
2. Translate *machine-actionable* prevention actions from retrieved memories
   into concrete plan steps (or step-argument changes), recording exactly which
   memory caused each change so the decision is auditable.
"""

from __future__ import annotations

import re

from backend.agent.environment import SimulatedEnvironment
from backend.agent.models import Plan, PlanStep, Recommendation

TASK_TYPE_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("deploy_service", ("deploy", "release", "rollout", "ship", "launch")),
    # Dependency tasks must be matched *before* fetch_api_data: the word
    # "requests" contains "request", so without this precedence a
    # "check if requests is installed" task would be routed to an API call.
    (
        "dependency_check",
        ("install", "installed", "dependency", "dependencies", "library", "libraries"),
    ),
    ("build_project", ("build", "compile", "package", "test suite")),
    ("fetch_api_data", ("fetch", "call", "api", "request", "download", "integrate", "sync")),
    ("run_migration", ("migrate", "migration", "schema", "database update")),
]

# Tokens that are never, on their own, the package a dependency task refers to.
_PACKAGE_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "it",
        "them",
        "this",
        "that",
        "and",
        "then",
        "if",
        "not",
        "is",
        "are",
        "be",
        "to",
        "for",
        "with",
        "some",
        "any",
        "all",
        "missing",
        "required",
        "package",
        "packages",
        "library",
        "libraries",
        "module",
        "modules",
        "dependency",
        "dependencies",
        "requirement",
        "requirements",
    }
)

# Prevention actions the planner understands. Others are advisory text only.
_ACTIONABLE_PREFIXES = ("validate_config:", "install_dependency:", "call_api:", "verify_outcome:")


def detect_package(task: str) -> str:
    """Best-effort, deterministic package-name extraction from a task string.

    Prefers an explicitly quoted name, then a name adjacent to an install or
    dependency word. Returns ``""`` when nothing package-like is present rather
    than guessing.
    """
    if not task:
        return ""
    quoted = re.search(r"['\"`]([A-Za-z0-9_.\-]+)['\"`]", task)
    if quoted:
        return quoted.group(1)
    lowered = task.lower()
    patterns = (
        r"\b(?:install|installed|reinstall|uninstall)\s+(?:the\s+)?([a-z0-9_.\-]+)",
        r"\b([a-z0-9_.\-]+)\s+(?:library|package|module|dependency|dependencies|requirements?)\b",
        r"\b([a-z0-9_.\-]+)\s+(?:is\s+|are\s+)?installed\b",
    )
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if match and match.group(1) not in _PACKAGE_STOPWORDS:
            return match.group(1)
    return ""


def detect_task_type(task: str) -> str:
    lowered = (task or "").lower()
    for task_type, keywords in TASK_TYPE_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            return task_type
    return "generic"


def _detect_target(task: str) -> str:
    match = re.search(
        r"\b(?:deploy|release|rollout|launch)\s+(?:the\s+)?([a-z0-9_\-]+)", task.lower()
    )
    if match and match.group(1) not in {"the", "a", "an", "app", "application"}:
        return match.group(1)
    return "app"


def _detect_service(task: str, env: SimulatedEnvironment | None) -> str:
    services = list((env.services if env else {}).keys())
    lowered = (task or "").lower()
    for service in services:
        token = service.replace("_api", "").replace("_", " ")
        if service in lowered or token in lowered:
            return service
    return services[0] if services else "billing_api"


class TaskPlanner:
    """Builds base plans and applies memory-guided preventions."""

    def plan(self, task: str, env: SimulatedEnvironment | None = None) -> Plan:
        task_type = detect_task_type(task)
        if task_type == "deploy_service":
            target = _detect_target(task)
            steps = [
                PlanStep(
                    id="deploy",
                    tool="deploy",
                    description=f"Deploy {target}",
                    args={"target": target},
                ),
                PlanStep(
                    id="verify",
                    tool="verify_deployment",
                    description=f"Verify {target} is deployed",
                    args={"target": target},
                ),
            ]
            goal_flags = [f"deployed:{target}"]
        elif task_type == "dependency_check":
            package = detect_package(task)
            steps = [
                PlanStep(
                    id="check_deps",
                    tool="check_dependency",
                    description=(
                        f"Check whether {package} is installed"
                        if package
                        else "Check whether the required dependencies are installed"
                    ),
                    args={"package": package},
                )
            ]
            if package:
                steps.append(
                    PlanStep(
                        id=f"install_dep_{package}",
                        tool="install_dependency",
                        description=f"Install {package} if it is missing",
                        args={"package": package},
                    )
                )
            steps.append(
                PlanStep(
                    id="test",
                    tool="run_tests",
                    description="Run the test suite",
                    args={"suite": "default"},
                )
            )
            goal_flags = ["tests_passed"]
        elif task_type == "build_project":
            steps = [
                PlanStep(id="build", tool="run_build", description="Build the project", args={}),
                PlanStep(
                    id="test",
                    tool="run_tests",
                    description="Run the test suite",
                    args={"suite": "default"},
                ),
            ]
            goal_flags = ["built", "tests_passed"]
        elif task_type == "fetch_api_data":
            service = _detect_service(task, env)
            steps = [
                PlanStep(
                    id="api",
                    tool="call_api",
                    description=f"Call {service}",
                    args={"service": service, "retries": 0, "backoff": False},
                )
            ]
            goal_flags = [f"api_ok:{service}"]
        elif task_type == "run_migration":
            steps = [
                PlanStep(id="migrate", tool="noop", description="Run migration", args={}),
            ]
            goal_flags = []
        else:
            steps = [PlanStep(id="noop", tool="noop", description="No-op", args={})]
            goal_flags = []
        return Plan(
            task=task,
            task_type=task_type,
            steps=steps,
            goal_flags=goal_flags,
            strategy="default",
        )

    # ------------------------------------------------------------------ #
    def apply_preventions(
        self, plan: Plan, recommendations: list[Recommendation]
    ) -> tuple[Plan, list[str]]:
        """Return a new plan with applicable preventions applied.

        Mutates ``recommendations`` in place to record what was applied. Returns
        the new plan and the list of memory ids that changed it.
        """
        steps = [step.model_copy(deep=True) for step in plan.steps]
        applied_memory_ids: list[str] = []

        config_vars: list[str] = []
        config_source: str | None = None
        load_vars: list[tuple[str, str]] = []  # (name, source_memory_id)
        packages: list[tuple[str, str]] = []  # (package, source_memory_id)
        api_fixes: dict[str, str] = {}  # service-or-"*" -> source memory id
        timeout_fixes: dict[str, int] = {}  # tool -> timeout seconds
        verify_targets: list[tuple[str, str]] = []

        for rec in recommendations:
            rec_changed = False
            for action in rec.prevention_actions:
                if action.startswith("validate_config:"):
                    name = action.split(":", 1)[1].strip()
                    if name and name not in config_vars:
                        config_vars.append(name)
                        config_source = rec.memory_id
                        rec_changed = True
                elif action.startswith("load_config:"):
                    name = action.split(":", 1)[1].strip()
                    if name and all(name != n for n, _ in load_vars):
                        load_vars.append((name, rec.memory_id))
                        rec_changed = True
                elif action.startswith("install_dependency:"):
                    package = action.split(":", 1)[1].strip()
                    if package and all(package != p for p, _ in packages):
                        packages.append((package, rec.memory_id))
                        rec_changed = True
                elif action.startswith("call_api:"):
                    parts = action.split(":")
                    service = parts[2] if len(parts) > 2 else "*"
                    api_fixes[service] = rec.memory_id
                    rec_changed = True
                elif action.startswith("configure_timeout:"):
                    parts = action.split(":")
                    tool = parts[1].strip() if len(parts) > 1 else ""
                    try:
                        seconds = int(parts[2]) if len(parts) > 2 else 30
                    except ValueError:
                        seconds = 30
                    if tool:
                        timeout_fixes[tool] = max(timeout_fixes.get(tool, 0), seconds)
                        rec_changed = True
                elif action.startswith("verify_outcome:"):
                    target = action.split(":", 1)[1].strip() or "app"
                    verify_targets.append((target, rec.memory_id))
                    rec_changed = True
            rec.applied = rec.applicable and rec_changed
            if rec.applied:
                applied_memory_ids.append(rec.memory_id)
                rec.followed = True
                rec.reason = (rec.reason + "; applied to plan").strip("; ")

        if not applied_memory_ids:
            return Plan(**plan.model_dump()), []

        preventive_front: list[PlanStep] = []
        for name, source in load_vars:
            preventive_front.append(
                PlanStep(
                    id=f"prevent_load_config_{name}",
                    tool="load_config",
                    description=f"Preventive: load configuration {name}",
                    args={"name": name},
                    is_prevention=True,
                    prevention_source=source,
                )
            )
        if config_vars:
            preventive_front.append(
                PlanStep(
                    id="prevent_validate_config",
                    tool="validate_config",
                    description="Preventive: validate required configuration",
                    args={"required": list(config_vars)},
                    is_prevention=True,
                    prevention_source=config_source,
                )
            )
        for package, source in packages:
            preventive_front.append(
                PlanStep(
                    id=f"prevent_check_dep_{package}",
                    tool="check_dependency",
                    description=f"Preventive: check dependency {package}",
                    args={"package": package},
                    is_prevention=True,
                    prevention_source=source,
                    optional=True,
                )
            )
            preventive_front.append(
                PlanStep(
                    id=f"prevent_install_dep_{package}",
                    tool="install_dependency",
                    description=f"Preventive: install dependency {package}",
                    args={"package": package},
                    is_prevention=True,
                    prevention_source=source,
                    optional=True,
                )
            )

        # Apply API retry/backoff and timeout fixes in place. Note: these steps
        # remain *risky* (not advisory), so we only tag their source and do NOT
        # set is_prevention (which would make a real failure non-fatal).
        for step in steps:
            if step.tool == "call_api":
                service = str(step.args.get("service", "*"))
                source = api_fixes.get(service) or api_fixes.get("*")
                if source:
                    step.args["retries"] = 1
                    step.args["backoff"] = True
                    step.prevention_source = source
                if step.tool in timeout_fixes:
                    step.args["timeout_seconds"] = timeout_fixes[step.tool]
                    step.prevention_source = step.prevention_source or "timeout"

        # Ensure verification steps exist for verify_outcome preventions.
        existing_verify = {
            str(s.args.get("target", "app")) for s in steps if s.tool == "verify_deployment"
        }
        for target, source in verify_targets:
            if target not in existing_verify:
                steps.append(
                    PlanStep(
                        id=f"prevent_verify_{target}",
                        tool="verify_deployment",
                        description=f"Preventive: verify {target} reached its goal",
                        args={"target": target},
                        is_prevention=True,
                        prevention_source=source,
                    )
                )

        new_plan = Plan(
            task=plan.task,
            task_type=plan.task_type,
            steps=preventive_front + steps,
            strategy="memory_guided",
            notes=[f"applied {len(applied_memory_ids)} prevention(s) from memory"],
        )
        return new_plan, list(dict.fromkeys(applied_memory_ids))


def parse_prevention_action(action: str) -> tuple[str, dict[str, str]]:
    """Parse ``"kind:params..."`` into ``(kind, params)`` for the API/UI."""
    if ":" not in action:
        return action, {}
    kind, _, rest = action.partition(":")
    if kind == "call_api":
        # call_api:retries=1,backoff=true[:service]
        body, _, service = rest.partition(":")
        params = {"service": service} if service else {}
        for pair in body.split(","):
            if "=" in pair:
                key, _, value = pair.partition("=")
                params[key.strip()] = value.strip()
        return kind, params
    return kind, {"value": rest}
