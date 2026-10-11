"""Secret redaction: memories and traces must never persist credentials."""

from __future__ import annotations

from backend.agent.models import ExecutionRecord, Plan, PlanStep, StepTrace, ToolResult
from backend.analysis.failure_analyzer import FailureAnalyzer
from backend.domain import OutcomeType
from backend.security import SecretRedactor, build_default_redactor


def test_redacts_api_key_assignments() -> None:
    redactor = SecretRedactor()
    output = redactor.redact("api_key=supersecretvalue123")
    assert "supersecretvalue123" not in output
    assert "[REDACTED]" in output


def test_redacts_bearer_tokens() -> None:
    redactor = SecretRedactor()
    output = redactor.redact("Authorization: Bearer abcdefghijklmnop1234567890")
    assert "abcdefghijklmnop1234567890" not in output


def test_redacts_url_credentials() -> None:
    redactor = SecretRedactor()
    output = redactor.redact("https://user:password@example.com/db")
    assert "password" not in output


def test_redacts_configured_extra_secret() -> None:
    redactor = SecretRedactor(extra_secrets=["sk-my-super-secret-value"])
    assert "sk-my-super-secret-value" not in redactor.redact(
        "using key sk-my-super-secret-value now"
    )


def test_disabled_redactor_is_a_passthrough() -> None:
    redactor = SecretRedactor(enabled=False)
    assert redactor.redact("api_key=abc") == "api_key=abc"


def test_redact_mapping_walks_nested_structures() -> None:
    redactor = SecretRedactor()
    output = redactor.redact_mapping(
        {"a": "api_key=xyzxyzxyz", "b": ["Bearer abcdefghijklmnopqrstuvwxyz"]}
    )
    assert "xyzxyzxyz" not in output["a"]
    assert "abcdefghijklmnopqrstuvwxyz" not in output["b"][0]


def test_default_redactor_includes_configured_api_key() -> None:
    class FakeSettings:
        llm_api_key = "sk-configured-secret-1234567890"
        redact_secrets = True

    redactor = build_default_redactor(FakeSettings())  # type: ignore[arg-type]
    assert "sk-configured-secret-1234567890" not in redactor.redact(
        "key sk-configured-secret-1234567890"
    )


def test_analyzer_redacts_secrets_from_failure_text(settings) -> None:
    step = PlanStep(id="s", tool="call_api", args={})
    secret_error = "request failed with api_key=leak-me-1234567890"
    result = ToolResult(
        tool="call_api",
        ok=False,
        outcome_type=OutcomeType.TOOL_FAILURE,
        error=secret_error,
        error_code="invalid_api_response",
    )
    record = ExecutionRecord(
        execution_id="e1",
        task="Call the billing api",
        plan=Plan(task="Call the billing api", task_type="fetch_api_data", steps=[step]),
        traces=[StepTrace(index=0, step=step, result=result)],
        outcome=OutcomeType.TOOL_FAILURE,
        success=False,
        error=secret_error,
    )

    analysis = FailureAnalyzer(settings).analyze(record)
    assert "leak-me-1234567890" not in analysis.failure
    assert all("leak-me-1234567890" not in item for item in analysis.evidence)
