# backend/agent/analyzer.py
from typing import Any

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Pydantic Output Schema
# --------------------------------------------------------------------------- #
class AnalyzedFailure(BaseModel):
    fault_category: str = Field(
        ...,
        description=(
            "Must be one of: 'missing_dependency', 'missing_configuration', "
            "'transient_api_error', 'permanent_api_error', 'malformed_payload', "
            "'tool_timeout', 'incorrect_assumption'"
        ),
    )
    root_cause: str = Field(
        ..., description="A concise, factual technical statement of why the tool failed."
    )
    lesson: str = Field(..., description="Generalizable rule learned from this specific failure.")
    prevention_strategy: str = Field(
        ..., description="Human-readable execution advice for future attempts."
    )
    prevention_actions: list[str] = Field(
        ...,
        description=(
            "Executable prevention actions using strict vocabulary, e.g., "
            "['verify_file_exists:config/prod.json', 'create_config:config/prod.json']"
        ),
    )
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence score in the root cause diagnosis."
    )


# --------------------------------------------------------------------------- #
# System & User Prompt Design
# --------------------------------------------------------------------------- #
SYSTEM_ANALYZER_PROMPT = """You are an expert AI Agent Failure Diagnostic System.
Your job is to analyze failed tool executions and extract precise, structured, and reusable failure memories.

CRITICAL RULES:
1. NO ABSTRACT PLACEHOLDERS: Never output placeholders like `<file_path>`, `<pkg>`, or `<key>`. Always extract literal paths, names, and identifiers from tool_arguments or error_details.
2. FAULT TAXONOMY: You MUST classify the failure into exactly one of these categories:
   - missing_dependency
   - missing_configuration
   - transient_api_error
   - permanent_api_error
   - malformed_payload
   - tool_timeout
   - incorrect_assumption
3. PREVENTION VOCABULARY: Every action in `prevention_actions` MUST use standard action prefixes followed by exact parameters:
   - `verify_file_exists:<path>`
   - `create_default_config:<path>`
   - `install_dependency:<package>`
   - `check_dependency:<package>`
   - `retry_with_exponential_backoff`
   - `validate_schema:<schema_name>`
4. CONFIDENCE SCORING:
   - 0.90 - 1.00: Deterministic errors with explicit system error codes (e.g., ENOENT, ModuleNotFoundError).
   - 0.60 - 0.89: Ambiguous runtime errors with identifiable patterns.
   - 0.00 - 0.59: Silent failures or unparseable errors.

OUTPUT FORMAT:
Respond strictly with a valid JSON object matching this structure:
{
  "fault_category": "<category>",
  "root_cause": "<concise explanation>",
  "lesson": "<reusable lesson>",
  "prevention_strategy": "<human-readable strategy>",
  "prevention_actions": ["<action_prefix>:<parameter>"],
  "confidence": <float_between_0_and_1>
}"""


USER_PROMPT_TEMPLATE = """Analyze the following agent execution failure:

Task Request: {original_task}
Tool Executed: {tool_executed}
Tool Arguments: {tool_arguments}
Error Details: {error_details}
"""


# --------------------------------------------------------------------------- #
# Deterministic Fallback Analyzer (For Offline / Non-LLM Execution)
# --------------------------------------------------------------------------- #
def analyze_failure_deterministically(payload: dict[str, Any]) -> AnalyzedFailure:
    """Fallback analyzer using rule-based parsing when no LLM is configured."""
    error_info = payload.get("error_details", {})
    err_msg = str(error_info.get("message", "")).lower()
    err_code = str(error_info.get("error_code", ""))
    tool_args = payload.get("tool_arguments", {})

    # ENOENT / File Not Found
    if err_code == "ENOENT" or "file not found" in err_msg or "no such file" in err_msg:
        path = tool_args.get("path") or tool_args.get("file_path") or "config/prod.json"
        return AnalyzedFailure(
            fault_category="missing_configuration",
            root_cause=f"Required configuration file '{path}' is missing from the workspace.",
            lesson=f"Before reading settings from '{path}', verify file existence or create a baseline template.",
            prevention_strategy=f"Pre-flight check for file existence at path '{path}'.",
            prevention_actions=[f"verify_file_exists:{path}"],
            confidence=0.95,
        )

    # Default fallback
    return AnalyzedFailure(
        fault_category="incorrect_assumption",
        root_cause=f"Tool '{payload.get('tool_executed')}' failed with error: {err_msg}",
        lesson="Verify tool input assumptions prior to execution.",
        prevention_strategy="Validate runtime prerequisites.",
        prevention_actions=["validate_prerequisites"],
        confidence=0.60,
    )
