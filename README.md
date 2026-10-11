# 🧠 AI Agent Failure Memory

> **AI agents that don't just remember what happened — they remember why they failed and use that experience to improve future decisions.**

[![Hackathon](https://img.shields.io/badge/Hackathon-Build%20With%20Nova%202026-blue)](#)
[![Status](https://img.shields.io/badge/Status-Prototype-orange)](#)
[![AI](https://img.shields.io/badge/AI-Agentic%20Memory-purple)](#)
[![License](https://img.shields.io/badge/License-MIT-green)](#)

---

## 🚀 Overview

**AI Agent Failure Memory** is an intelligent memory system designed to help AI agents learn from their previous failures.

Most AI agents can remember conversations, instructions, or retrieved documents. However, remembering an event is not the same as learning from it.

This project focuses on a different type of memory:

> **Failure → Cause → Lesson → Future Prevention**

When an agent fails at a task, the system analyzes the failure, identifies the likely root cause, extracts an actionable lesson, and stores that experience as structured memory.

When a similar task appears later, the system retrieves relevant past failures and provides the learned lessons to the agent before it acts.

### Core Loop

```text
┌──────────────┐
│     Task     │
└──────┬───────┘
       ↓
┌──────────────┐
│ Agent Action │
└──────┬───────┘
       ↓
┌──────────────┐
│    Result    │
└──────┬───────┘
       ↓
   ┌───┴────┐
   │Success?│
   └───┬────┘
       │
   ┌───┴─────────────┐
   │                 │
  YES                NO
   │                 │
   │          ┌──────▼──────┐
   │          │    Failure  │
   │          │   Analysis  │
   │          └──────┬──────┘
   │                 ↓
   │          ┌──────────────┐
   │          │ Root Cause   │
   │          │  Detection   │
   │          └──────┬───────┘
   │                 ↓
   │          ┌──────────────┐
   │          │ Lesson       │
   │          │ Extraction   │
   │          └──────┬───────┘
   │                 ↓
   │          ┌──────────────┐
   │          │ Failure      │
   │          │ Memory       │
   │          └──────┬───────┘
   │                 │
   └────────┬────────┘
            ↓
     ┌───────────────┐
     │  Future Task  │
     └───────┬───────┘
             ↓
     ┌───────────────┐
     │ Retrieve Past │
     │   Experience  │
     └───────┬───────┘
             ↓
     ┌───────────────┐
     │ Better Agent  │
     │    Decision   │
     └───────────────┘
```

---

# 🎯 Problem

AI agents frequently operate through trial and error.

A typical agent might do this:

```text
Task
 ↓
Attempt
 ↓
Failure
 ↓
Retry
 ↓
Failure
 ↓
Retry
 ↓
Eventually succeeds
```

The problem is that the useful information contained in those failures can easily disappear after the task ends.

The agent may encounter the same situation days later and repeat the same mistake.

### Example

An agent deploys an application.

```text
❌ Deployment failed

Cause:
DATABASE_URL was missing.

Lesson:
Validate required environment variables
before starting the deployment.
```

Later, a similar deployment occurs.

Without failure memory:

```text
Agent → repeats mistake → failure
```

With failure memory:

```text
Agent
 ↓
Search previous failures
 ↓
Find deployment lesson
 ↓
Validate DATABASE_URL
 ↓
Avoid previous mistake
 ↓
✅ Success
```

---

# 💡 Solution

AI Agent Failure Memory introduces a dedicated memory layer for **agent mistakes and lessons**.

Instead of simply storing:

```text
"What happened?"
```

the system stores:

```text
"What happened?"
"Why did it happen?"
"What evidence supports the cause?"
"What should the agent do differently?"
"Did this lesson actually help later?"
```

Each failure becomes a reusable experience.

---

# ✨ Key Features

## 🧠 Failure Memory

Stores structured information about previous agent failures.

Each memory can contain:

* Task
* Action taken
* Failure
* Root cause
* Evidence
* Lesson
* Prevention strategy
* Confidence
* Timestamp
* Outcome

---

## 🔍 Failure Analysis

The system analyzes failed attempts to determine:

```text
Failure
   ↓
Symptoms
   ↓
Evidence
   ↓
Possible causes
   ↓
Most likely cause
```

---

## 📚 Memory Retrieval

When a new task arrives, the system searches previous failures for relevant ones.

```text
Current Task
     ↓
Vectorise (lexical by default)
     ↓
Memory Search
     ↓
Rank Memories (similarity + confidence + recency + feedback)
     ↓
Gate (score AND similarity floors)
     ↓
Apply as concrete plan steps
```

The default embedder is a deterministic **feature-hashing** vector similarity
computed entirely offline. It is a *lexical* signal, reported as
`hashing_embedding` everywhere — it is **not** a trained semantic model. A pure
lexical `tfidf` fallback and an optional neural embedder exist behind the same
interface and are only used when explicitly configured. See
[`docs/architecture.md`](docs/architecture.md#similarity-modes) for details.

`RETRIEVAL_METHOD` can also select the similarity function explicitly — `tfidf`,
`bm25` (hand-rolled Okapi BM25), `embedding`, or `hybrid` — and the benchmark
compares all four head-to-head on the same labelled probes. The default, `auto`,
preserves the historical routing, and a lexical method is always reported as
lexical, never as semantic.

---

## 🎯 Preventive Reasoning

Retrieved memories are not simply displayed to the agent.

The system converts them into actionable guidance.

Example:

```text
Past failure:
API rate limit

Lesson:
Use exponential backoff.

Current task:
Call the same API.

Preventive recommendation:
Apply retry backoff before executing.
```

---

## 📈 Learning Metrics

The system tracks whether failure memories actually improve future performance
by running the same tasks in three arms under identical conditions: a
**baseline** (no retrieval, no learning), a **naive** arm (retrieve and apply
everything, no validation — a control for the guard rails), and the
**validated memory** arm (retrieve, gate, apply, learn, feedback).

Reproduce it with:

```bash
python -m backend.evaluation.benchmark      # or: failure-memory-benchmark
```

The benchmark writes a machine-readable JSON report and a human-readable report,
and the dashboard reads the real report from the backend — no metrics are
hardcoded in the UI. The current measured results (success-rate improvement,
prevented vs repeated failures, harmful applications, and selection/application
retrieval relevance) are in [`docs/evaluation.md`](docs/evaluation.md).

---

## 🔄 Memory Feedback

A memory can be evaluated after being used.

```text
Memory retrieved
      ↓
Agent changes behavior
      ↓
Task executed
      ↓
Outcome observed
      ↓
Memory effectiveness updated
```

This helps distinguish useful lessons from unreliable ones.

---

# 🏗️ Architecture

```text
                         ┌───────────────┐
                         │     User      │
                         └───────┬───────┘
                                 │
                                 ▼
                       ┌──────────────────┐
                       │    AI Agent      │
                       └────────┬─────────┘
                                │
                       ┌────────▼─────────┐
                       │ Task Understanding│
                       └────────┬─────────┘
                                │
                                ▼
                       ┌──────────────────┐
                       │ Failure Memory   │
                       │    Retriever     │
                       └────────┬─────────┘
                                │
                       ┌────────▼─────────┐
                       │ Relevant Past    │
                       │    Failures      │
                       └────────┬─────────┘
                                │
                                ▼
                       ┌──────────────────┐
                       │ Context Builder  │
                       └────────┬─────────┘
                                │
                                ▼
                       ┌──────────────────┐
                       │    AI Agent      │
                       │ Decision/Action  │
                       └────────┬─────────┘
                                │
                                ▼
                       ┌──────────────────┐
                       │ Tool / Task      │
                       │   Execution      │
                       └────────┬─────────┘
                                │
                       ┌────────▼─────────┐
                       │     Result       │
                       └────────┬─────────┘
                                │
                         ┌──────┴──────┐
                         │             │
                      Success        Failure
                         │             │
                         │             ▼
                         │      ┌──────────────┐
                         │      │ Failure      │
                         │      │ Analyzer     │
                         │      └──────┬───────┘
                         │             │
                         │             ▼
                         │      ┌──────────────┐
                         │      │ Lesson       │
                         │      │ Extractor    │
                         │      └──────┬───────┘
                         │             │
                         │             ▼
                         │      ┌──────────────┐
                         │      │ Memory Store │
                         │      └──────┬───────┘
                         │             │
                         └──────┬──────┘
                                ▼
                         ┌──────────────┐
                         │ Evaluation & │
                         │   Metrics    │
                         └──────────────┘
```

---

## 🗺️ Where each module lives

The diagram above is the concept; the shipped code is described in
[`docs/architecture.md`](docs/architecture.md). That document also contains a
**reference design mapping** that lines this project up against the simpler
four-module prototype sketch and explains exactly which real module covers each
piece:

| Concept in the diagram | Module |
| --- | --- |
| Task understanding / planning | `backend/agent/planner.py` |
| Failure Memory Retriever | `backend/memory/retriever.py` + `ranking.py` + `embedding.py` |
| Context builder / decision | `backend/agent/agent.py` (`planner.apply_preventions`) |
| Tool / task execution | `backend/agent/executor.py` + `tools.py` |
| Failure Analyzer | `backend/analysis/failure_analyzer.py` |
| Lesson extractor | `backend/analysis/lesson_extractor.py` |
| Memory Store | `backend/memory/store.py` (SQLite) |
| Evaluation & Metrics | `backend/evaluation/benchmark.py` + `metrics.py` |

---

# 🔬 Failure Memory Model

A failure is represented as structured experience.

Example:

```json
{
  "id": "1f0c…",
  "task": "deploy python application",
  "task_type": "deploy",
  "action": "deploy",
  "failure": "deployment did not change target state",
  "failure_category": "missing_configuration",
  "root_cause": "required configuration 'DATABASE_URL' is missing",
  "cause_status": "confirmed",
  "evidence": [
    "environment is missing required key 'DATABASE_URL'",
    "deploy reported failure for target 'app'"
  ],
  "lesson": "Validate required environment variables before deployment",
  "prevention": "Validate configuration before starting the deployment",
  "prevention_actions": [
    "validate_config:DATABASE_URL",
    "verify_outcome:deployment"
  ],
  "tags": ["missing_configuration", "deploy"],
  "confidence": 0.91,
  "status": "active",
  "occurrence_count": 3,
  "use_count": 3,
  "success_count": 2,
  "failure_count": 1
}
```

Confidence is only a stored prior. `effective_confidence` (derived from the
success/failure counts and lifecycle status) is what actually gates retrieval and
application, and `prevention_actions` are the machine-actionable steps the
planner can insert into a plan.

This makes failure memories:

* Searchable
* Explainable
* Evaluatable
* Reusable
* Machine-readable

---

# 🔄 Demo Flow

The primary demonstration follows two runs.

## Run 1 — Agent Fails

```text
User:
Deploy the application.
```

The agent attempts the task.

```text
Agent
 ↓
Build
 ↓
Start
 ↓
❌ Failure
```

The system analyzes the failure.

```text
Root Cause:
Missing DATABASE_URL

Confidence:
91%

Lesson:
Validate required environment variables
before deployment.
```

The lesson is stored.

---

## Run 2 — Agent Learns

The user gives a similar task.

```text
User:
Deploy another version of the application.
```

The system searches memory.

```text
🧠 Relevant experience found

Previous failure:
Missing DATABASE_URL

Recommended prevention:
Validate required environment variables.
```

The agent changes its behavior.

```text
✓ Checks configuration
✓ Finds DATABASE_URL
✓ Starts application
✓ Deployment succeeds
```

### The key demonstration

```text
WITHOUT MEMORY

Task
 ↓
Failure
 ↓
Retry
 ↓
Same mistake


WITH FAILURE MEMORY

Task
 ↓
Retrieve experience
 ↓
Apply lesson
 ↓
Avoid mistake
 ↓
Success
```

---

# 📊 Evaluation

Improvement is measured, not claimed. The benchmark runs every scenario in three
arms under identical task, environment, and attempt budgets:

- **Baseline** — the agent runs with no retrieval and no learning.
- **Naive memory** — retrieve and apply *every* candidate with no validation
  (a research arm that isolates what the guard rails contribute).
- **Validated memory** — the same tasks, with retrieval, gating, learning, and
  feedback.

It records per-arm success rate, repeated failures, prevented failures, and
harmful memory applications, plus retrieval relevance (precision/recall for
**selection** and **application**, reported separately). Two extra studies come
from the same run: a **retrieval-method comparison** (`tfidf`, `bm25`,
`embedding`, `hybrid`) and a **memory-lifecycle** fresh/stale/obsolete/expired
breakdown (at run time and projected to the retire horizon).

```bash
python -m backend.evaluation.benchmark       # writes JSON + Markdown reports
```

- Machine-readable report: `data/evaluation_report.json`
- Human-readable report: [`docs/evaluation.md`](docs/evaluation.md)

Every scenario is explicitly labelled as simulated, and the report contains only
values measured by the run — the dashboard renders that report rather than
hardcoded numbers.

Larger public datasets (ToolBench, SWE-bench Lite, ALFWorld / WebArena) are
documented as an **external-validation roadmap** in
[`docs/architecture.md`](docs/architecture.md#external-dataset-validation-roadmap),
mapped to our failure categories. They are not wired into the default benchmark
because they need network, models, or heavy CPU that the reproducible offline
demo deliberately avoids; the adapter would emit the same `Scenario` shape and
leave every metric unchanged.

---

# 🛠️ Technology Stack

> The stack is deliberately offline-first: no API key, GPU, or network access is
> required to run the agent, the tests, or the benchmark.

### Backend

* Python 3.11+
* FastAPI + Uvicorn
* Pydantic v2
* stdlib `sqlite3` (no external database server)

### AI / Agent Layer

* Deterministic rule-based planner and executor (offline, no GPU)
* Optional, replaceable LLM provider (`deterministic` default, OpenAI-compatible optional)
* Structured tool execution against an in-memory sandbox
* Evidence-based failure analysis and lesson extraction

### Memory

* Structured failure records persisted in SQLite (dedup + merge)
* Two-stage retrieval: vector scoring (`hashing` / `tfidf` / optional neural) then gating
* Explainable ranking (similarity + confidence + recency + feedback)
* Feedback, lifecycle status, contradiction detection, repeated-failure tracking

### Frontend

* Next.js 16 (App Router)
* React + TypeScript
* Hand-written dark CSS (no Tailwind)

### Testing

* Pytest (`backend/tests/`: unit, integration, persistence, retrieval, API, evaluation)
* Ruff (lint + format)
* Frontend: ESLint, `tsc --noEmit`, `next build`
* Deterministic evaluation benchmark

### Development

* Git
* GitHub
* NOVA CLI

---

# 📁 Project Structure

```text
ai-agent-failure-memory/
│
├── backend/
│   ├── app.py                 # re-exports the FastAPI app
│   ├── config.py              # Settings from env (offline defaults)
│   ├── domain.py              # shared enums + time helpers
│   ├── security.py            # secret redaction
│   ├── services.py            # build_runtime(): wires store/retriever/agent
│   │
│   ├── api/
│   │   ├── routes.py          # FastAPI app + endpoints
│   │   ├── schemas.py
│   │   └── serializers.py
│   │
│   ├── agent/
│   │   ├── agent.py           # FailureMemoryAgent: full lifecycle
│   │   ├── planner.py         # task -> plan; prevention -> plan steps
│   │   ├── executor.py        # runs a plan, classifies outcomes
│   │   ├── tools.py           # sandboxed tools
│   │   ├── environment.py     # in-memory SimulatedEnvironment
│   │   └── models.py
│   │
│   ├── memory/
│   │   ├── models.py          # FailureMemory, RetrievalQuery/Result, feedback
│   │   ├── store.py           # SQLite persistence, dedup/merge, feedback
│   │   ├── embedding.py       # hashing / tfidf / optional neural
│   │   ├── ranking.py         # explainable score
│   │   └── retriever.py       # selection gates + contradiction detection
│   │
│   ├── analysis/
│   │   ├── failure_analyzer.py
│   │   ├── root_cause.py
│   │   ├── lesson_extractor.py
│   │   └── models.py
│   │
│   ├── llm/
│   │   └── provider.py        # deterministic default + optional OpenAI
│   │
│   ├── evaluation/
│   │   ├── scenarios.py       # 13 deterministic simulated scenarios
│   │   ├── metrics.py
│   │   └── benchmark.py
│   │
│   └── tests/                 # unit, integration, API, persistence, evaluation
│
├── frontend/                  # Next.js 16 (App Router)
│   ├── app/                   # layout.tsx, page.tsx, globals.css
│   ├── components/            # Dashboard, panels, cards
│   └── lib/                   # api client, types, formatting, presets
│
├── docs/
│   ├── architecture.md
│   └── evaluation.md
│
├── run.py                     # interactive sandbox tool REPL
├── .env.example
├── requirements.txt
├── pyproject.toml
├── README.md
└── LICENSE
```

---

# ⚙️ Installation

## Prerequisites

Make sure you have:

* Python 3.11+
* Git
* Node.js 20+ (only for the web frontend)

No API key, GPU, or network access is required: the project runs fully offline
with deterministic defaults, including its tests and benchmark.

---

## 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/ai-agent-failure-memory.git
cd ai-agent-failure-memory
```

---

## 2. Create a Python environment

### Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Windows

```powershell
python -m venv .venv
.venv\Scripts\activate
```

---

## 3. Install dependencies

```bash
pip install -r requirements.txt
```

---

## 4. Configure environment variables (optional)

The app runs with no `.env` at all. Every value in [`.env.example`](.env.example)
is optional, and the defaults are offline and deterministic. Copy it only if you
want to change something:

```bash
cp .env.example .env
```

Common overrides:

```env
MEMORY_DATABASE=data/memory.db      # SQLite location (":memory:" for ephemeral)
LLM_PROVIDER=deterministic         # or "openai" (then set LLM_API_KEY)
EMBEDDING_PROVIDER=hashing         # or "tfidf" / "openai"
```

**Never commit `.env` or API keys to GitHub.**

---

## 5. Start the backend

```bash
uvicorn backend.api.routes:app --reload      # or: uvicorn backend.app:app --reload
```

The API becomes available at <http://localhost:8000> (interactive docs at
<http://localhost:8000/docs>).

For a quick manual look at the sandbox tools without the HTTP server:

```bash
python run.py
```

---

## 6. Start the frontend

If the project includes a web frontend:

```bash
cd frontend
npm install
npm run dev
```

Then open:

```text
http://localhost:3000
```

---

# 🧪 Testing

Backend tests and linting:

```bash
pytest -q --cov=backend                      # unit, integration, API, persistence, retrieval, evaluation
ruff check . && ruff format --check .
```

Run a single test file with verbose output:

```bash
pytest backend/tests/test_agent.py -v
```

Run the evaluation benchmark (writes `data/evaluation_report.json`):

```bash
python -m backend.evaluation.benchmark       # or: failure-memory-benchmark
```

Frontend checks:

```bash
cd frontend
npm run lint && npx tsc --noEmit && npm run build
```

---

# 📸 Screenshots

> Add screenshots here after the UI is finalized.

### Dashboard

```text
[ Add dashboard screenshot here ]
```

Example filename:

```text
docs/screenshots/dashboard.png
```

---

### Failure Analysis

```text
[ Add failure analysis screenshot here ]
```

Example:

```text
docs/screenshots/failure-analysis.png
```

---

### Memory Explorer

```text
[ Add memory explorer screenshot here ]
```

Example:

```text
docs/screenshots/memory-explorer.png
```

---

### Before vs After

```text
[ Add benchmark screenshot here ]
```

Example:

```text
docs/screenshots/before-after.png
```

---

# 🎥 Demo

A short demo should show the complete learning loop:

```text
1. Give agent a task
        ↓
2. Agent attempts task
        ↓
3. Agent fails
        ↓
4. System analyzes failure
        ↓
5. Lesson is created
        ↓
6. Memory is stored
        ↓
7. Give similar task
        ↓
8. Memory is retrieved
        ↓
9. Agent changes strategy
        ↓
10. Task succeeds
```

### Demo Video

> 🎥 **Coming soon**

Add your final demo video here:

```text
[Demo Video Link]
```

---

# 🤖 Nova CLI Usage

This project was developed using **NOVA CLI** as part of the **Build With Nova 2026** hackathon.

NOVA CLI is designed as an AI developer in the terminal: it can work directly with a repository, implement changes, understand existing code, debug problems, and verify changes using project tests.

## How Nova was used

Nova was used throughout the development lifecycle rather than only for generating initial boilerplate.

### 1. Project Architecture

Used Nova to explore:

```text
Agent architecture
Memory architecture
Failure-analysis pipeline
API structure
Evaluation strategy
```

---

### 2. Implementation

Nova assisted with implementing and modifying:

```text
Agent execution
Failure detection
Memory storage
Memory retrieval and ranking
Lesson extraction
API endpoints
Frontend components
Tests
```

---

### 3. Debugging

When implementation issues occurred:

```text
Error
 ↓
Nova analysis
 ↓
Root cause
 ↓
Code change
 ↓
Test
 ↓
Verification
```

---

### 4. Testing

Nova was used to help:

* Create tests
* Diagnose failing tests
* Improve error handling
* Verify API behavior
* Refactor implementation
* Run the project's test suite

---

### 5. Iteration

The development process followed:

```text
Idea
 ↓
Prototype
 ↓
Test
 ↓
Failure
 ↓
Nova-assisted debugging
 ↓
Improvement
 ↓
Retest
```

This mirrors the core philosophy of the project itself:

> **Build → fail → learn → improve.**

---

# 🧩 Why Nova Matters to This Project

The project itself is about **learning from failures**.

Nova was used as part of the development feedback loop:

```text
Developer
    ↓
Build with Nova
    ↓
Run tests
    ↓
Encounter failure
    ↓
Analyze
    ↓
Fix
    ↓
Retest
    ↓
Improve
```

The development process therefore naturally reflects the project's central concept:

> **Failures are not the end of the process. They are information that can be used to improve the next attempt.**

---

# 🔐 Security

The system may process logs, errors, configuration information, or task data.

Recommended security practices:

* Never commit API keys
* Never store secrets inside failure memories
* Redact credentials from logs
* Sanitize tool outputs
* Validate external inputs
* Limit agent tool permissions
* Keep sensitive data out of embeddings where possible

---

# 🧪 Implemented vs Future

Already shipped:

- **Memory confidence** — `effective_confidence` is a Beta posterior over
  success/failure and helpful/unhelpful feedback.
- **Memory expiration / decay** — lifecycle status (`outdated`, `incorrect`,
  `archived`) plus recency decay down-weight stale lessons.
- **Memory lifecycle automation** — a deterministic policy labels every memory
  fresh / stale / obsolete / expired, exposes a **dry-run** plan
  (`GET /api/memories/lifecycle`), and applies monotonic transitions only on an
  explicit `POST /api/memories/lifecycle/apply`. Lifecycle counts are surfaced in
  `/api/memories/stats` and the dashboard.
- **Retrieval-method comparison** — `tfidf`, `bm25`, `embedding`, and `hybrid`
  are compared head-to-head on the same labelled probes (similarity-only, no
  ranker weights) so the study isolates the text-similarity method.
- **Guard-rail control arm** — the benchmark runs a `naive` arm that applies
  every retrieved memory with no validation, isolating what the gates contribute
  (fewer harmful applications, same or better prevention).
- **Contradiction detection** — `GET /api/memories/contradictions` surfaces
  memories that give conflicting prevention advice, and retrieval suppresses
  them.
- **Failure recurrence tracking** — memories are deduplicated/merged and count
  repeated occurrences.

Still future work:

### Cross-Agent Learning

Allow multiple agents to share verified failure lessons.

```text
Agent A
   ↓
Failure
   ↓
Shared Memory
   ↓
Agent B
   ↓
Avoids failure
```

### Automatic Experimentation

The system could test multiple strategies and remember which one performs best.

---

# 🗺️ Roadmap

## Phase 1 — MVP

* [x] Project concept
* [x] Agent execution
* [x] Failure detection
* [x] Failure analysis
* [x] Structured memory
* [x] Memory retrieval
* [x] Basic UI

## Phase 2 — Learning

* [x] Lesson effectiveness
* [x] Memory confidence
* [x] Failure recurrence tracking
* [x] Before/after evaluation

## Phase 3 — Advanced Memory

* [x] Memory contradiction detection
* [x] Memory decay
* [x] Memory lifecycle automation (classify / plan / apply)
* [x] Retrieval-method comparison (tfidf / bm25 / embedding / hybrid)
* [ ] Cross-agent learning
* [ ] Automatic strategy selection

---

# 🏆 Hackathon

Built for:

## **Build With Nova 2026**

**Theme:** Build With Nova
**Duration:** 48 Hours
**Mode:** Online
**Team Size:** 1–4

The hackathon encourages participants to use Nova CLI throughout the development process, from building and debugging to experimentation and shipping.

### Track

**Build for the Future**

---

# 💭 Philosophy

AI agents are becoming increasingly capable of acting autonomously.

But autonomy without learning can lead to repeated mistakes.

AI Agent Failure Memory explores a simple question:

> **What if an AI agent could turn every meaningful failure into experience?**

Instead of:

```text
Failure → Forget
```

we want:

```text
Failure
   ↓
Understand
   ↓
Learn
   ↓
Remember
   ↓
Improve
```

---

# 📜 License

This project is licensed under the MIT License.

See [`LICENSE`](LICENSE) for details.

---

# 👥 Team

**Project:** AI Agent Failure Memory

**Built for:** Build With Nova 2026

**Team Members:**

* Aum namaha  — AI / Backend
* sri harsha — Frontend
* shafi masthan koushik — Research / Evaluation
* vamsi sai krishna— Product / Design

---

# ⭐ If You Like This Project

Give the repository a ⭐ and follow the project as it evolves.

> **AI agents should not just remember what they did. They should remember what went wrong — and do better next time.**
