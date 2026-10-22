"""Replaceable LLM provider interface.

The application never *requires* an LLM. The default provider is deterministic
and offline; a real OpenAI-compatible provider is only constructed when a key is
configured. Analysis and planning always work without any provider, and any
provider failure degrades gracefully to the rule-based path.
"""

from __future__ import annotations

import json
import os
import time
from typing import Protocol, runtime_checkable

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

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
        # Observability for the LLM benchmark (see OllamaLLMProvider).
        self.usage: dict[str, int] | None = None
        self.last_latency_ms: int | None = None

    def complete(self, prompt: str, system: str | None = None) -> str:
        import requests

        with self._concurrency.slot():
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            started = time.perf_counter()
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
        self.last_latency_ms = int((time.perf_counter() - started) * 1000)
        usage = payload.get("usage") if isinstance(payload, dict) else None
        if isinstance(usage, dict):
            self.usage = {
                "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                "completion_tokens": int(usage.get("completion_tokens") or 0),
            }
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
        disable_thinking: bool = False,
    ) -> None:
        if not model:
            raise ValueError("model is required")
        self._model = model
        self._base_url = base_url.rstrip("/").removesuffix("/v1")
        self._timeout = timeout
        self._num_threads = num_threads if num_threads > 0 else (os.cpu_count() or 1)
        self._disable_thinking = disable_thinking
        self.name = f"ollama:{model}"
        self._concurrency = AdaptiveConcurrency()
        # Observability for the LLM benchmark: token usage and latency of the
        # most recent successful call (None until the first completion).
        self.usage: dict[str, int] | None = None
        self.last_latency_ms: int | None = None

    def complete(self, prompt: str, system: str | None = None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        started = time.perf_counter()
        with self._concurrency.slot():
            response = requests.post(
                f"{self._base_url}/api/chat",
                json={
                    "model": self._model,
                    "messages": messages,
                    "stream": False,
                    # Ollama >=0.3 accepts "think": false for reasoning models.
                    **({"think": False} if self._disable_thinking else {}),
                    "options": {
                        "temperature": 0,
                        "num_thread": self._num_threads,
                    },
                },
                timeout=self._timeout,
            )
        response.raise_for_status()
        payload = response.json()
        self.last_latency_ms = int((time.perf_counter() - started) * 1000)
        prompt_tokens = payload.get("prompt_eval_count")
        completion_tokens = payload.get("eval_count")
        if prompt_tokens is not None or completion_tokens is not None:
            self.usage = {
                "prompt_tokens": int(prompt_tokens or 0),
                "completion_tokens": int(completion_tokens or 0),
            }
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


class LlamaCppLLMProvider:
    """Local llama.cpp HTTP server provider (OpenAI-compatible endpoint).

    Targets a ``llama-server`` instance running on localhost or another
    accessible host. Uses the standard ``/v1/chat/completions`` path so it
    works with any OpenAI-compatible local server, not just llama.cpp.

    Generation parameters are conservative for 4B models on limited VRAM:
    low temperature, modest max_tokens, and an optional seed for reproducibility.
    """

    is_real = True

    def __init__(
        self,
        model: str,
        base_url: str = "http://127.0.0.1:8080",
        api_key: str | None = None,
        timeout: float = 120.0,
        max_tokens: int = 512,
        temperature: float = 0.0,
        seed: int | None = None,
        num_threads: int = 0,
        context_length: int | None = None,
        disable_thinking: bool = False,
    ) -> None:
        if not model:
            raise ValueError("model is required")
        self._model = model
        # Tolerate OpenAI-style base URLs ("…/v1") the same way the Ollama
        # provider does; the request path appends "/v1/chat/completions".
        self._base_url = base_url.rstrip("/").removesuffix("/v1")
        self._api_key = api_key or None
        self._timeout = timeout
        self._max_tokens = max(1, max_tokens)
        self._temperature = temperature
        self._seed = seed
        self._num_threads = num_threads if num_threads > 0 else (os.cpu_count() or 1)
        self._context_length = context_length
        self._disable_thinking = disable_thinking
        self.name = f"llama.cpp:{model}"
        self._concurrency = AdaptiveConcurrency()
        # Observability for the LLM benchmark (see OllamaLLMProvider).
        self.usage: dict[str, int] | None = None
        self.last_latency_ms: int | None = None

    def _post(self, payload: dict) -> dict:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            # llama-server started with --api-key requires this on every call.
            headers["Authorization"] = f"Bearer {self._api_key}"
        with self._concurrency.slot():
            response = requests.post(
                f"{self._base_url}/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=self._timeout,
            )
        response.raise_for_status()
        return response.json()

    def complete(self, prompt: str, system: str | None = None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload: dict = {
            "model": self._model,
            "messages": messages,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }
        if self._seed is not None:
            payload["seed"] = self._seed
        if self._disable_thinking:
            # Reasoning models otherwise spend their whole token budget on
            # hidden reasoning before emitting any answer tokens.
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        started = time.perf_counter()
        try:
            data = self._post(payload)
        except requests.ConnectionError as exc:
            raise LLMUnavailable(f"cannot connect to llama.cpp server at {self._base_url}") from exc
        except requests.Timeout as exc:
            raise LLMUnavailable("llama.cpp server timed out") from exc
        except requests.HTTPError as exc:
            raise LLMUnavailable(
                f"llama.cpp server returned HTTP {exc.response.status_code if exc.response else '?'}"
            ) from exc
        self.last_latency_ms = int((time.perf_counter() - started) * 1000)
        usage = data.get("usage") if isinstance(data, dict) else None
        if isinstance(usage, dict):
            self.usage = {
                "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                "completion_tokens": int(usage.get("completion_tokens") or 0),
            }
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMUnavailable("unexpected llama.cpp response shape") from exc

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

    def describe(self) -> dict:
        """Best-effort model metadata from the server (/props). Never raises."""
        try:
            import requests as _requests

            headers = {}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            response = _requests.get(f"{self._base_url}/props", timeout=5, headers=headers)
            response.raise_for_status()
            props = response.json()
        except Exception:  # noqa: BLE001 - metadata is optional
            return {"provider": self.name}
        if not isinstance(props, dict):  # pragma: no cover - defensive
            return {"provider": self.name}
        model = props.get("model") or {}
        info = {
            "provider": self.name,
            # llama.cpp changed the /props shape; support both layouts.
            "quantization": model.get("quantization") or props.get("model_ftype"),
            "model_path": model.get("path") or props.get("model_path") or props.get("model_alias"),
            "total_slots": props.get("total_slots"),
        }
        build = props.get("build_info") or props.get("build_commit")
        if build:
            info["server_build"] = build
        return {key: value for key, value in info.items() if value is not None}


def make_llm_provider(settings) -> LLMProvider:
    """Build the configured provider, defaulting to deterministic/offline."""
    if settings.llm_provider == "llama.cpp":
        try:
            return LlamaCppLLMProvider(
                model=settings.llm_model,
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key or None,
                timeout=settings.llm_timeout_seconds,
                max_tokens=getattr(settings, "llm_max_tokens", 512),
                temperature=getattr(settings, "llm_temperature", 0.0),
                seed=getattr(settings, "llm_seed", None),
                num_threads=settings.llm_num_threads,
                context_length=getattr(settings, "llm_context_length", None),
                disable_thinking=settings.llm_disable_thinking,
            )
        except ValueError:
            return DeterministicLLMProvider()
    if settings.llm_provider == "ollama":
        try:
            return OllamaLLMProvider(
                model=settings.llm_model,
                base_url=settings.llm_base_url,
                timeout=settings.llm_timeout_seconds,
                num_threads=settings.llm_num_threads,
                disable_thinking=settings.llm_disable_thinking,
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
