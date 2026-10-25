# Memory Replay Lab

The **Memory Replay Lab** is a side-by-side evaluation harness that runs the same task twice under identical conditions — once with failure-memory retrieval disabled (**baseline**) and once with it enabled (**treatment**) — then reports real metric deltas between the two arms.

---

## Architectural Flow

```
┌─────────────────────────────────────────────────────┐
│                 Replay Run Trigger                   │
│  POST /api/lab/replay { scenario_id, task_input }   │
└──────────────────┬──────────────────────────────────┘
                   │
        ┌──────────▼──────────┐
        │  MemoryReplayLab    │
        │  .run_replay()      │
        └───────┬─────┬───────┘
                │     │
   ┌────────────▼     ▼────────────┐
   │ Baseline Arm              Treatment Arm          │
   │ memory_enabled = false    memory_enabled = true  │
   │ No retrieval              Retrieval + application│
   └────────────┬───────────────┬────────────────────┘
                │               │
        ┌───────▼───────┐ ┌────▼──────────────┐
        │ ExecutionTrace│ │ ExecutionTrace    │
        │ (no memory)   │ │ (with memory)     │
        └───────┬───────┘ └────┬──────────────┘
                │              │
        ┌───────▼──────────────▼───────────────┐
        │      MetricDelta Computation          │
        │  success_improved, attempts_saved     │
        │  time_saved_ms, memories_applied_count│
        └──────────────┬───────────────────────┘
                       │
            ┌──────────▼──────────┐
            │ ReplayRunResponse   │
            │ (JSON)              │
            └─────────────────────┘
```

### Step-by-step execution

1. **Baseline arm** — `MemoryReplayLab._run_arm(task_input, env, mode="baseline")` executes the agent's task with memory retrieval disabled. The orchestrator runs without loading any failure lessons. A full `ExecutionTrace` is captured: steps, tool calls, errors, wall-clock duration.

2. **Treatment arm** — `_run_arm(task_input, env, mode="memory")` runs the same task against an identical environment clone (cloned so both arms see the exact same conditions). Memory retrieval is active; retrieved lessons are injected into the agent's plan via `prevention_injections`. A complete trace with `retrieved_memories` and `applied` flags is captured.

3. **Delta computation** — `_compute_delta(baseline, treatment)` calculates:
   - `success_improved`: boolean — true only when baseline failed and treatment succeeded.
   - `attempts_saved`: int — `max(0, baseline.total_attempts − treatment.total_attempts)`.
   - `time_saved_ms`: float — `baseline.execution_time_ms − treatment.execution_time_ms` (negative means treatment was slower).
   - `memories_applied_count`: count of unique lesson IDs that were applied during the treatment run.

4. **Response** — `ReplayRunResponse` is serialised as JSON with `replay_id`, `scenario_id`, `execution_mode`, both traces, and the delta dict. The frontend dashboard renders this in two side-by-side panels plus a delta summary row.

---

## Baseline vs Treatment Evaluation Mechanics

| Aspect | Baseline (Memory Disabled) | Treatment (Memory Enabled) |
|--------|---------------------------|----------------------------|
| `memory_enabled` | `false` | `true` |
| Retrieval | None | Retrieves lessons from store via retriever |
| Prevention injection | None | Lessons injected into plan as `prevention_injections` |
| `retrieved_memories` | Empty list | All lessons considered, with attribution metadata |
| Step traces | Full execution steps | Full execution steps (may differ due to prevention) |

Both arms use the **same environment clone** and the **same orchestrator settings**, ensuring that any metric difference is attributable solely to memory retrieval and application.

---

## Attribution Inspector Fields

Each entry in `retrieved_memories` carries these fields:

| Field | Type | Description |
|-------|------|-------------|
| `lesson_id` | `str` | Unique identifier of the referenced failure memory |
| `lesson_text` | `str` | The extracted lesson text that was retrieved |
| `retrieval_strategy` | `str` | Strategy used: `"bm25"`, `"tfidf"`, `"embedding"`, or `"hybrid"` |
| `similarity_score` | `float` (0–1) | Text-similarity score between current task and this memory |
| `confidence_score` | `float` (0–1) | Confidence of the lesson at retrieval time |
| `retrieved` | `bool` | Whether the retriever surfaced this memory for this run |
| `applied` | `bool` | Whether the lesson was injected into the execution plan |
| `rejection_reason` | `str \| null` | Why a retrieved lesson was **not** applied (see below) |
| `is_root_cause_verified` | `bool` | Whether the root cause of this memory's source failure is confirmed (`true`) or still a hypothesis (`false`) |

### Rejection Reasons

When a lesson is retrieved but not applied, `rejection_reason` explains why:

| Value | Meaning |
|-------|---------|
| `"below_confidence_gate"` | The lesson's confidence was below the retrieval/application threshold |
| `"contradiction_detected"` | Another memory provides conflicting prevention advice; this one is suppressed |

### Root Cause Verification Status

- **Confirmed** — evidence (environment state, tool output) supports the root cause claim. Shown with a green badge in the UI.
- **Unverified** — no direct evidence yet; the cause is a hypothesis. Shown with an amber/warn badge.

---

## Real Metric Delta Calculations

The `delta` dict in the response contains four computed values:

```python
success_improved = (not baseline.success) and treatment.success
attempts_saved   = max(0, baseline.total_attempts - treatment.total_attempts)
time_saved_ms    = round(baseline.execution_time_ms - treatment.execution_time_ms, 3)
memories_applied_count = len(unique_applied_lesson_ids ∪ prevention_injections)
```

- `success_improved` is a **boolean** — it flips only when memory turns an otherwise-failing run into success.
- `attempts_saved` and `time_saved_ms` are **numeric deltas** (can be zero or negative).
- `memories_applied_count` counts both lessons in `retrieved_memories` where `applied=True` **and** any items in `prevention_injections` that may not appear as individual attributions.

---

## API Reference

### POST `/api/lab/replay`

Request body (`ReplayRunRequest`):

```json
{
  "scenario_id": "missing_config_deploy",
  "task_input": "Deploy the application with DATABASE_URL present.",
  "execution_mode": "simulated",
  "project_id": "default_project"
}
```

| Field | Type | Required | Default |
|-------|------|----------|---------|
| `scenario_id` | `str` (1–256 chars) | Yes | — |
| `task_input` | `str` (1–4096 chars) | Yes | — |
| `execution_mode` | `"simulated" \| "real"` | No | `"simulated"` |
| `project_id` | `str` (1–256 chars) | No | `"default_project"` |

Response body (`ReplayRunResponse`):

```json
{
  "replay_id": "a3f9c8d1e2b4",
  "scenario_id": "missing_config_deploy",
  "execution_mode": "simulated",
  "baseline": { ... ExecutionTrace ... },
  "treatment": { ... ExecutionTrace ... },
  "delta": {
    "success_improved": true,
    "attempts_saved": 1,
    "time_saved_ms": -342.5,
    "memories_applied_count": 1
  }
}
```

---

## Frontend Dashboard

Navigate to **`/lab`** in the Next.js dashboard:

1. Enter a `scenario_id` and `task_input` (or use the preset values).
2. Choose execution mode — **Simulated** (default) or **Real**.
3. Click **▶ Run Replay**.
4. Review the side-by-side panels:
   - **Baseline (Memory Disabled)** — no-memory execution with attempts, duration, steps, and prevention rules.
   - **Treatment (Memory Enabled)** — memory-augmented execution with the same metrics plus an embedded **Memory Attribution Inspector** showing each retrieved lesson's confidence bar, strategy badge, root-cause status, and rejection reasons.
5. The delta summary row above the panels shows computed metric deltas dynamically from the backend response.

---

## Testing

Full test coverage lives in `backend/tests/test_replay_lab.py`:

```bash
python -m pytest backend/tests/test_replay_lab.py -v
```

Tests cover: engine execution, trace schema compliance, rejection reason capture, metric delta accuracy, API endpoint validation (422 on missing fields), and direct class-level tests.
