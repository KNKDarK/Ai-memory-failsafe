# Developer SDK Integration Guide

The **Developer SDK** (`/api/v1/sdk/*`) provides a set of REST endpoints for external agents and tools to query prevention lessons, record failures, and submit outcome feedback. A Python client wrapper (`FailsafeClient`) is included in the `src/ai_memory_failsafe/` package.

---

## Quick Install

```bash
pip install -e src/ai_memory_failsafe/   # or: pip install ai-memory-failsafe-client
```

Or use directly from source:

```python
from ai_memory_failsafe.client import FailsafeClient, ConnectionError, FailsafeError
```

---

## REST API Endpoints

All endpoints are under the `/api/v1/sdk/` prefix on a running backend (default `http://localhost:8000`).

### 1. Query Prevention Lessons — `POST /api/v1/sdk/query-lessons`

Retrieve past failure lessons relevant to a current task description, filtered by confidence and scoped to a project.

**Request (`QueryLessonsRequest`):**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `task_description` | `str` (1–4096) | Yes | — | The current task/prompt to find relevant past failures for |
| `project_id` | `str` (1–256) | Yes | — | Project identifier to scope the search within a single project's memories |
| `agent_id` | `str` (1–128) | Yes | — | Agent requesting lessons; used for per-agent statistics |
| `min_confidence` | `float` (0.0–1.0) | No | `0.65` | Minimum confidence threshold; lessons below this are filtered out |
| `top_k` | `int` (1–50) | No | `5` | Maximum number of lessons to return |

**Response:**

```json
{
  "query": "Deploy the billing service",
  "lessons_found": 3,
  "lessons": [
    {
      "lesson_id": "a1b2c3d4e5f6",
      "failure_mode": "missing_configuration",
      "lesson_text": "Validate required environment variables before deployment.",
      "prevention_action": "Run config validation step before deploy action.",
      "confidence_score": 0.87,
      "verified": true
    }
  ]
}
```

**Status Codes:**

| Code | Meaning |
|------|---------|
| `200` | Success — lessons returned (may be empty list) |
| `400/422` | Validation error — missing or invalid fields |
| `503` | Storage unavailable — database is unreachable |

---

### 2. Record a Failure — `POST /api/v1/sdk/record-failure`

Ingest an execution trace and error message. The backend runs failure analysis, extracts a lesson from the root cause, and stores it as structured memory.

**Request (`RecordFailureRequest`):**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `project_id` | `str` (1–256) | Yes | — | Project identifier for grouping failures |
| `agent_id` | `str` (1–128) | Yes | — | Agent that encountered the failure |
| `task_input` | `str` (1–4096) | Yes | — | The original task/prompt that led to this failure |
| `action_trace` | `list[dict]` | No | `[]` | Ordered sequence of tool calls and results leading up to the failure |
| `error_message` | `str` (1–4096) | Yes | — | The error or exception message that caused this failure |

**Response:**

```json
{
  "lesson_id": "f7e8d9c0b1a2",
  "root_cause": "Required configuration 'DATABASE_URL' was missing before the deploy action.",
  "lesson_extracted": "Validate required environment variables before deploying.",
  "confidence_score": 0.75,
  "is_verified": false
}
```

**Status Codes:**

| Code | Meaning |
|------|---------|
| `200` | Success — lesson extracted and stored |
| `400/422` | Validation error — missing or invalid fields |
| `503` | Storage unavailable |

---

### 3. Submit Feedback — `POST /api/v1/sdk/feedback`

Update a lesson's confidence score and UCB1 bandit weights based on whether applying the lesson led to success or failure.

**Protected endpoint** — requires API token authentication when `API_AUTH_TOKEN` is configured (`Authorization: Bearer <token>`). Without it, the endpoint is open (local dev mode).

**Request (`FeedbackRequest`):**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `lesson_id` | `str` (1+) | Yes | — | Identifier of the lesson being rated |
| `agent_id` | `str` (1–128) | Yes | — | Agent providing the feedback |
| `task_success` | `bool` | Yes | — | Whether the task succeeded after applying this lesson |
| `project_id` | `str \| null` | No | `None` | Optional project identifier for per-project aggregation |

**Response:**

```json
{
  "lesson_id": "f7e8d9c0b1a2",
  "verdict": "useful",
  "success": true
}
```

**Status Codes:**

| Code | Meaning |
|------|---------|
| `200` | Success — feedback recorded, counters updated |
| `401` | Missing API token (when `API_AUTH_TOKEN` is set) |
| `403` | Invalid/wrong API token |
| `400/422` | Validation error |

---

## Python Client: FailsafeClient

The `FailsafeClient` wraps the three SDK endpoints in a synchronous, typed interface.

### Initialization

```python
from ai_memory_failsafe.client import FailsafeClient

# Without authentication (local dev mode)
client = FailsafeClient(base_url="http://localhost:8000")

# With API token (production / protected deployments)
client = FailsafeClient(base_url="http://your-server:8000", api_key="my-secret-token")

# As a context manager
with FailsafeClient(base_url="http://localhost:8000") as client:
    lessons = client.get_prevention_lessons(...)
```

### Methods

#### `get_prevention_lessons(task_description, project_id, agent_id, min_confidence=0.65, top_k=5)`

Query prevention lessons relevant to a task description.

```python
result = client.get_prevention_lessons(
    task_description="Deploy the billing service",
    project_id="payments",
    agent_id="agent-42",
    min_confidence=0.65,
    top_k=5,
)
# result: {"query": "Deploy...", "lessons_found": 3, "lessons": [...]}
```

#### `record_failure(task_input, action_trace, error_message, project_id="default_project", agent_id="default")`

Ingest an execution trace and error for root-cause analysis.

```python
result = client.record_failure(
    task_input="Deploy the application",
    action_trace=[{"tool": "deploy", "args": {"env": "production"}}],
    error_message="DATABASE_URL not set",
    project_id="payments",
    agent_id="agent-42",
)
# result: {"lesson_id": "...", "root_cause": "...", "confidence_score": 0.75, ...}
```

#### `report_outcome(lesson_id, task_success, project_id=None, agent_id="default")`

Submit outcome feedback for a previously retrieved lesson.

```python
result = client.report_outcome(
    lesson_id="f7e8d9c0b1a2",
    task_success=True,
    project_id="payments",
    agent_id="agent-42",
)
# result: {"lesson_id": "...", "verdict": "useful", "success": true}
```

### Error Handling

```python
from ai_memory_failsafe.client import FailsafeError, ConnectionError

try:
    lessons = client.get_prevention_lessons(...)
except ConnectionError as exc:
    print(f"Cannot reach backend: {exc}")
except FailsafeError as exc:
    print(f"HTTP error {exc.status_code}: {exc}")
```

| Exception | When raised |
|-----------|-------------|
| `ConnectionError` | Backend unreachable, timeout, or network error (`status_code=None`) |
| `FailsafeError` | HTTP 4xx/5xx response from the server (includes `status_code`) |

---

## Multi-Tenant Project Isolation

The SDK supports project-scoped operations via the `project_id` parameter:

```python
# Agent in "payments" project records a failure
client.record_failure(
    task_input="Deploy billing service",
    action_trace=[...],
    error_message="DATABASE_URL not set",
    project_id="payments",  # Scoped to payments project
)

# Query lessons — only lessons from the same project are returned
lessons = client.get_prevention_lessons(
    task_description="Deploy the billing service",
    project_id="payments",  # Same scope
    agent_id="agent-42",
)
```

Project isolation ensures that:
- Lessons recorded under `project_A` are not surfaced when querying for `project_B`.
- Feedback submitted under one project does not affect another project's lesson statistics.
- Each project maintains its own confidence scores and UCB1 bandit weights.

---

## Handling Low-Confidence Memory Rejections

When a lesson is retrieved but not applied, the client can inspect rejection reasons from the Replay Lab dashboard or trace data:

```python
# In the treatment arm's retrieved_memories:
for memory in treatment_trace.retrieved_memories:
    if not memory.applied and memory.retrieval_reason:
        reason = memory.rejection_reason
        if reason == "below_confidence_gate":
            print(f"Lesson {memory.lesson_id} rejected: confidence below gate")
            # Consider lowering min_confidence or waiting for more evidence
        elif reason == "contradiction_detected":
            print(f"Lesson {memory.lesson_id} suppressed by contradiction")
```

On the SDK side, set `min_confidence` to control the filtering threshold:

```python
# Higher threshold — only high-confidence lessons returned
lessons = client.get_prevention_lessons(
    task_description="Critical deployment",
    project_id="payments",
    agent_id="agent-42",
    min_confidence=0.9,  # Strict gate for critical operations
)

# Lower threshold — include all lessons with some confidence
lessons = client.get_prevention_lessons(
    task_description="Low-stakes experiment",
    project_id="payments",
    agent_id="agent-42",
    min_confidence=0.3,  # Lenient gate for experiments
)
```

---

## Full Integration Example

```python
from ai_memory_failsafe.client import FailsafeClient, ConnectionError, FailsafeError


def run_task_with_failure_memory(task: str, project_id: str = "default_project") -> dict:
    """Execute a task with failure-memory lesson retrieval built in."""
    client = FailsafeClient(base_url="http://localhost:8000", api_key=None)

    # Step 1: Retrieve relevant lessons before acting
    try:
        result = client.get_prevention_lessons(
            task_description=task,
            project_id=project_id,
            agent_id="my-agent",
            min_confidence=0.65,
            top_k=3,
        )
        lessons = result.get("lessons", [])
    except (ConnectionError, FailsafeError) as exc:
        print(f"Retrieval failed: {exc}")
        lessons = []

    # Step 2: Apply prevention guidance to your task execution...
    # (agent logic goes here — inject lesson_text into prompts, etc.)

    # Step 3: After execution, report outcome for each applied lesson
    for lesson in lessons[:1]:  # Assume first lesson was applied
        try:
            client.report_outcome(
                lesson_id=lesson["lesson_id"],
                task_success=True,  # or False if it failed anyway
                project_id=project_id,
                agent_id="my-agent",
            )
        except Exception as exc:
            print(f"Feedback error: {exc}")

    return {"task": task, "lessons_applied": len(lessons)}
```
