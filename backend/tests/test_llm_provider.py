"""Tests for optional local LLM provider configuration."""

from __future__ import annotations

import pytest
import requests

from backend.config import Settings
from backend.llm.provider import LlamaCppLLMProvider, LLMUnavailable, OllamaLLMProvider


class _Response:
    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return {"message": {"content": "ok"}}


def test_ollama_uses_cpu_threads_without_forcing_gpu_backend(monkeypatch) -> None:
    captured: dict = {}

    def fake_post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return _Response()

    monkeypatch.setattr(requests, "post", fake_post)
    provider = OllamaLLMProvider("qwen:4b", num_threads=7)

    assert provider.complete("hello") == "ok"
    assert captured["url"] == "http://127.0.0.1:11434/api/chat"
    assert captured["json"]["options"] == {"temperature": 0, "num_thread": 7}
    assert "num_gpu" not in captured["json"]["options"]


def test_ollama_is_reported_as_enabled() -> None:
    settings = Settings(llm_provider="ollama", llm_model="qwen:4b")

    assert settings.llm_enabled is True


class _FakeResponse:
    def __init__(self, json_data: dict, status_code: int = 200):
        self._json = json_data
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            from requests import HTTPError

            raise HTTPError(f"{self.status_code}", response=self)

    def json(self) -> dict:
        return self._json


def test_llamacpp_provider_uses_openai_compatible_endpoint(monkeypatch) -> None:
    captured: dict = {}

    def fake_post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return _FakeResponse(
            {"choices": [{"message": {"content": "plan: check_env, validate_config"}}]}
        )

    monkeypatch.setattr(requests, "post", fake_post)
    provider = LlamaCppLLMProvider(
        model="qwen2.5-4b-instruct-q4_k_m.gguf",
        base_url="http://127.0.0.1:8080",
        max_tokens=256,
        temperature=0.0,
        seed=42,
    )

    result = provider.complete("Deploy the service")
    assert result == "plan: check_env, validate_config"
    assert captured["url"] == "http://127.0.0.1:8080/v1/chat/completions"
    payload = captured["json"]
    assert payload["model"] == "qwen2.5-4b-instruct-q4_k_m.gguf"
    assert payload["temperature"] == 0.0
    assert payload["max_tokens"] == 256
    assert payload["seed"] == 42
    assert payload["messages"][0]["role"] == "user"


def test_llamacpp_provider_json_mode(monkeypatch) -> None:
    def fake_post(url, **kwargs):
        return _FakeResponse(
            {"choices": [{"message": {"content": '{"action": "check_env", "reason": "baseline"}'}}]}
        )

    monkeypatch.setattr(requests, "post", fake_post)
    provider = LlamaCppLLMProvider(model="test", base_url="http://localhost:8080")

    result = provider.complete_json("Plan a task")
    assert result == {"action": "check_env", "reason": "baseline"}


def test_llamacpp_provider_connection_error(monkeypatch) -> None:
    from requests import ConnectionError as RequestsConnectionError

    def fake_post(url, **kwargs):
        raise RequestsConnectionError("refused")

    monkeypatch.setattr(requests, "post", fake_post)
    provider = LlamaCppLLMProvider(model="test", base_url="http://localhost:8080")

    with pytest.raises(LLMUnavailable) as exc_info:
        provider.complete("hello")
    assert "cannot connect" in str(exc_info.value)


def test_llamacpp_provider_timeout(monkeypatch) -> None:
    from requests import Timeout as RequestsTimeout

    def fake_post(url, **kwargs):
        raise RequestsTimeout()

    monkeypatch.setattr(requests, "post", fake_post)
    provider = LlamaCppLLMProvider(model="test", base_url="http://localhost:8080")

    with pytest.raises(LLMUnavailable) as exc_info:
        provider.complete("hello")
    assert "timed out" in str(exc_info.value)


def test_llamacpp_provider_malformed_json(monkeypatch) -> None:
    def fake_post(url, **kwargs):
        return _FakeResponse({"choices": [{"message": {"content": "not json"}}]})

    monkeypatch.setattr(requests, "post", fake_post)
    provider = LlamaCppLLMProvider(model="test", base_url="http://localhost:8080")

    with pytest.raises(LLMUnavailable) as exc_info:
        provider.complete_json("hello")
    assert "valid JSON" in str(exc_info.value)


def test_llamacpp_is_reported_as_enabled() -> None:
    settings = Settings(llm_provider="llama.cpp", llm_model="qwen2.5-4b-instruct-q4_k_m.gguf")
    assert settings.llm_enabled is True


def test_llamacpp_empty_model_falls_back_to_deterministic() -> None:
    from backend.llm.provider import make_llm_provider

    settings = Settings(llm_provider="llama.cpp", llm_model="")
    provider = make_llm_provider(settings)
    assert provider.is_real is False


def test_llamacpp_provider_captures_usage_and_latency(monkeypatch) -> None:
    def fake_post(url, **kwargs):
        return _FakeResponse(
            {
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 321, "completion_tokens": 54},
            }
        )

    monkeypatch.setattr(requests, "post", fake_post)
    provider = LlamaCppLLMProvider(model="test", base_url="http://localhost:8080")

    assert provider.complete("hello") == "ok"
    assert provider.usage == {"prompt_tokens": 321, "completion_tokens": 54}
    assert isinstance(provider.last_latency_ms, int)


def test_ollama_provider_captures_usage_and_latency(monkeypatch) -> None:
    class _OllamaResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {
                "message": {"content": "ok"},
                "prompt_eval_count": 40,
                "eval_count": 9,
            }

    monkeypatch.setattr(requests, "post", lambda url, **kwargs: _OllamaResponse())
    provider = OllamaLLMProvider("qwen:4b")

    assert provider.complete("hello") == "ok"
    assert provider.usage == {"prompt_tokens": 40, "completion_tokens": 9}
    assert isinstance(provider.last_latency_ms, int)


def test_llamacpp_describe_is_best_effort(monkeypatch) -> None:
    def fake_get(url, **kwargs):
        return _FakeResponse(
            {"model": {"path": "/models/qwen.gguf", "quantization": "Q4_K_M"}, "total_slots": 1}
        )

    monkeypatch.setattr(requests, "get", fake_get)
    provider = LlamaCppLLMProvider(model="test", base_url="http://localhost:8080")
    info = provider.describe()
    assert info["quantization"] == "Q4_K_M"

    def failing_get(url, **kwargs):
        raise OSError("no server")

    monkeypatch.setattr(requests, "get", failing_get)
    assert provider.describe() == {"provider": provider.name}


def test_llamacpp_describe_supports_new_props_shape(monkeypatch) -> None:
    """Recent llama-server builds replaced props["model"] with top-level keys."""

    def fake_get(url, **kwargs):
        return _FakeResponse(
            {
                "model_ftype": "Q4_K - Medium",
                "model_path": "/models/qwen.gguf",
                "model_alias": "/models/qwen.gguf",
                "total_slots": 4,
                "build_info": "b11429-d812350493",
            }
        )

    monkeypatch.setattr(requests, "get", fake_get)
    provider = LlamaCppLLMProvider(model="test", base_url="http://localhost:8080")
    info = provider.describe()
    assert info["quantization"] == "Q4_K - Medium"
    assert info["server_build"] == "b11429-d812350493"
    assert info["total_slots"] == 4


def test_llamacpp_disable_thinking_sends_template_kwargs(monkeypatch) -> None:
    captured: dict = {}

    def fake_post(url, **kwargs):
        captured.update(kwargs)
        return _FakeResponse({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(requests, "post", fake_post)
    LlamaCppLLMProvider(model="t", disable_thinking=True).complete("hi")
    assert captured["json"]["chat_template_kwargs"] == {"enable_thinking": False}

    LlamaCppLLMProvider(model="t", disable_thinking=False).complete("hi")
    assert "chat_template_kwargs" not in captured["json"]


def test_ollama_disable_thinking_sends_think_false(monkeypatch) -> None:
    captured: dict = {}

    def fake_post(url, **kwargs):
        captured.update(kwargs)
        return type(
            "_R",
            (),
            {
                "raise_for_status": lambda self: None,
                "json": lambda self: {"message": {"content": "ok"}},
            },
        )()

    monkeypatch.setattr(requests, "post", fake_post)
    OllamaLLMProvider("m", disable_thinking=True).complete("hi")
    assert captured["json"]["think"] is False

    OllamaLLMProvider("m", disable_thinking=False).complete("hi")
    assert "think" not in captured["json"]


def test_disable_thinking_env_parsing(monkeypatch) -> None:
    from backend.config import Settings

    monkeypatch.setenv("LLM_DISABLE_THINKING", "true")
    assert Settings.from_env().llm_disable_thinking is True
    monkeypatch.delenv("LLM_DISABLE_THINKING")
    assert Settings.from_env().llm_disable_thinking is False


def test_llamacpp_sends_bearer_token_when_api_key_configured(monkeypatch) -> None:
    captured: dict = {}

    def fake_post(url, **kwargs):
        captured.update(kwargs)
        return _FakeResponse({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(requests, "post", fake_post)
    LlamaCppLLMProvider(model="t", api_key="s3cret").complete("hi")
    assert captured["headers"]["Authorization"] == "Bearer s3cret"

    LlamaCppLLMProvider(model="t").complete("hi")
    assert "Authorization" not in captured["headers"]


def test_llamacpp_tolerates_openai_style_base_url(monkeypatch) -> None:
    captured: dict = {}

    def fake_post(url, **kwargs):
        captured.update(url=url)
        return _FakeResponse({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(requests, "post", fake_post)
    LlamaCppLLMProvider(model="t", base_url="http://localhost:8080/v1").complete("hi")
    assert captured["url"] == "http://localhost:8080/v1/chat/completions"
