"""Lesson extraction: turn a diagnosed cause into actionable guidance.

Lessons are stored as free text *plus* machine-actionable prevention actions of
the form ``"<action>:<parameter>"`` (for example
``"validate_config:DATABASE_URL"``). The planner understands this small,
explicit vocabulary, which is what lets a retrieved memory change the next plan
in a way that is auditable rather than magical.
"""

from __future__ import annotations

from backend.agent.models import ExecutionRecord
from backend.analysis.root_cause import RootCauseResult
from backend.domain import FailureCategory


def _collect_missing(execution: ExecutionRecord) -> list[str]:
    missing: list[str] = []
    for trace in execution.traces:
        if trace.result.ok:
            continue
        value = (trace.result.metadata or {}).get("missing")
        if isinstance(value, list):
            for item in value:
                text = str(item)
                if text and text not in missing:
                    missing.append(text)
        elif value:
            text = str(value)
            if text not in missing:
                missing.append(text)
    return missing


def _find_service(execution: ExecutionRecord) -> str | None:
    for trace in execution.traces:
        if trace.result.ok:
            continue
        service = (trace.result.metadata or {}).get("service")
        if service:
            return str(service)
    return None


def _find_target(execution: ExecutionRecord) -> str:
    for step in execution.plan.steps:
        if step.tool == "deploy":
            return str(step.args.get("target", "app"))
    for trace in execution.traces:
        target = (trace.result.metadata or {}).get("target")
        if target:
            return str(target)
    return "app"


def _looks_like_path(name: str) -> bool:
    """True when a missing "configuration" name is really a file path."""
    text = (name or "").strip()
    if not text:
        return False
    if "/" in text or "\\" in text:
        return True
    suffix = text.lower().rsplit(".", 1)[-1]
    return suffix in {
        "json",
        "yaml",
        "yml",
        "toml",
        "ini",
        "cfg",
        "conf",
        "env",
        "properties",
        "xml",
    }


def extract_lesson(root: RootCauseResult, execution: ExecutionRecord) -> dict[str, object]:
    """Return ``{lesson, prevention, prevention_actions, tags, action}``."""
    failed_tool = root.primary.tool or "the action"
    missing = _collect_missing(execution)
    service = _find_service(execution)
    target = _find_target(execution)
    category = root.category

    if category is FailureCategory.MISSING_CONFIGURATION:
        names = missing or ["<required-config>"]
        file_like = [name for name in names if _looks_like_path(name)]
        if file_like:
            # A missing *configuration file* generalises to "validate your
            # deployment prerequisites before execution" — not "create this one
            # file", which would only ever help that single path again.
            lesson = (
                "Before deploying, verify that all required configuration files "
                "and environment-specific settings are present and readable."
            )
            prevention = (
                "Add a pre-execution prerequisite check that validates required "
                "configuration files and secrets before the risky action begins; "
                "if a required item is missing, stop and report it explicitly."
            )
            actions = [f"validate_config:{name}" for name in names]
        else:
            lesson = (
                f"Before '{failed_tool}', ensure all required configuration is present: "
                "validate it and load it from the secret store if missing."
            )
            prevention = (
                "Validate required configuration before the risky action, and load the "
                "values from the secret store when they are absent."
            )
            actions = [f"validate_config:{name}" for name in names]
            actions += [f"load_config:{name}" for name in names]
        tags = ["configuration", "environment", "prevention"]

    elif category is FailureCategory.MISSING_DEPENDENCY:
        names = missing or ["<required-package>"]
        lesson = f"Install and verify required dependencies before '{failed_tool}'."
        prevention = (
            "Check the dependency manifest and install missing packages before running the action."
        )
        actions = [f"install_dependency:{name}" for name in names]
        tags = ["dependencies", "setup", "prevention"]

    elif category is FailureCategory.INVALID_API_RESPONSE:
        lesson = (
            "API failures can be transient: retry with exponential backoff and "
            "validate the response payload before using it."
        )
        prevention = (
            "Wrap the API call in a retry-with-backoff policy and validate the response schema."
        )
        base = "call_api:retries=1,backoff=true"
        actions = [f"{base}:{service}"] if service else [base]
        tags = ["api", "retry", "backoff", "prevention"]

    elif category is FailureCategory.TOOL_TIMEOUT:
        lesson = f"Give '{failed_tool}' an explicit timeout and a bounded retry budget."
        prevention = "Fail fast on timeout instead of hanging, then retry within a budget."
        if failed_tool == "call_api":
            actions = [f"configure_timeout:{failed_tool}:30", "retry_with_backoff"]
        else:
            actions = ["set_timeout", "retry_with_backoff"]
        tags = ["timeout", "reliability", "prevention"]

    elif category is FailureCategory.INCORRECT_ASSUMPTION:
        lesson = "Do not assume the action reached the goal; verify the post-condition."
        prevention = "Add an explicit verification step and branch on the observed result."
        actions = [f"verify_outcome:{target}"]
        tags = ["verification", "assumption", "prevention"]

    elif category is FailureCategory.PERMISSION_DENIED:
        lesson = "Check permissions and credentials before invoking the protected action."
        prevention = "Pre-flight a permission check and surface missing credentials early."
        actions = ["check_permissions"]
        tags = ["permissions", "security", "prevention"]

    elif category is FailureCategory.RESOURCE_EXHAUSTED:
        lesson = "Check available resources before running the action."
        prevention = "Add a resource pre-check and reduce concurrency to fit the budget."
        actions = ["check_resources"]
        tags = ["resources", "capacity", "prevention"]

    else:
        lesson = "Capture more evidence before retrying; the root cause is not confirmed."
        prevention = "Add tracing around the failed step and reproduce it deterministically."
        actions = ["inspect_evidence"]
        tags = ["investigation", "unknown"]

    return {
        "lesson": lesson,
        "prevention": prevention,
        "prevention_actions": actions,
        "tags": tags,
        "action": failed_tool,
    }
