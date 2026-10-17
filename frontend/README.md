# AI Agent Failure Memory — Dashboard UI

The control-plane UI for **AI Agent Failure Memory**. Built with Next.js 16
(Turbopack) + React 19 and TypeScript, styled with **hand-written dark CSS**
(no Tailwind, no chart library) so the whole demo stays offline-first and
dependency-light.

Every number on screen is read from the live FastAPI backend — nothing in the
UI is hardcoded.

## Quick Start

### 1. Install dependencies

```bash
npm install
```

### 2. Configure the environment

```bash
cp .env.example .env.local
```

`.env.local` is git-ignored. It controls where the browser looks for the API:

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

The committed default (`lib/api.ts`) is `http://localhost:8000`, matching the
main README. If port 8000 is already taken on your machine, run the backend on
8001 instead and point this value at it (this is what `.env.local` does in the
demo environment).

### 3. Start the backend (from the repository root)

```bash
uvicorn backend.app:app --port 8001 --reload
# or: uvicorn backend.api.routes:app --reload
```

### 4. Start the development server

```bash
npm run dev
```

Open <http://localhost:3000> in your browser.

If the backend is unreachable, the UI degrades to an error banner instead of
showing stale or invented numbers.

## Key features (the real tabs)

| Tab | What it visualizes |
| --- | --- |
| **Overview** | Health + configuration header, four live metric cards, evaluation-report highlights, memory-growth and failure-category charts. |
| **Agent Sandbox** | Chat-style task execution. Pick a preset or type a prompt, choose a mode (**memory** / **naive** / **baseline**), then inspect the step-by-step execution trace, the plan changes, and a consolidated table showing *why each memory was — or wasn't — used* (similarity, rank, gates, reason). |
| **Scenarios** | The 13 deterministic simulated scenarios; run one in isolation and compare baseline vs. memory. |
| **Retrieval** | Read-only retrieval preview: similarity score, matched terms, rank, and the score + similarity gate decisions behind every selection. |
| **Memory Bank** | Table of stored lessons: failure, root cause, prevention actions, trust, uses / success rate, and lifecycle state (fresh / stale / obsolete / expired). Rows expand inline for feedback and lifecycle preview/apply. |
| **Evaluation** | The generated benchmark report rendered as SVG charts: the three evaluation arms, the retrieval-method comparison, and the memory-lifecycle breakdown. |

## Endpoints consumed

- `GET /api/health`, `GET /api/config`
- `GET /api/evaluation/report` (regenerate with `python -m backend.evaluation.benchmark`)
- `GET /api/memories`, `GET /api/memories/stats`, `GET /api/memories/lifecycle`
- `POST /api/tasks/run`, `POST /api/tasks/compare`, `POST /api/scenarios/{id}/run`
- `POST /api/retrieval/preview`

## Verifying the UI build

```bash
npx tsc --noEmit   # type-check
npm run build      # production build
npm run lint       # eslint
```

## Recorded demo

A step-by-step walkthrough for a screen recording lives in
[`../docs/demo.md`](../docs/demo.md).
