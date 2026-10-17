"""Replaceable LLM provider interface.

The application never *requires* an LLM. The default provider is deterministic
and offline; a real OpenAI-compatible provider is only constructed when a key is
configured. Analysis and planning always work without any provider, and any
provider failure degrades gracefully to the rule-based path.
"""

from __future__ import annotations

import json
import os
from typing import Protocol, runtime_checkable

from backend.resources import AdaptiveConcurrency


class LLMUnavailable(RuntimeError):
    """Raised when a provider cannot produce a completion."""


@runtime_checkable
class LLMProvider(Protocol):
    name: str
    is_real: bool

    def complete(self, prompt: str, system: str | None = None) -> str:  # pragma: no cover
        ...


class DeterministicLLMProvider:
    """Offline provider used by default.

    It does not invent analysis. Callers that need a *real* model check
    ``is_real`` before using it, so the deterministic path stays rule-based and
    honest.
    """

    name = "deterministic"
    is_real = False

    def complete(self, prompt: str, system: str | None = None) -> str:
        raise LLMUnavailable("deterministic provider does not generate free-form text")

    def complete_json(self, prompt: str, system: str | None = None) -> dict:
        raise LLMUnavailable("deterministic provider does not generate structured output")


class OpenAICompatibleLLMProvider:
    """Thin OpenAI-compatible chat-completions client (optional)."""

    is_real = True

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 30.0,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self.name = f"openai:{model}"
        self._concurrency = AdaptiveConcurrency()

    def complete(self, prompt: str, system: str | None = None) -> str:
        import requests

        with self._concurrency.slot():
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            response = requests.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "messages": messages,
                    "temperature": 0,
                },
                timeout=self._timeout,
            )
        response.raise_for_status()
        payload = response.json()
        try:
            return payload["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMUnavailable("unexpected response shape") from exc

    def complete_json(self, prompt: str, system: str | None = None) -> dict:
        """Request JSON and parse it defensively."""
        instruction = (
            "Respond with a single JSON object and nothing else. Do not wrap it in markdown fences."
        )
        raw = self.complete(
            prompt,
            system=(system + "\n" + instruction) if system else instruction,
        )
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            cleaned = cleaned.split("\n", 1)[-1] if "\n" in cleaned else cleaned
        try:
            parsed = json.loads(cleaned)
        except (json.JSONDecodeError, TypeError) as exc:
            raise LLMUnavailable("model did not return valid JSON") from exc
        if not isinstance(parsed, dict):
            raise LLMUnavailable("model JSON was not an object")
        return parsed


class OllamaLLMProvider:
    """Ollama native chat provider with Vulkan-friendly automatic offload.

    ``num_gpu`` is intentionally omitted: Ollama then uses an available GPU
    and falls back to CPU when no compatible Vulkan device is present.
    ``num_thread`` is always supplied so the CPU path can use all host cores.
    """

    is_real = True

    def __init__(
        self,
        model: str,
        base_url: str = "http://127.0.0.1:11434",
        timeout: float = 120.0,
        num_threads: int = 0,
    ) -> None:
        if not model:
            raise ValueError("model is required")
        self._model = model
        self._base_url = base_url.rstrip("/").removesuffix("/v1")
        self._timeout = timeout
        self._num_threads = num_threads if num_threads > 0 else (os.cpu_count() or 1)
        self.name = f"ollama:{model}"
        self._concurrency = AdaptiveConcurrency()

    def complete(self, prompt: str, system: str | None = None) -> str:
        import requests

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        with self._concurrency.slot():
            response = requests.post(
                f"{self._base_url}/api/chat",
                json={
                    "model": self._model,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "temperature": 0,
                        "num_thread": self._num_threads,
                    },
                },
                timeout=self._timeout,
            )
        response.raise_for_status()
        payload = response.json()
        try:
            return payload["message"]["content"] or ""
        except (KeyError, TypeError) as exc:
            raise LLMUnavailable("unexpected Ollama response shape") from exc

    def complete_json(self, prompt: str, system: str | None = None) -> dict:
        instruction = (
            "Respond with a single JSON object and nothing else. Do not wrap it in markdown fences."
        )
        raw = self.complete(
            prompt,
            system=(system + "\n" + instruction) if system else instruction,
        )
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            cleaned = cleaned.split("\n", 1)[-1] if "\n" in cleaned else cleaned
        try:
            parsed = json.loads(cleaned)
        except (json.JSONDecodeError, TypeError) as exc:
            raise LLMUnavailable("model did not return valid JSON") from exc
        if not isinstance(parsed, dict):
            raise LLMUnavailable("model JSON was not an object")
        return parsed


def make_llm_provider(settings) -> LLMProvider:
    """Build the configured provider, defaulting to deterministic/offline."""
    if settings.llm_provider == "ollama":
        try:
            return OllamaLLMProvider(
                model=settings.llm_model,
                base_url=settings.llm_base_url,
                timeout=settings.llm_timeout_seconds,
                num_threads=settings.llm_num_threads,
            )
        except ValueError:
            return DeterministicLLMProvider()
    if settings.llm_provider == "openai" and settings.llm_api_key:
        try:
            return OpenAICompatibleLLMProvider(
                api_key=settings.llm_api_key,
                model=settings.llm_model,
                base_url=settings.llm_base_url,
                timeout=settings.llm_timeout_seconds,
            )
        except ValueError:
            return DeterministicLLMProvider()
    return DeterministicLLMProvider()
