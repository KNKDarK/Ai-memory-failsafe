#!/usr/bin/env python3
"""Example external agent demonstrating FailsafeClient usage.

This script shows the full lifecycle:
    1. Query prevention lessons before execution
    2. Simulate an execution error (API key expired, endpoint unreachable)
    3. Record the failure trace and extract root cause
    4. Send outcome feedback to the backend store

Run with a running backend::

    python examples/external_agent.py

Without a backend, it demonstrates graceful error handling by catching
``FailsafeError`` exceptions and printing informative messages.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Ensure the project root is on sys.path so the package can be imported.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ai_memory_failsafe.client import ConnectionError, FailsafeClient, FailsafeError

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
logger = logging.getLogger("external_agent_example")


def simulate_execution(task_description: str) -> dict:
    """Simulate a task execution that may succeed or fail.

    In this example we always "fail" with a simulated API key expiry error so the
    failure-recording path is exercised.  Change ``always_fail`` to False to see
    a successful path instead.
    """
    always_fail = True  # Set to False to simulate success

    if always_fail:
        raise RuntimeError(
            "API key expired while calling billing_api — request returned HTTP 401"
        )
    return {"status": "ok", "data": {"balance": 1250.0}}


def main() -> None:
    # ------------------------------------------------------------------ #
    # 1. Initialise the client
    # ------------------------------------------------------------------ #
    base_url = "http://localhost:8000"
    logger.info("Initialising FailsafeClient (base_url=%s)", base_url)

    try:
        with FailsafeClient(base_url=base_url, api_key=None) as client:
            _run_lifecycle(client)
    except ConnectionError as exc:
        # Backend is not running — print a helpful message and exit cleanly.
        logger.warning("Backend unreachable at %s", base_url)
        logger.info(
            "Start the backend with:\n"
            "  cd Ai-memory-failsafe && uvicorn backend.api.routes:app --reload\n"
            f"\nConnection error (expected when no backend is running):\n"
            "  {exc}"
        )
        # Still demonstrate the local flow so the code path is covered.
        _run_lifecycle_local()


def _run_lifecycle(client: FailsafeClient) -> None:
    """Full lifecycle against a live backend."""

    # ------------------------------------------------------------------ #
    # 2. Query prevention lessons before execution
    # ------------------------------------------------------------------ #
    task = "Call the billing API to fetch user balances"
    logger.info("Step 1 — Querying prevention lessons for: %s", task)

    try:
        result = client.get_prevention_lessons(
            task_description=task,
            project_id="payments",
            agent_id="external-agent-01",
            min_confidence=0.65,
            top_k=3,
        )
        lessons_found = result.get("lessons_found", 0)
        logger.info("   Found %d relevant lesson(s)", lessons_found)

        for i, lesson in enumerate(result.get("lessons", []), start=1):
            logger.info(
                "   Lesson %d — [%s] confidence=%.2f: %s",
                i,
                lesson["failure_mode"],
                lesson["confidence_score"],
                lesson["lesson_text"][:100],
            )

    except FailsafeError as exc:
        logger.warning("Query failed (server returned error): %s", exc)

    # ------------------------------------------------------------------ #
    # 3. Simulate execution & record failure on error
    # ------------------------------------------------------------------ #
    logger.info("Step 2 — Executing task …")

    action_trace = [
        {"tool": "call_api", "args": {"service": "billing_api", "method": "GET", "path": "/balances"}, "output": None},
    ]

    try:
        simulate_execution(task)
        logger.info("   Task succeeded — no failure to record.")

    except Exception as exc:
        error_message = str(exc)
        logger.warning("   Execution failed: %s", error_message)

        logger.info("Step 3 — Recording failure trace …")
        try:
            resp = client.record_failure(
                task_input=task,
                action_trace=action_trace,
                error_message=error_message,
                project_id="payments",
                agent_id="external-agent-01",
            )
            logger.info("   Root cause: %s", resp.get("root_cause", "unknown"))
            logger.info("   Lesson extracted: %s", resp.get("lesson_extracted", "")[:100])
            logger.info(
                "   Confidence=%.2f  verified=%s  lesson_id=%s",
                resp.get("confidence_score", 0),
                resp.get("is_verified"),
                resp.get("lesson_id", ""),
            )

        except FailsafeError as exc:
            logger.warning("Record failure failed (server returned error): %s", exc)

    # ------------------------------------------------------------------ #
    # 4. Submit outcome feedback
    # ------------------------------------------------------------------ #
    lesson_id = "demo-lesson-placeholder"  # In real usage this comes from record_failure
    logger.info("Step 4 — Sending outcome feedback for lesson %s …", lesson_id)

    try:
        fb = client.report_outcome(
            lesson_id=lesson_id,
            task_success=False,
            project_id="payments",
            agent_id="external-agent-01",
        )
        logger.info("   Feedback recorded — verdict=%s", fb.get("verdict"))

    except FailsafeError as exc:
        logger.warning("Report outcome failed (server returned error): %s", exc)


def _run_lifecycle_local() -> None:
    """Demonstrate the client API flow without a live backend.

    This covers all code paths so the example is useful even when no backend
    is running — it shows graceful error handling and prints the expected
    response shapes.
    """
    logger.info("\n--- Running demo without backend (local simulation) ---\n")

    with FailsafeClient(base_url="http://localhost:8000", api_key=None) as client:
        # 1. Query lessons — will raise ConnectionError, handled gracefully.
        try:
            client.get_prevention_lessons(
                task_description="Call the billing API",
                project_id="payments",
                agent_id="demo-agent",
            )
        except FailsafeError as exc:
            logger.info("  [ConnectionError] %s", exc)

        # 2. Record failure — same graceful handling.
        try:
            client.record_failure(
                task_input="Call the billing API",
                action_trace=[{"tool": "call_api"}],
                error_message="API key expired (HTTP 401)",
                project_id="payments",
                agent_id="demo-agent",
            )
        except FailsafeError as exc:
            logger.info("  [ConnectionError] %s", exc)

        # 3. Report outcome — same graceful handling.
        try:
            client.report_outcome(lesson_id="some-lesson-id", task_success=False)
        except FailsafeError as exc:
            logger.info("  [ConnectionError] %s", exc)

    logger.info("\nDemo complete — all error paths handled gracefully.")


if __name__ == "__main__":
    main()
