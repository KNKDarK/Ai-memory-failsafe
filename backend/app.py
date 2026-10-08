"""Core failure-memory primitives for the AI agent failsafe."""


def record_failure(task: str, cause: str) -> dict:
    """Store a structured failure record: Failure -> Cause -> Lesson."""
    if not task.strip():
        raise ValueError("task must not be empty")
    if not cause.strip():
        raise ValueError("cause must not be empty")
    return {"task": task, "cause": cause, "lesson": None}


def lesson_for(record: dict, lesson: str) -> dict:
    """Attach an actionable lesson to a failure record."""
    return {**record, "lesson": lesson}
