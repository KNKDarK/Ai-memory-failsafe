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

## 📚 Semantic Memory Retrieval

When a new task arrives, the system searches for previous failures that are semantically similar.

```text
Current Task
     ↓
Embedding
     ↓
Memory Search
     ↓
Relevant Failures
     ↓
Rank Memories
     ↓
Inject Lessons
```

This allows the agent to benefit from previous experiences even when the new task is worded differently.

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

The system tracks whether failure memories actually improve future performance.

Example:

```text
Total Tasks              100
Failures                  31
Lessons Learned           24
Repeated Failures           7
Prevented Failures         17

Failure Rate
Before Memory             31%
After Memory              14%

Improvement               54.8%
```

> Metrics shown above are illustrative. Actual benchmark results should be generated from the project's evaluation runs.

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

# 🔬 Failure Memory Model

A failure is represented as structured experience.

Example:

```json
{
  "task": "deploy_python_application",
  "action": "start_container",
  "failure": "application_crashed",
  "root_cause": "missing_database_url",
  "evidence": [
    "DATABASE_URL was not present",
    "application startup failed",
    "container exited with code 1"
  ],
  "lesson": "Validate required environment variables before deployment",
  "prevention": "Run configuration validation before starting the container",
  "confidence": 0.91,
  "successful_prevention_count": 3
}
```

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

The project should be evaluated using controlled repeated tasks.

### Baseline

Run the agent without failure memory.

Record:

```text
Success rate
Failure rate
Repeated failure rate
Average attempts
```

### Memory-enabled agent

Run the same or equivalent tasks with failure memory enabled.

Record:

```text
Success rate
Failure rate
Repeated failure rate
Average attempts
Prevented failures
```

### Comparison

```text
                    Baseline     Memory
------------------------------------------
Success Rate           XX%          XX%
Failure Rate          XX%          XX%
Repeated Failures     XX%          XX%
Avg Attempts          X.X          X.X
Prevented Failures     --           XX
```

The goal is to demonstrate **measurable improvement**, not simply claim that the agent learns.

---

# 🛠️ Technology Stack

> The exact stack can be adjusted during implementation. Keep this section synchronized with the final codebase.

### Backend

* Python
* FastAPI
* Pydantic
* Uvicorn

### AI / Agent Layer

* LLM provider
* Agent orchestration
* Structured tool execution
* Failure analysis
* Lesson extraction

### Memory

* Embeddings
* Vector database
* Semantic retrieval
* Structured failure records

### Frontend

* React / Next.js
* TypeScript
* Tailwind CSS

### Testing

* Pytest
* Unit tests
* Integration tests
* Evaluation benchmarks

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
│   ├── api/
│   │   ├── routes.py
│   │   └── schemas.py
│   │
│   ├── agent/
│   │   ├── agent.py
│   │   ├── executor.py
│   │   └── tools.py
│   │
│   ├── memory/
│   │   ├── models.py
│   │   ├── store.py
│   │   ├── retriever.py
│   │   └── ranking.py
│   │
│   ├── analysis/
│   │   ├── failure_analyzer.py
│   │   ├── root_cause.py
│   │   └── lesson_extractor.py
│   │
│   └── evaluation/
│       ├── benchmark.py
│       └── metrics.py
│
├── frontend/
│   ├── components/
│   ├── pages/
│   └── lib/
│
├── tests/
│   ├── test_agent.py
│   ├── test_memory.py
│   ├── test_retrieval.py
│   └── test_evaluation.py
│
├── docs/
│   ├── architecture.md
│   └── evaluation.md
│
├── .env.example
├── requirements.txt
├── README.md
└── LICENSE
```

---

# ⚙️ Installation

## Prerequisites

Make sure you have:

* Python 3.11+
* Git
* Node.js 20+ (if using the web frontend)
* An LLM/API provider configured for the project

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

## 4. Configure environment variables

Copy the example configuration:

```bash
cp .env.example .env
```

Configure the required AI provider credentials.

Example:

```env
LLM_API_KEY=your_api_key_here
LLM_MODEL=your_model_here
MEMORY_DATABASE=./data/memory.db
```

**Never commit `.env` or API keys to GitHub.**

---

## 5. Start the backend

```bash
uvicorn backend.api.routes:app --reload
```

The API should become available at:

```text
http://localhost:8000
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

Run the automated tests:

```bash
pytest -q
```

Run with verbose output:

```bash
pytest -v
```

Run the evaluation benchmark:

```bash
python -m backend.evaluation.benchmark
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
Semantic retrieval
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

# 🧪 Future Improvements

Potential future versions could include:

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

### Memory Confidence

Automatically increase or decrease confidence based on repeated outcomes.

### Memory Expiration

Old or repeatedly invalid lessons can be downgraded or archived.

### Contradiction Detection

Detect when two memories disagree.

```text
Memory A:
Use strategy X

Memory B:
Strategy X caused failure

       ↓

Conflict detected
       ↓
Re-evaluate memories
```

### Automatic Experimentation

The system could test multiple strategies and remember which one performs best.

---

# 🗺️ Roadmap

## Phase 1 — MVP

* [x] Project concept
* [ ] Agent execution
* [ ] Failure detection
* [ ] Failure analysis
* [ ] Structured memory
* [ ] Memory retrieval
* [ ] Basic UI

## Phase 2 — Learning

* [ ] Lesson effectiveness
* [ ] Memory confidence
* [ ] Failure recurrence tracking
* [ ] Before/after evaluation

## Phase 3 — Advanced Memory

* [ ] Memory contradiction detection
* [ ] Memory decay
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

* Your Name — AI / Backend
* Team Member — Frontend
* Team Member — Research / Evaluation
* Team Member — Product / Design

---

# ⭐ If You Like This Project

Give the repository a ⭐ and follow the project as it evolves.

> **AI agents should not just remember what they did. They should remember what went wrong — and do better next time.**
