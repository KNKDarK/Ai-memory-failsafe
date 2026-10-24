"""Lightweight HTTP client for the AI Memory Failsafe backend.

``FailsafeClient`` provides a thin, synchronous wrapper around the v1 SDK REST
endpoints so external agents can query prevention lessons, record failures, and
submit outcome feedback without constructing raw HTTP requests themselves.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger("ai_memory_failsafe.client")


class FailsafeError(Exception):
    """Base exception for all client-side errors."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ConnectionError(FailsafeError):
    """Raised when the backend is unreachable or a timeout occurs."""


class FailsafeClient:
    """HTTP client for external agent integration with the failure-memory API.

    Parameters
    ----------
    base_url : str
        Root URL of the running backend (default ``http://localhost:8000``).
    api_key : str | None
        Optional bearer token sent as ``Authorization: Bearer <key>`` on every
        request.  Required only for endpoints that mutate state when
        ``API_AUTH_TOKEN`` is configured on the server.

    Usage
    -----
    >>> client = FailsafeClient(base_url="http://localhost:8000", api_key=None)
    >>> lessons = client.get_prevention_lessons(
    ...     task_description="Deploy the billing service",
    ...     project_id="payments",
    ...     agent_id="agent-42",
    ... )
    """

    def __init__(self, base_url: str = "http://localhost:8000", api_key: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._client = httpx.Client(
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0),
            follow_redirects=True,
        )

    # ------------------------------------------------------------------ #
    # Public API methods
    # ------------------------------------------------------------------ #

    def get_prevention_lessons(
        self,
        task_description: str,
        project_id: str,
        agent_id: str,
        *,
        min_confidence: float = 0.65,
        top_k: int = 5,
    ) -> dict[str, Any]:
        """Query prevention lessons relevant to the given task description.

        Parameters
        ----------
        task_description : str
            The current task or prompt to find past failures for.
        project_id : str
            Project identifier to scope the search within a single project's memories.
        agent_id : str
            Agent requesting lessons; used for per-agent statistics and cross-agent sharing.
        min_confidence : float
            Minimum confidence threshold (0–1). Defaults to 0.65.
        top_k : int
            Maximum number of lessons to return. Defaults to 5.

        Returns
        -------
        dict
            Parsed JSON response from ``POST /api/v1/sdk/query-lessons``
            containing ``query``, ``lessons_found``, and a list of ``lessons``.

        Raises
        ------
        ConnectionError
            When the backend is unreachable or the request times out.
        FailsafeError
            On HTTP 4xx/5xx responses from the server.
        """
        payload = {
            "task_description": task_description,
            "project_id": project_id,
            "agent_id": agent_id,
            "min_confidence": min_confidence,
            "top_k": top_k,
        }
        resp = self._post("/api/v1/sdk/query-lessons", payload)
        return resp

    def record_failure(
        self,
        task_input: str,
        action_trace: list[dict[str, Any]],
        error_message: str,
        *,
        project_id: str = "default_project",
        agent_id: str = "default",
    ) -> dict[str, Any]:
        """Ingest an execution trace and error for root-cause analysis.

        The backend will run failure analysis, extract a lesson from the
        recorded root cause, and store it as structured memory.

        Parameters
        ----------
        task_input : str
            The original task or prompt that led to this failure.
        action_trace : list[dict[str, Any]]
            Ordered sequence of tool calls and their results leading up to
            the failure (e.g. ``[{"tool": "deploy", "args": {...}}]``).
        error_message : str
            The error or exception message that caused this failure.
        project_id : str
            Project identifier for grouping failures. Defaults to "default_project".
        agent_id : str
            Agent that encountered the failure. Defaults to "default".

        Returns
        -------
        dict
            Parsed JSON response from ``POST /api/v1/sdk/record-failure``
            containing ``lesson_id``, ``root_cause``, ``lesson_extracted``,
            ``confidence_score``, and ``is_verified``.

        Raises
        ------
        ConnectionError
            When the backend is unreachable or the request times out.
        FailsafeError
            On HTTP 4xx/5xx responses from the server.
        """
        payload = {
            "task_input": task_input,
            "action_trace": action_trace,
            "error_message": error_message,
            "project_id": project_id,
            "agent_id": agent_id,
        }
        resp = self._post("/api/v1/sdk/record-failure", payload)
        return resp

    def report_outcome(
        self,
        lesson_id: str,
        task_success: bool,
        *,
        project_id: str | None = None,
        agent_id: str = "default",
    ) -> dict[str, Any]:
        """Submit outcome feedback for a previously retrieved lesson.

        Updates the lesson's confidence score and contributes to the adaptive
        retrieval bandit (UCB1) weights based on whether applying the lesson
        led to success or failure.

        Parameters
        ----------
        lesson_id : str
            Identifier of the lesson being rated.
        task_success : bool
            Whether the task succeeded after applying this lesson.
        project_id : str | None
            Optional project identifier for per-project feedback aggregation.
        agent_id : str
            Agent providing the feedback. Defaults to "default".

        Returns
        -------
        dict
            Parsed JSON response from ``POST /api/v1/sdk/feedback`` containing
            ``lesson_id``, ``verdict``, and ``success``.

        Raises
        ------
        ConnectionError
            When the backend is unreachable or the request times out.
        FailsafeError
            On HTTP 4xx/5xx responses from the server.
        """
        payload = {
            "lesson_id": lesson_id,
            "agent_id": agent_id,
            "task_success": task_success,
            "project_id": project_id,
        }
        resp = self._post("/api/v1/sdk/feedback", payload)
        return resp

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Send a POST request and return the parsed JSON body.

        Handles connection errors, timeouts, HTTP status codes, and JSON
        parsing failures, raising typed exceptions for each category.
        """
        url = f"{self.base_url}{path}"
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            response = self._client.post(url, json=payload, headers=headers)
        except httpx.ConnectTimeout:
            raise ConnectionError(
                f"Connection timed out while reaching {url}",
                status_code=None,
            ) from None
        except (httpx.ConnectError, httpx.NetworkError):
            raise ConnectionError(
                f"Could not connect to {url} — is the backend running?",
                status_code=None,
            ) from None

        # HTTP error responses.
        if response.status_code >= 500:
            detail = self._extract_detail(response)
            raise FailsafeError(
                f"Server error ({response.status_code}): {detail}",
                status_code=response.status_code,
            )
        if response.status_code >= 400:
            detail = self._extract_detail(response)
            raise FailsafeError(
                f"Client error ({response.status_code}): {detail}",
                status_code=response.status_code,
            )

        # Success — parse JSON.
        try:
            return response.json()
        except httpx.InvalidJSONError as exc:
            logger.warning("Failed to parse JSON from %s: %s", url, exc)
            raise FailsafeError(
                f"Backend returned non-JSON response (status {response.status_code})",
                status_code=response.status_code,
            ) from None

    @staticmethod
    def _extract_detail(response: httpx.Response) -> str:
        """Best-effort extraction of an error detail string."""
        try:
            body = response.json()
            return body.get("detail", str(body))
        except Exception:  # noqa: BLE001 — best effort only
            return response.text[:256] if response.text else "(no body)"

    def close(self) -> None:
        """Close the underlying HTTP client connection pool."""
        self._client.close()

    def __enter__(self) -> "FailsafeClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
