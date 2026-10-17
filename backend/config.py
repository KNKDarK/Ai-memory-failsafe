"""Runtime configuration for the AI Agent Failure Memory backend.

Configuration is resolved from environment variables, but the application is
designed to run completely offline with deterministic defaults. No network
access, API key, or GPU is required for the core lifecycle, the test suite, or
the evaluation benchmark.

Real LLM / embedding providers are *optional*: they are only activated when the
relevant environment variables are present. Secrets are never logged.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass
class Settings:
    """Resolved settings.

    Attributes are deliberately simple so the dataclass can be constructed in
    tests without touching the environment.
    """

    # --- Storage ---------------------------------------------------------
    memory_database: str = "data/memory.db"
    evaluation_report_path: str = "data/evaluation_report.json"

    # --- LLM provider ----------------------------------------------------
    # "deterministic" (default, offline), "ollama" (local), or "openai".
    llm_provider: str = "deterministic"
    llm_model: str = "deterministic-rule-based"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str | None = None
    llm_timeout_seconds: float = 30.0
    llm_num_threads: int = 0
    llm_max_tokens: int = 512
    llm_temperature: float = 0.0
    llm_seed: int | None = None
    llm_context_length: int | None = None
    # Reasoning models (e.g. qwen3.5 "thinking" variants) spend most of their
    # token budget on hidden reasoning before answering. On small local models
    # that is usually counterproductive; disable it explicitly when set.
    llm_disable_thinking: bool = False
    # Where the LLM evaluation benchmark writes its reports. Reports use
    # unique run ids and are never overwritten.
    llm_benchmark_output_dir: str = "data/llm_benchmarks"

    # --- Embeddings ------------------------------------------------------
    # "hashing" (default, offline deterministic vector similarity) or
    # "openai" (optional neural embeddings) or "tfidf" (pure lexical fallback).
    embedding_provider: str = "hashing"
    embedding_dim: int = 256
    embedding_model: str = "text-embedding-3-small"

    # --- Retrieval / ranking --------------------------------------------
    retrieval_limit: int = 5
    # Similarity method: "auto" (historical default: embedding if available, else
    # TF-IDF) or an explicit method for the retrieval comparison study:
    # "tfidf" | "bm25" | "embedding" | "hybrid".
    retrieval_method: str = "auto"
    retrieval_min_score: float = 0.28
    # A memory must also clear this *text similarity* floor to be selected, so a
    # high-confidence but textually unrelated memory can never be surfaced by
    # the confidence/recency terms alone.
    retrieval_min_similarity: float = 0.08
    weight_similarity: float = 0.62
    weight_confidence: float = 0.20
    weight_recency: float = 0.10
    weight_feedback: float = 0.08
    recency_half_life_days: float = 30.0
    # A memory must reach this "effective confidence" before its prevention is
    # allowed to change the agent's plan.
    min_confidence_to_apply: float = 0.55

    # --- Memory lifecycle -------------------------------------------------
    # Deterministic freshness/staleness/obsolescence/retirement thresholds.
    lifecycle_stale_after_days: float = 30.0
    lifecycle_retire_after_days: float = 90.0
    lifecycle_obsolete_failure_ratio: float = 0.5
    lifecycle_min_uses_for_obsolete: int = 3

    # --- Agent execution -------------------------------------------------
    default_max_attempts: int = 2
    max_retries_per_step: int = 1

    # --- Security / privacy ---------------------------------------------
    redact_secrets: bool = True
    max_memory_text_length: int = 4000
    cors_origins: list[str] = field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )

    # --- API access control ----------------------------------------------
    # Shared token protecting task-execution and memory-mutation endpoints.
    # Read from API_AUTH_TOKEN; empty/None disables enforcement (open local
    # development mode). Never logged, echoed, or serialised anywhere.
    api_auth_token: str | None = None

    # --- Request resource limits ------------------------------------------
    # Maximum accepted HTTP request-body size in bytes (413 above it). Guards
    # every content type, including chunked bodies with no Content-Length.
    max_request_body_bytes: int = 262144  # 256 KiB
    # Limits for user-supplied nested environment/configuration structures.
    max_env_depth: int = 6
    max_env_items: int = 64
    max_env_value_length: int = 4096

    # --- Misc ------------------------------------------------------------
    environment: str = "development"

    @classmethod
    def from_env(cls) -> Settings:
        cors_raw = os.getenv("CORS_ORIGINS")
        cors = (
            [o.strip() for o in cors_raw.split(",") if o.strip()]
            if cors_raw
            else ["http://localhost:3000", "http://127.0.0.1:3000"]
        )
        return cls(
            memory_database=os.getenv("MEMORY_DATABASE", "data/memory.db"),
            evaluation_report_path=os.getenv(
                "EVALUATION_REPORT_PATH", "data/evaluation_report.json"
            ),
            llm_provider=os.getenv("LLM_PROVIDER", "deterministic").strip().lower(),
            llm_model=os.getenv("LLM_MODEL", "deterministic-rule-based"),
            llm_base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
            llm_api_key=os.getenv("LLM_API_KEY") or None,
            llm_timeout_seconds=_env_float("LLM_TIMEOUT_SECONDS", 30.0),
            llm_num_threads=_env_int("LLM_NUM_THREADS", 0),
            llm_max_tokens=_env_int("LLM_MAX_TOKENS", 512),
            llm_temperature=_env_float("LLM_TEMPERATURE", 0.0),
            llm_seed=_env_int("LLM_SEED", -1) if os.getenv("LLM_SEED") else None,
            llm_context_length=_env_int("LLM_CONTEXT_LENGTH", 0) or None,
            llm_disable_thinking=_env_bool("LLM_DISABLE_THINKING", False),
            llm_benchmark_output_dir=os.getenv("LLM_BENCHMARK_OUTPUT_DIR", "data/llm_benchmarks"),
            embedding_provider=os.getenv("EMBEDDING_PROVIDER", "hashing").strip().lower(),
            embedding_dim=_env_int("EMBEDDING_DIM", 256),
            embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
            retrieval_limit=_env_int("RETRIEVAL_LIMIT", 5),
            retrieval_method=(os.getenv("RETRIEVAL_METHOD", "auto").strip().lower()),
            retrieval_min_score=_env_float("RETRIEVAL_MIN_SCORE", 0.28),
            retrieval_min_similarity=_env_float("RETRIEVAL_MIN_SIMILARITY", 0.08),
            weight_similarity=_env_float("WEIGHT_SIMILARITY", 0.62),
            weight_confidence=_env_float("WEIGHT_CONFIDENCE", 0.20),
            weight_recency=_env_float("WEIGHT_RECENCY", 0.10),
            weight_feedback=_env_float("WEIGHT_FEEDBACK", 0.08),
            recency_half_life_days=_env_float("RECENCY_HALF_LIFE_DAYS", 30.0),
            min_confidence_to_apply=_env_float("MIN_CONFIDENCE_TO_APPLY", 0.55),
            lifecycle_stale_after_days=_env_float("LIFECYCLE_STALE_AFTER_DAYS", 30.0),
            lifecycle_retire_after_days=_env_float("LIFECYCLE_RETIRE_AFTER_DAYS", 90.0),
            lifecycle_obsolete_failure_ratio=_env_float("LIFECYCLE_OBSOLETE_FAILURE_RATIO", 0.5),
            lifecycle_min_uses_for_obsolete=_env_int("LIFECYCLE_MIN_USES_FOR_OBSOLETE", 3),
            default_max_attempts=_env_int("DEFAULT_MAX_ATTEMPTS", 2),
            max_retries_per_step=_env_int("MAX_RETRIES_PER_STEP", 1),
            redact_secrets=_env_bool("REDACT_SECRETS", True),
            max_memory_text_length=_env_int("MAX_MEMORY_TEXT_LENGTH", 4000),
            cors_origins=cors,
            api_auth_token=os.getenv("API_AUTH_TOKEN") or None,
            max_request_body_bytes=max(1024, _env_int("MAX_REQUEST_BODY_BYTES", 262144)),
            max_env_depth=max(1, _env_int("MAX_ENV_DEPTH", 6)),
            max_env_items=max(1, _env_int("MAX_ENV_ITEMS", 64)),
            max_env_value_length=max(16, _env_int("MAX_ENV_VALUE_LENGTH", 4096)),
            environment=os.getenv("APP_ENV", "development"),
        )

    @property
    def llm_enabled(self) -> bool:
        """True when a *real* LLM provider is configured and usable."""
        return (
            (self.llm_provider == "llama.cpp" and bool(self.llm_model))
            or (self.llm_provider == "ollama" and bool(self.llm_model))
            or (self.llm_provider == "openai" and bool(self.llm_api_key))
        )

    @property
    def uses_memory_database(self) -> bool:
        return self.memory_database not in {"", ":memory:"}

    def ensure_data_dir(self) -> None:
        if not self.uses_memory_database:
            return
        path = Path(self.memory_database)
        if path.parent and str(path.parent) not in {"", "."}:
            path.parent.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    """Load settings from the environment (safe to call repeatedly)."""
    return Settings.from_env()
