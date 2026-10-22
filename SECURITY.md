# Security Policy

## Supported Versions

Only the latest version of the **AI Agent Failure Memory** codebase is actively supported with security updates.

| Version | Supported          |
| ------- | ------------------ |
| 1.0  | :white_check_mark: |
| < 1.0   | :x:                |

---

## Security Considerations for AI & Memory Systems

Because this system processes logs, agent actions, trace data, and vector embeddings, please ensure the following safety measures are observed:

* **Secret Redaction**: Never commit `.env` files or API keys. Ensure that runtime logs and error outputs are sanitized to prevent API keys, bearer tokens, or database credentials from being stored in failure memories or vector databases.
* **API Access Control**: For local single-user deployments, set `API_AUTH_TOKEN` so task-execution and memory-mutation endpoints require a bearer token (see the README "API security" section). This is a local convenience mechanism, not a substitute for a real authenticating proxy if the app is ever network-exposed.
* **Request Limits**: HTTP request bodies are size-capped (`MAX_REQUEST_BODY_BYTES`, HTTP 413) and nested environment/config structures are depth- and size-bounded (HTTP 422).
* **Tool Permissions**: Grant AI agents the minimum necessary permissions required for task execution (Principle of Least Privilege).
* **Input Validation**: Sanitize and validate external inputs and tool execution parameters prior to execution.
* **Data Privacy in Embeddings**: Ensure sensitive personally identifiable information (PII) or confidential environment details are excluded from semantic embeddings and public vector stores.
* **Model Server Exposure**: Local inference servers (`llama-server`, Ollama) are unauthenticated by default. Keep them on `127.0.0.1`; if a model server must be reachable by containers or other hosts, start it with `--api-key` (the backend sends `LLM_API_KEY` as a Bearer token) and restrict the port with the host firewall. Never expose a model server to untrusted networks.
* **Untrusted Memory and Model Output**: Retrieved memory text and LLM output are unvalidated data, never instructions. Model-proposed tools are checked against an allowlist (disallowed tools become `noop`), and the deterministic trust gates — not the model — decide which memories are applied; a model cannot suggest a reviewer-rejected memory into execution.
* **Benchmark Honesty**: LLM benchmark reports count model-call errors and abort loudly when the endpoint is dead, instead of silently presenting rule-based fallback results as model results. Do not weaken this: masked provider failures are indistinguishable from real model behaviour.

---

## Reporting a Vulnerability

If you discover a security vulnerability or sensitive credential exposure within this repository, please report it responsibly:

1. **Do not** create a public GitHub issue.
2. Email your security findings to **`knkssmk@gmail.com`** (or contact the primary maintainer directly).
3. Include detailed steps to reproduce the vulnerability, including any relevant code snippets or payloads.

### What to Expect

* **Response Time**: We aim to acknowledge receipt of security reports within **48 hours**.
* **Status Updates**: You will receive progress updates at least once every **5 business days** until the issue is resolved.
* **Public Disclosure**: Once a fix is released, an advisory or patch update will be published acknowledging responsible disclosures.
