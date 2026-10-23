"""Automatic retrieval-strategy selection (adaptive bandit)."""

from __future__ import annotations

import dataclasses

from backend.domain import CauseStatus, FailureCategory
from backend.memory.embedding import make_embedding_provider
from backend.memory.models import RetrievalQuery
from backend.memory.ranking import MemoryRanker
from backend.memory.retriever import MemoryRetriever
from backend.memory.store import MemoryStore
from backend.memory.strategies import StrategySelector
from backend.tests.factories import deploy_env, make_memory


def _retriever(store: MemoryStore, settings) -> MemoryRetriever:
    return MemoryRetriever(
        store,
        settings,
        embedder=make_embedding_provider(settings),
        ranker=MemoryRanker(settings),
    )


def _seed(store: MemoryStore) -> None:
    store.save(
        make_memory(
            id="deploy-mem",
            task="Deploy the application",
            task_type="deploy_service",
            action="deploy",
            failure="deployment failed: missing configuration DATABASE_URL",
            root_cause="required environment variable DATABASE_URL is missing",
            failure_category=FailureCategory.MISSING_CONFIGURATION,
            cause_status=CauseStatus.CONFIRMED,
            prevention_actions=["validate_config:DATABASE_URL"],
        )
    )


def test_selector_explores_every_candidate_before_exploiting(store: MemoryStore) -> None:
    selector = StrategySelector(store)
    chosen = [selector.choose("deploy_service")["strategy"] for _ in range(4)]
    # Nothing is recorded between choices, so every call explores the same
    # untried first candidate (deterministic, reproducible).
    assert chosen == ["tfidf", "tfidf", "tfidf", "tfidf"]

    for index, strategy in enumerate(["tfidf", "bm25", "embedding", "hybrid"]):
        selector.record("deploy_service", strategy, success=index == 3)

    selection = selector.choose("deploy_service")
    assert selection["strategy"] == "hybrid"
    assert selection["trials"] == 1
    assert "UCB1" in selection["reason"]


def test_selector_learns_best_strategy_per_task_type(store: MemoryStore) -> None:
    selector = StrategySelector(store, exploration=0.0)
    for strategy in ("tfidf", "bm25", "embedding", "hybrid"):
        selector.record("build_project", strategy, success=strategy == "bm25")

    assert selector.choose("build_project")["strategy"] == "bm25"
    assert selector.choose("deploy_service")["strategy"] == "tfidf"


def test_selector_excludes_embedding_methods_without_an_embedder(
    store: MemoryStore,
) -> None:
    selector = StrategySelector(store)
    assert selector.candidates(embedder_available=False) == ("tfidf", "bm25")
    assert set(selector.candidates(embedder_available=True)) == {
        "tfidf",
        "bm25",
        "embedding",
        "hybrid",
    }


def test_adaptive_retriever_reports_and_uses_the_selected_strategy(
    store: MemoryStore, settings
) -> None:
    _seed(store)
    adaptive = dataclasses.replace(settings, retrieval_method="adaptive")
    retriever = _retriever(store, adaptive)

    results = retriever.retrieve(
        RetrievalQuery(text="Deploy the application", task_type="deploy_service")
    )
    assert results
    assert results[0].retrieval_strategy == "tfidf"
    assert results[0].retrieval_mode == "tfidf_fallback"
    assert results[0].selected is True

    retriever.strategy_selector.record(
        "deploy_service", "tfidf", success=False
    )
    second = retriever.retrieve(
        RetrievalQuery(text="Deploy the application", task_type="deploy_service")
    )
    assert second[0].retrieval_strategy == "bm25"
    assert second[0].retrieval_mode == "bm25_lexical"


def test_agent_records_adaptive_outcomes(runtime, settings) -> None:
    runtime.settings.retrieval_method = "adaptive"
    runtime.retriever.settings.retrieval_method = "adaptive"
    runtime.store.save(
        make_memory(
            id="deploy-mem",
            task="Deploy the application",
            task_type="deploy_service",
            action="deploy",
            prevention_actions=["load_config:DATABASE_URL", "validate_config:DATABASE_URL"],
        )
    )

    run = runtime.agent().run_task(
        "Deploy the application",
        deploy_env(),
        mode="memory",
        max_attempts=1,
        agent_id="agent-a",
    )

    assert run.strategy_selections
    selection = run.strategy_selections[0]
    assert selection["strategy"] == "tfidf"
    assert selection["success"] is True
    stats = runtime.store.strategy_stats()
    assert stats[0]["task_type"] == "deploy_service"
    assert stats[0]["strategy"] == "tfidf"
    assert stats[0]["trials"] == 1
