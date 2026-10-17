# Demo Walkthrough — Recording Script

A four-act script that shows the whole loop on screen:

> **Failure → Cause → Lesson → Plan modification → Future prevention**

Everything below was executed against the real backend and is reproducible
offline; expected values are included so you can tell a good recording from a
glitched one.

---

## 0. Before you record

```bash
# terminal 1 — backend
uvicorn backend.app:app --port 8001 --reload

# terminal 2 — frontend
cd frontend && npm run dev
```

Open <http://localhost:3000>. Confirm the top health strip says the store is
available — if the backend port differs, fix `frontend/.env.local`
(`NEXT_PUBLIC_API_BASE_URL`).

Optional clean slate (the demo writes real memories to `data/memory.db`):

```bash
curl -s localhost:8001/api/memories | python -c "import sys,json;[print(m['id']) for m in json.load(sys.stdin)['items']]"
curl -X DELETE localhost:8001/api/memories/<id>
```

> **Use the built-in preset.** The Environment preset **Build — missing
> dependency** (task `Build the project`) is the scenario that reliably fails
> and then recovers. A free-typed prompt such as *"Check if 'requests' is
> installed and run tests"* does **not** fail in this sandbox: `check_dependency`
> is a read-only query and the registry has `requests`, so there is no fault to
> learn from. Presets map 1:1 to the tested scenarios.

---

## Act 1 — The failure

**Tab:** `Agent Sandbox`

1. **Environment preset** → `Build — missing dependency`
2. **Mode** → `memory`, **Max attempts** → `2`
3. Press **▶ Run Agent**

**What you should see on screen (verified):**

- Attempt 1 fails at `run_build` with
  `missing_dependency — build failed: missing dependencies pandas`
- The failure analysis card shows `missing_dependency`, **confirmed**, with
  root cause *"A required dependency was not installed or was unavailable.
  Missing: pandas."*
- Attempt 2 shows a **different plan**: the preventive steps
  `check_dependency` → `install_dependency` appear **before** `run_build`
- Final badge: **Success**, `attempt 2 of 2`, *Failure prevented*

<details>
<summary>Voice-over line</summary>

"Nothing was cached from the task text — the agent simply failed because `pandas`
was not installed. Watch the plan on the second attempt: two steps were
*inserted* ahead of the build."

</details>

---

## Act 2 — The memory extraction

**Tab:** `Memory Bank`

Find the new `missing_dependency` row and expand it (inline row, no navigation).

**What you should see (verified):**

| Field | Expected |
| --- | --- |
| `failure_category` | `missing_dependency` |
| `cause_status` | `confirmed` |
| `confidence` | `0.92` (effective `0.96` after feedback) |
| `root_cause` | *"A required dependency was not installed or was unavailable. Missing: pandas."* |
| `lesson` | *"Install and verify required dependencies before 'run_build'."* |
| `prevention_actions` | `["install_dependency:pandas"]` |
| `status` | `active` (lifecycle **fresh**) |

<details>
<summary>Voice-over line</summary>

"This is the part most error logs skip: it records *why*, not just *what*. Note
the prevention is machine-actionable — `install_dependency:pandas` — which is
what lets the planner act on it instead of just printing advice."

</details>

---

## Act 3 — The prevention

Stay in **Agent Sandbox** and press **▶ Run Agent** again with the same preset.

**What you should see (verified):**

- **`attempt 1 of 1`** — no failure at all this time
- The trace begins with `check_dependency` → `install_dependency`, then
  `run_build` → `run_tests`
- `retrieved_memory_ids` and `memory_ids_applied` contain the memory from Act 2
- Final badge: **Success**

<details>
<summary>Voice-over line</summary>

"Same task, same environment, one attempt instead of two — the memory was
retrieved *before* the agent acted and rewrote the plan. The lesson generalises:
a `requirements.txt` or a different package would hit the same prevention."

</details>

---

## Act 4 — The auditability

Two places prove this was principled rather than lucky:

**a) In the Agent Sandbox**, scroll to **"Why each memory was (or wasn't) used"**
— one row per candidate showing rank, similarity, score, matched terms, and
whether it was *surfaced* / *filtered* and *applied* / *not applied*.

**b) The `Retrieval` tab** — run the preview to see similarity score, matched
terms, and the two independent gates (score floor **and** similarity floor) that
decide selection. Selection is separate from application: a memory can be
surfaced yet still blocked by the confidence threshold.

**Optional closing shots**

- Press **⇄ Compare** for a side-by-side baseline-vs-memory run of the same task
  (baseline can never recover — there is nothing to retrieve).
- **`Evaluation` tab**: three arms (baseline **15.4%** → memory **69.2%**),
  naive arm showing **4 harmful applications** vs. **0** validated, the
  retrieval-method comparison, and the lifecycle breakdown — all read from
  `GET /api/evaluation/report`, none hardcoded in the UI.
- Mention the `naive` mode in the Mode dropdown (carries an on-screen warning):
  it applies every memory with no validation, which is exactly what isolates the
  value of the guard rails.

---

## Quick verification (no recording required)

```bash
ENV='{"id":"demo","registry":{"pandas":"2.2.0","requests":"2.31.0"},"packages":{},"faults":{"build_requires":["pandas"]}}'
curl -s -X POST localhost:8001/api/tasks/run -H 'content-type: application/json' \
  -d "{\"task\":\"Build the project\",\"mode\":\"memory\",\"max_attempts\":2,\"environment\":$ENV}"
```

Expected: `final_success: true`, `attempts_used: 2`, one id in both
`memory_ids_created` and `memory_ids_applied`.
