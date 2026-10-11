# Architecture

> Status: this document describes the code in this repository. If the code and
> this document disagree, the code is authoritative.

## Goals & non-goals

**Goals**

- Turn every task failure into a structured, reusable memory.
- Retrieve the right memory before the next attempt and adapt the plan.
- Never silently trust a discredited or irrelevant memory.
- Run **offline and deterministically** on any machine (AMD, NVIDIA, CPU, Mac),
  with no GPU and no API key required.
- Keep every improvement claim measurable against a baseline.

**Non-goals**

- A general-purpose agent. The planner is a small deterministic rule engine, not
  a language model. Prevention only works for the explicit prevention vocabulary.
- Real tool execution. Tools run against an in-memory sandbox only.

## Components

```text
backend/
  config.py        Settings resolved from environment (offline defaults)
  security.py      Secret redaction used on every API response
  domain.py        Shared enums + timezone helpers
  services.py      Builds a Runtime (store + embedder + retriever + agent)
  llm/provider.py  Optional LLM provider (deterministic default, OpenAI optional)

  memory/
    models.py      FailureMemory, RetrievalQuery/Result, MemoryFeedback
    embedding.py   HashingEmbedder (offline) / TfIdf fallback / optional OpenAI
    store.py       SQLite persistence, dedup/merge, feedback, stats
    ranking.py     Explainable score: similarity+confidence+recency+feedback
    retriever.py   Selection gates + contradiction detection

  agent/
    environment.py In-memory SimulatedEnvironment (the only "world" tools see)
    tools.py       Sandboxed tools (build, deploy, call_api, config, deps, ...)
    planner.py     Task -> plan, and memory prevention -> concrete plan steps
    executor.py    Runs a plan, records traces, classifies outcomes
    models.py      Plan, StepTrace, ExecutionRecord, TaskRun
    agent.py       Orchestrates attempts, retrieval, learning, feedback

  analysis/
    root_cause.py       Evidence-based cause candidates (confirmed vs hypothesis)
    lesson_extractor.py Failure -> lesson + machine-actionable prevention
    failure_analyzer.py Combines the two
    models.py           FailureAnalysis, CauseCandidate

  evaluation/
    scenarios.py   13 deterministic simulated scenarios
    metrics.py     Per-run metrics + aggregate + retrieval relevance
    benchmark.py   Baseline vs memory harness, JSON + Markdown reports

  api/
    schemas.py     Request models
    serializers.py Response builders (redaction + derived fields)
    routes.py      FastAPI app factory + endpoints
  app.py           Re-exports the app (alternative launch entry point)

  tests/           Unit, integration, API, persistence, retrieval, evaluation

frontend/          Next.js 16 (App Router) dashboard, client components
docs/              architecture.md, evaluation.md
```

## Reference design mapping

The team circulated a four-module prototype sketch (a `FailureAnalysisResult`
model, an OpenAI-backed `analyze_failure`, an in-memory `MemoryStore` with numpy
cosine search, and an `agent_loop.py` that injects lessons before acting). Every
capability in that sketch is implemented below — in the offline-first,
persistent, auditable form this project requires. This section maps each
reference module to its shipped counterpart and records why the implementation
diverges.

| Reference sketch | Intent | Shipped implementation | Deliberate difference |
| --- | --- | --- | --- |
| `memory/models.py`: `FailureMemory` + `FailureAnalysisResult` | A structured record of "what failed, why, and what to do instead" | [`memory/models.py`](../backend/memory/models.py) · `FailureMemory`, [`analysis/models.py`](../backend/analysis/models.py) · `FailureAnalysis` | The failed tool call (`tool`, `args`, `error_code`, `error_message`) lives on [`agent/models.py`](../backend/agent/models.py) · `ExecutionRecord`/`ToolResult`, not on the memory. The memory adds `failure_category`, `cause_status` (confirmed vs hypothesis), `evidence`, machine-actionable `prevention_actions`, lifecycle `status`, and usage counts. |
| `analysis/failure_analyzer.py`: `analyze_failure(...)` via `OpenAI().beta.chat.completions.parse` | Root-cause analysis → lesson + prevention | [`analysis/failure_analyzer.py`](../backend/analysis/failure_analyzer.py) · `FailureAnalyzer.analyze(ExecutionRecord)` | No module-level `OpenAI()` client. Root cause comes from [`analysis/root_cause.py`](../backend/analysis/root_cause.py) evidence and the lesson from [`analysis/lesson_extractor.py`](../backend/analysis/lesson_extractor.py). A real LLM is optional and may only *refine wording* through the `LLMProvider` interface — it can never promote a hypothesis to a confirmed cause. |
| `memory/store.py`: in-memory `MemoryStore` with numpy cosine over `text-embedding-3-small` | Store memories and retrieve similar past failures | [`memory/store.py`](../backend/memory/store.py) · `MemoryStore` + [`memory/retriever.py`](../backend/memory/retriever.py) + [`memory/ranking.py`](../backend/memory/ranking.py) + [`memory/embedding.py`](../backend/memory/embedding.py) | Persistent, thread-safe `sqlite3` store instead of an in-memory list. `merge_or_store` dedups/merges equivalent memories; `record_use`/`add_feedback`/`set_status` drive trust. Similarity uses pure-stdlib cosine (no numpy): deterministic `hashing` by default, `tfidf` lexical fallback, and an optional `OpenAIEmbeddingProvider`. Retrieval is explainable and gated by two independent floors. |
| `agent_loop.py`: ReAct loop with `build_preventive_context` and post-failure `analyze_failure` + `add_memory` | Act with past lessons, then learn from new failures | [`agent/agent.py`](../backend/agent/agent.py) · `FailureMemoryAgent.run_task`, [`agent/planner.py`](../backend/agent/planner.py), [`agent/executor.py`](../backend/agent/executor.py), wired by [`services.py`](../backend/services.py) · `build_runtime` | A deterministic plan engine rather than free-form tool-calling. Retrieved memories are **applied** as concrete plan steps (`apply_preventions`), not merely prepended as prompt text, and every applied step records its source memory id — so prevention is machine-actionable and auditable. Baseline and memory modes are explicit so improvement is measurable. |

### Enabling the optional real-LLM path

The reference sketch's OpenAI behaviour is available, but opt-in and
replaceable:

- `LLM_PROVIDER=openai` + `LLM_API_KEY` activates an OpenAI-compatible provider
  that may refine the *wording* of a diagnosis.
- `EMBEDDING_PROVIDER=openai` + `LLM_API_KEY` activates neural embeddings for
  retrieval.

Both degrade gracefully to the deterministic path when no key is configured or
when a call fails, and nothing imports `openai` or `numpy` at module load time.
The optional providers use the already-declared `requests` dependency; neither
`openai` nor `numpy` is a dependency of this project.

## Lifecycle

```text
Task
  -> plan            planner.plan(task, env)
  -> retrieve        retriever.retrieve(query)          [memory mode only]
  -> recommend       rank + gate memories (score & similarity floors)
  -> apply           planner.apply_preventions(plan, recs)
  -> execute         executor runs steps against SimulatedEnvironment
  -> classify        success | task_failure | tool_failure | timeout | invalid_output
  -> analyse         failure_analyzer -> root cause (confirmed/hypothesis) + lesson
  -> store           store.merge_or_store(memory)      (dedup + merge)
  -> retry           with retrieved memories applied
  -> feedback        record_use(...) updates trust for the next retrieval
```

`FailureMemoryAgent.run_task(task, env, mode, max_attempts)` drives this. With
`mode="baseline"` there is no retrieval and no learning, which is exactly how the
evaluation measures improvement. `mode="naive"` retrieves and applies **every**
candidate memory with no validation (no status, confidence, similarity, or
contradiction gating); it exists only as a research arm to show what the guard
rails contribute, and is never a recommended operating mode.

### Memory lifecycle

Separately from the per-task flow above, stored memories have their own
deterministic lifecycle policy (`backend/memory/lifecycle.py`). A memory is
labelled **fresh**, **stale** (untouched for `LIFECYCLE_STALE_AFTER_DAYS`),
**obsolete** (repeatedly applied but failing, or already `incorrect`), or
**expired** (past the retire horizon or archived). Transitions are monotonic —
`active → outdated → incorrect → archived` — so the policy never un-archives a
memory. `plan_transitions` is a **dry run** used by `/api/memories/lifecycle`;
only `apply_lifecycle` (POST `/api/memories/lifecycle/apply`) writes, and it
re-checks each transition inside the store.

## Domain model

Failure memories distinguish several things a plain error log conflates:

| Concept | Field / enum |
| --- | --- |
| How an attempt ended | `OutcomeType`: `success`, `task_failure`, `tool_failure`, `timeout`, `invalid_output` |
| Failure class | `FailureCategory` (missing config/dependency, invalid response, timeout, …) |
| Cause confidence | `CauseStatus`: `confirmed` (evidence proves it) vs `hypothesis` |
| Memory lifecycle | `MemoryStatus`: `active`, `outdated`, `incorrect`, `archived` |
| Human verdict | `FeedbackVerdict`: `useful`, `unhelpful`, `outdated`, `incorrect` |

A **tool failure** means a tool raised an error; a **task failure** means the
tools ran but the goal was not met (e.g. a deploy reported success but did not
change state). The two are classified differently and lead to different lessons.

## Memory trust

Stored confidence is only a prior. `FailureMemory.effective_confidence` is the
mean of a Beta posterior:

```text
alpha = 2 * confidence + success_count + helpful_count
beta  = 2 * (1 - confidence) + failure_count + unhelpful_count
posterior = alpha / (alpha + beta)
effective_confidence = clamp(posterior * status_penalty(status))
```

`status_penalty` is `active=1.0`, `outdated=0.5`, `incorrect=0.05`,
`archived=0.0`. A memory that repeatedly causes failures therefore loses trust
even if it was first stored with high confidence, and `incorrect`/`archived`
memories can never reach the apply threshold.

## Retrieval

`MemoryRetriever` scores candidates with:

```text
score = w_similarity * similarity
      + w_confidence * effective_confidence
      + w_recency    * recency
      + w_feedback   * feedback
score *= status_penalty(status)
```

Default weights: similarity `0.62`, confidence `0.20`, recency `0.10`,
feedback `0.08`. Recency is exponential decay (30-day half-life); feedback is a
Laplace-smoothed helpfulness ratio.

A candidate is **selected** only when it clears **two** independent gates:

1. `score >= retrieval_min_score` (default `0.28`), and
2. `similarity >= retrieval_min_similarity` (default `0.08`).

The second gate is the guardrail: a high-confidence but textually unrelated
memory can no longer be surfaced on the strength of confidence and recency
alone. Selection does **not** mean application: even a selected memory is only
applied when its `effective_confidence >= min_confidence_to_apply`
(default `0.55`). This is why the evaluation reports **selection** and
**application** relevance separately.

### Similarity modes

The default `HashingEmbedder` is a deterministic feature-hashing vector
similarity computed entirely offline. It is a **lexical** signal and is reported
as `hashing_embedding` throughout — it is *not* a trained semantic model. A
pure lexical `tfidf` fallback and an optional OpenAI neural embedder (only when
a key is configured) exist behind the same interface.

`RETRIEVAL_METHOD` selects the text-similarity function explicitly:
`tfidf`, `bm25` (hand-rolled Okapi BM25, max-normalised to `[0, 1]`), `embedding`,
or `hybrid` (0.5 · embedding + 0.5 · BM25). The default, `auto`, keeps the
historical behaviour — the configured embedder when available, otherwise TF-IDF —
so existing results are unchanged. Each result reports the mode it actually used
(`tfidf_fallback`, `bm25_lexical`, `hashing_embedding`, `hybrid_lexical_embedding`,
or `neural_embedding`), and a lexical method is never labelled semantic.

## Prevention vocabulary

For a retrieved memory to change the plan it must carry **machine-actionable**
prevention actions, parsed by the planner:

| Action | Plan effect |
| --- | --- |
| `validate_config:<name>` | insert a config-validation step |
| `load_config:<name>` | load a value from the simulated secret store |
| `install_dependency:<pkg>` | insert check + install steps (optional) |
| `call_api:<...>:<service>` | enable retry with backoff on the API step |
| `configure_timeout:<tool>:<sec>` | raise the tool timeout |
| `verify_outcome:<target>` | append a post-condition verification step |

Anything else is advisory text only. The applied actions and the source memory
id are recorded on each plan step, so every plan change is auditable.

## Persistence

`MemoryStore` is a thread-safe stdlib `sqlite3` store. On read, every row is
re-validated through the `FailureMemory` Pydantic model; malformed or incomplete
rows are skipped and counted (`malformed_row_count`) instead of crashing.

New observations are deduplicated by a canonical key
(`task_type|action|failure_category|root_cause`, normalised + SHA-1). An
equivalent memory is **merged**: `occurrence_count` increments, evidence/tags
are unioned, the highest confidence is kept, and a memory that had been marked
`outdated`/`incorrect` is refreshed from the new evidence.

## Failure analysis

`root_cause.py` collects cause candidates from tool error codes, environment
state, and the plan step that failed. A candidate is `confirmed` only when the
evidence actually proves it (for example, the environment is *missing* a key the
tool requires); otherwise it is an explicit `hypothesis`. `lesson_extractor.py`
maps the analysed category to a lesson plus the prevention actions above.

## Evaluation

`evaluation/scenarios.py` defines 13 deterministic simulated scenarios in three
groups — **fixable** (5: a learned prevention unlocks recovery), **detection**
(4: the failure must be classified correctly even when unfixable, including a
memory that is applied but does not unlock recovery), and **restraint** (4: a
misleading/irrelevant/low-confidence/incorrect memory must *not* be applied).

`Benchmark.run()` executes every scenario in **three arms** on an **isolated
in-memory store**: `baseline` (no retrieval, no learning), `naive` (retrieve and
apply every candidate, no validation), and `memory` (retrieve + validate + apply
+ learn + feedback), under identical task/environment/attempt budgets. It reports
success rate, repeated failures, prevented failures, and harmful memory
applications per arm, plus retrieval relevance (precision/recall for both
selection and application).

Two additional studies are produced from the same run:

- **Retrieval method comparison** — similarity-only precision/recall/F1 of
  `tfidf`, `bm25`, `embedding`, and `hybrid` on the labelled seed-memory probes,
  with no ranker weights applied, so it isolates the text-similarity method.
- **Memory lifecycle** — deterministic fresh/stale/obsolete/expired counts for
  the run's memories, shown at run time and **projected** to the retire horizon.
  Projections are labelled as projections, never observed data.

See [`evaluation.md`](./evaluation.md) for the current measured results and the
explicit limitations.

### External dataset validation (roadmap)

The runnable demo uses the deterministic synthetic DevOps pack above because the
whole suite must execute offline, on CPU, with no extra dependencies, and produce
identical numbers on every machine. The broader research landscape is documented
here for validation beyond the hackathon, together with the failure categories
each dataset exercises:

| Dataset | Best for | Maps to our categories |
| --- | --- | --- |
| [ToolBench](https://github.com/OpenBMB/ToolBench) | API failures and tool-use correction (16k+ real APIs; rate limits, malformed payloads, 404s) | `invalid_api_response`, `tool_timeout`, `resource_exhausted` |
| [SWE-bench Lite](https://github.com/princeton-nlp/SWE-bench) | Code / DevOps: missing packages, failed tests, syntax errors | `missing_dependency`, `incorrect_assumption`, `tool_failure` |
| [ALFWorld](https://github.com/alfworld/alfworld) / [WebArena](https://webarena.dev) | Sequential decision-making under strict environment constraints | `incorrect_assumption`, `permission_denied` |
| Synthetic DevOps pack (this repo) | Offline, deterministic, reproducible demo of every category | all six categories |

None of the bulk datasets run offline/deterministically or on CPU here, so they
are a roadmap item rather than part of the default benchmark. The adapter would
be a single `evaluation/scenarios.py`-style loader that emits the same `Scenario`
shape (task + environment spec + expected outcomes), leaving `Benchmark.run()`
and every metric unchanged.

## HTTP API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | store availability + memory counts |
| GET | `/api/config` | non-secret runtime configuration |
| GET | `/api/scenarios` | list simulated scenarios |
| POST | `/api/scenarios/{id}/run` | baseline+memory run on an isolated store |
| POST | `/api/tasks/run` | run one task (baseline, naive, or memory) |
| POST | `/api/tasks/compare` | run one task in both modes with cloned envs |
| POST | `/api/retrieval/preview` | explain retrieval without executing |
| GET | `/api/memories` | list memories (filter by status/task type) |
| GET | `/api/memories/stats` | aggregate counters + lifecycle summary |
| GET | `/api/memories/contradictions` | conflicting prevention advice |
| GET | `/api/memories/lifecycle` | dry-run lifecycle labels + planned transitions |
| POST | `/api/memories/lifecycle/apply` | apply monotonic lifecycle transitions |
| GET | `/api/memories/{id}` | one memory + feedback history |
| POST | `/api/memories/{id}/feedback` | attach useful/unhelpful/outdated/incorrect |
| PATCH | `/api/memories/{id}/status` | change lifecycle status |
| DELETE | `/api/memories/{id}` | delete a memory |
| POST | `/api/evaluation/run` | run the benchmark, write the JSON report |
| GET | `/api/evaluation/report` | fetch the last report |

The app degrades gracefully: if the database cannot be opened, `/api/health`
reports `degraded` and data endpoints return `503` rather than crashing.

## Security

- Tools never touch the host, network, or filesystem — only the in-memory
  `SimulatedEnvironment`.
- Every string in every API response passes through a `SecretRedactor` that
  removes API keys, bearer tokens, and labelled secrets.
- Only `NEXT_PUBLIC_*` environment variables reach the browser bundle; the
  backend never returns configured secrets.

## Configuration

See [`.env.example`](../.env.example) for the full list. Defaults are safe and
offline; the app runs with no `.env` at all.

## Testing

`backend/tests/` covers the memory store, retrieval gates, analysis, the agent
lifecycle, the evaluation harness, redaction, and the HTTP API. Run:

```bash
pytest -q --cov=backend
ruff check . && ruff format --check .
```

The frontend is checked with `npm run lint` and `npm run build`.
