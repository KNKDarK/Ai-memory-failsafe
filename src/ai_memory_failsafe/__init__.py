"""AI Memory Failsafe — Python SDK client.

Provides ``FailsafeClient`` for external agent integration with the
failure-memory backend over HTTP.
"""

from __future__ import annotations

from src.ai_memory_failsafe.client import FailsafeClient, FailsafeError

__all__ = ["FailsafeClient", "FailsafeError"]
