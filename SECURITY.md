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
* **Tool Permissions**: Grant AI agents the minimum necessary permissions required for task execution (Principle of Least Privilege).
* **Input Validation**: Sanitize and validate external inputs and tool execution parameters prior to execution.
* **Data Privacy in Embeddings**: Ensure sensitive personally identifiable information (PII) or confidential environment details are excluded from semantic embeddings and public vector stores.

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
