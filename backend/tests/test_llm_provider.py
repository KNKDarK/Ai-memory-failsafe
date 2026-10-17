"""Tests for optional local LLM provider configuration."""

from __future__ import annotations

import requests

from backend.config import Settings
from backend.llm.provider import OllamaLLMProvider


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
