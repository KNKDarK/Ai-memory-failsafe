"""Rule-based root-cause detection.

The first failing step is treated as the primary cause because later failures
are usually downstream consequences of it. Each cause is classified as either
*confirmed* (direct, machine-checkable evidence such as an explicitly missing
variable) or a *hypothesis* (a plausible explanation that still needs
corroboration). The distinction is preserved all the way to storage and the UI.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.agent.models import ExecutionRecord, StepTrace
from backend.agent.tools import (
    ERR_INVALID_API_RESPONSE,
    ERR_INVALID_ARGS,
    ERR_INVALID_OUTPUT,
    ERR_MISSING_CONFIG,
    ERR_MISSING_DEPENDENCY,
    ERR_MISSING_FILE,
    ERR_PERMISSION_DENIED,
    ERR_RESOURCE_EXHAUSTED,
    ERR_TEST_FAILURE,
    ERR_TIMEOUT,
    ERR_TOOL_ERROR,
    ERR_TRANSIENT,
    ERR_UNKNOWN_TOOL,
    ERR_VERIFICATION_FAILED,
)
from backend.analysis.models import CauseCandidate
from backend.domain import CauseStatus, FailureCategory


@dataclass
class RootCauseResult:
    category: FailureCategory
    cause: str
    status: CauseStatus
    confidence: float
    evidence: list[str]
    primary: CauseCandidate
    alternatives: list[CauseCandidate]


# error_code -> (category, confirmed, cause template, base confidence)
_MAP: dict[str, tuple[FailureCategory, bool, str, float]] = {
    ERR_MISSING_CONFIG: (
        FailureCategory.MISSING_CONFIGURATION,
        True,
        "Required configuration/environment variable(s) were missing before the action.",
        0.92,
    ),
    ERR_MISSING_DEPENDENCY: (
        FailureCategory.MISSING_DEPENDENCY,
        True,
        "A required dependency was not installed or was unavailable.",
        0.9,
    ),
    ERR_TIMEOUT: (
        FailureCategory.TOOL_TIMEOUT,
        True,
        "The tool did not complete within its time budget and timed out.",
        0.9,
    ),
    ERR_INVALID_OUTPUT: (
        FailureCategory.INVALID_API_RESPONSE,
        True,
        "The external response/output could not be parsed as valid data.",
        0.85,
    ),
    ERR_INVALID_API_RESPONSE: (
        FailureCategory.INVALID_API_RESPONSE,
        False,
        "The API call failed; the underlying cause needs corroboration "
        "(transient vs. permanent is not yet proven).",
        0.6,
    ),
    ERR_PERMISSION_DENIED: (
        FailureCategory.PERMISSION_DENIED,
        True,
        "The action was denied because of missing permissions or credentials.",
        0.88,
    ),
    ERR_RESOURCE_EXHAUSTED: (
        FailureCategory.RESOURCE_EXHAUSTED,
        True,
        "A required resource was exhausted.",
        0.8,
    ),
    ERR_VERIFICATION_FAILED: (
        FailureCategory.INCORRECT_ASSUMPTION,
        False,
        "The agent assumed the action reached the goal, but the post-condition check failed.",
        0.65,
    ),
    ERR_TEST_FAILURE: (
        FailureCategory.INCORRECT_ASSUMPTION,
        False,
        "Tests failed, indicating the implementation did not meet expectations.",
        0.6,
    ),
    ERR_MISSING_FILE: (
        FailureCategory.UNKNOWN,
        False,
        "A required file/artifact was missing at the expected path.",
        0.6,
    ),
    ERR_TRANSIENT: (
        FailureCategory.UNKNOWN,
        False,
        "The tool failed transiently; the cause is not yet confirmed.",
        0.5,
    ),
    ERR_UNKNOWN_TOOL: (
        FailureCategory.INCORRECT_ASSUMPTION,
        True,
        "The agent tried to use a tool that is not permitted or does not exist.",
        0.9,
    ),
    ERR_INVALID_ARGS: (
        FailureCategory.INCORRECT_ASSUMPTION,
        True,
        "The agent invoked a tool with invalid arguments.",
        0.85,
    ),
    ERR_TOOL_ERROR: (
        FailureCategory.UNKNOWN,
        False,
        "The tool raised an unexpected error; more evidence is required.",
        0.5,
    ),
}

_DEFAULT = (
    FailureCategory.UNKNOWN,
    False,
    "The failure could not be attributed to a confirmed cause.",
    0.35,
)

# External / native error codes that mean the same thing as one of ours. This
# lets traces imported from other harnesses (ToolBench, SWE-bench, a plain
# POSIX errno, or a raw Python exception name) be analysed without first
# rewriting their error codes.
_CODE_ALIASES: dict[str, str] = {
    "ENOENT": ERR_MISSING_FILE,
    "FileNotFoundError": ERR_MISSING_FILE,
    "file_not_found": ERR_MISSING_FILE,
}

# A missing file that looks like configuration is a *missing-configuration*
# failure, not an unclassifiable one: the reusable lesson is "validate your
# prerequisites", never "create this one file".
_CONFIG_SUFFIXES = (
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".env",
    ".properties",
    ".xml",
)
_CONFIG_NAME_HINTS = ("config", "settings", "secret", "credential", ".env")


def looks_like_config_path(path: str) -> bool:
    """True when ``path`` points at something a deploy step would call config."""
    lowered = (path or "").lower().strip()
    if not lowered:
        return False
    name = lowered.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if name.endswith(_CONFIG_SUFFIXES):
        return True
    return any(hint in name for hint in _CONFIG_NAME_HINTS)


def _missing_path(trace: StepTrace) -> str | None:
    meta = trace.result.metadata or {}
    for key in ("path", "file", "filename"):
        value = meta.get(key)
        if value:
            return str(value)
    value = (trace.step.args or {}).get("path")
    return str(value) if value else None


def _string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value]
    return [str(value)]


def _contextualize(base: str, trace: StepTrace | None, category: FailureCategory) -> str:
    """Add concrete, evidence-derived detail to a generic cause description."""
    if trace is None:
        return base
    meta = trace.result.metadata or {}
    missing = meta.get("missing")
    if category is FailureCategory.MISSING_CONFIGURATION and missing:
        joined = ", ".join(_string_list(missing))
        return f"{base} Missing: {joined}."
    if category is FailureCategory.MISSING_DEPENDENCY and missing:
        joined = ", ".join(_string_list(missing))
        return f"{base} Missing: {joined}."
    service = meta.get("service")
    if category is FailureCategory.INVALID_API_RESPONSE and service:
        return f"{base} Affected service: {service}."
    return base


def _confidence_from(base: float, evidence: list[str]) -> float:
    """Corroboration raises confidence, but never to certainty."""
    bonus = min(0.07, 0.02 * max(0, len(evidence) - 1))
    return round(min(0.97, base + bonus), 4)


def analyze_root_cause(execution: ExecutionRecord) -> RootCauseResult:
    failed_raw = [t for t in execution.traces if not t.result.ok]
    if not failed_raw:
        # Should not be called on success, but be defensive.
        candidate = CauseCandidate(
            category=FailureCategory.UNKNOWN,
            cause="No failing step was recorded.",
            confidence=0.2,
            confirmed=False,
        )
        return RootCauseResult(
            category=FailureCategory.UNKNOWN,
            cause=candidate.cause,
            status=CauseStatus.HYPOTHESIS,
            confidence=0.2,
            evidence=[],
            primary=candidate,
            alternatives=[],
        )

    # A failed *preventive* step (e.g. configuration validation that correctly
    # reports a still-missing variable) is diagnostic context, not the root
    # failure. The real failure is the risky action that follows it.
    non_preventive = [t for t in failed_raw if not t.step.is_prevention]
    failed = non_preventive or failed_raw

    candidates: list[CauseCandidate] = []
    for trace in failed:
        raw_code = trace.result.error_code or ""
        code = _CODE_ALIASES.get(raw_code, raw_code)
        category, confirmed, template, base = _MAP.get(code, _DEFAULT)
        if code == ERR_MISSING_FILE:
            path = _missing_path(trace)
            if path and looks_like_config_path(path):
                # A missing config file is a *confirmed* missing-configuration
                # failure. The generalized cause explains why it happened (no
                # prerequisite check), not merely that the file was absent.
                category = FailureCategory.MISSING_CONFIGURATION
                confirmed = True
                base = 0.9
                template = (
                    f"Required configuration file '{path}' was missing before the "
                    "action; required configuration was not validated before access."
                )
        evidence = list(trace.result.evidence)
        if trace.result.error:
            evidence.append(trace.result.error)
        cause_text = _contextualize(template, trace, category)
        candidates.append(
            CauseCandidate(
                category=category,
                cause=cause_text,
                confidence=_confidence_from(base, evidence),
                confirmed=confirmed,
                error_code=code or None,
                tool=trace.result.tool,
                evidence=evidence,
            )
        )

    primary = candidates[0]
    alternatives = candidates[1:]
    # Merge evidence from ALL failing steps (including preventive diagnostics).
    merged_evidence: list[str] = []
    for trace in failed_raw:
        for item in list(trace.result.evidence) + (
            [trace.result.error] if trace.result.error else []
        ):
            if item and item not in merged_evidence:
                merged_evidence.append(item)

    status = CauseStatus.CONFIRMED if primary.confirmed else CauseStatus.HYPOTHESIS
    return RootCauseResult(
        category=primary.category,
        cause=primary.cause,
        status=status,
        confidence=primary.confidence,
        evidence=merged_evidence,
        primary=primary,
        alternatives=alternatives,
    )
