"""Retrieval relevance, safety gates, and contradiction handling."""

from __future__ import annotations

import dataclasses

from backend.domain import CauseStatus, FailureCategory, MemoryStatus
from backend.memory.models import RetrievalQuery
from backend.memory.retriever import MemoryRetriever, find_contradictions
from backend.memory.store import MemoryStore
from backend.tests.factories import make_memory


def _retriever(store: MemoryStore, settings) -> MemoryRetriever:
    from backend.memory.embedding import make_embedding_provider
    from backend.memory.ranking import MemoryRanker

    return MemoryRetriever(
        store, settings, embedder=make_embedding_provider(settings), ranker=MemoryRanker(settings)
    )


def test_relevant_memory_is_selected(store: MemoryStore, settings) -> None:
    memory = make_memory(
        id="deploy-mem",
        task="Deploy the application",
        task_type="deploy_service",
        action="deploy",
        prevention_actions=["validate_config:DATABASE_URL"],
    )
    store.save(memory)

    results = _retriever(store, settings).retrieve(
        RetrievalQuery(text="Deploy the application", task_type="deploy_service")
    )
    assert results
    top = results[0]
    assert top.memory.id == "deploy-mem"
    assert top.selected is True
    assert top.similarity > 0
    assert top.reason  # explainable


def test_confident_but_unrelated_memory_is_not_selected(store: MemoryStore, settings) -> None:
    """A high-confidence memory with no textual overlap must be filtered out.

    Regression test: previously the confidence/recency terms alone could push an
    unrelated memory over the score threshold despite negative similarity.
    """
    store.save(
        make_memory(
            id="rust-mem",
            task="Compile a Rust crate",
            task_type="build_project",
            action="cargo_build",
            failure="linker error",
            root_cause="missing system linker",
            prevention="Install build-essential",
            prevention_actions=["install_dependency:build-essential"],
            failure_category=FailureCategory.MISSING_DEPENDENCY,
            confidence=0.95,
        )
    )

    results = _retriever(store, settings).retrieve(
        RetrievalQuery(text="Deploy the application", task_type="deploy_service")
    )
    selected = [r for r in results if r.selected]
    assert selected == []
    assert any("relevance floor" in r.reason for r in results)


def test_inactive_memories_are_excluded(store: MemoryStore, settings) -> None:
    store.save(make_memory(id="active"))
    store.save(make_memory(id="incorrect", status=MemoryStatus.INCORRECT))

    results = _retriever(store, settings).retrieve(
        RetrievalQuery(text="Deploy the application", task_type="deploy_service")
    )
    assert {r.memory.id for r in results} == {"active"}

    included = _retriever(store, settings).retrieve(
        RetrievalQuery(
            text="Deploy the application", task_type="deploy_service", include_inactive=True
        )
    )
    assert {r.memory.id for r in included} == {"active", "incorrect"}


def test_retrieve_selected_respects_limit(store: MemoryStore, settings) -> None:
    for index in range(4):
        store.save(
            make_memory(
                id=f"m{index}",
                task="Deploy the application",
                action="deploy",
                root_cause=f"cause number {index}",
            )
        )
    query = RetrievalQuery(text="Deploy the application", task_type="deploy_service", limit=2)
    assert len(_retriever(store, settings).retrieve_selected(query)) == 2


def test_contradictory_memories_are_suppressed(store: MemoryStore, settings) -> None:
    stronger = make_memory(
        id="strong",
        task="Build the project",
        task_type="build_project",
        action="run_build",
        root_cause="pandas missing",
        prevention="Install pandas.",
        prevention_actions=["install_dependency:pandas"],
        confidence=0.9,
        success_count=5,
        failure_category=FailureCategory.MISSING_DEPENDENCY,
    )
    weaker = make_memory(
        id="weak",
        task="Build the project",
        task_type="build_project",
        action="run_build",
        root_cause="pandas missing",
        prevention="Install nonexistent-lib.",
        prevention_actions=["install_dependency:nonexistent-lib"],
        confidence=0.5,
        failure_category=FailureCategory.MISSING_DEPENDENCY,
    )
    store.save(stronger)
    store.save(weaker)

    results = _retriever(store, settings).retrieve(
        RetrievalQuery(text="Build the project", task_type="build_project", min_score=0.0)
    )
    by_id = {r.memory.id: r for r in results}
    assert by_id["strong"].selected is True
    assert by_id["weak"].selected is False
    assert "contradictory" in by_id["weak"].reason

    conflicts = find_contradictions(store.list())
    assert len(conflicts) == 1
    assert conflicts[0]["preferred_id"] == "strong"


def test_no_candidates_returns_empty(store: MemoryStore, settings) -> None:
    assert _retriever(store, settings).retrieve(RetrievalQuery(text="anything")) == []


def test_probe_reports_mode_and_matched_terms(store: MemoryStore, settings) -> None:
    store.save(make_memory(id="a", task="Deploy the application", action="deploy"))
    result = _retriever(store, settings).retrieve(
        RetrievalQuery(text="Deploy the application", task_type="deploy_service")
    )[0]
    assert result.retrieval_mode == "hashing_embedding"
    assert "deploy" in result.matched_terms
    assert result.components.similarity > 0


def test_retrieval_method_setting_selects_the_method(store: MemoryStore, settings) -> None:
    """`RETRIEVAL_METHOD` is honoured and each method reports its own honest mode."""
    store.save(make_memory(id="a", task="Deploy the application", action="deploy"))
    expected = {
        "tfidf": "tfidf_fallback",
        "bm25": "bm25_lexical",
        "embedding": "hashing_embedding",
        "hybrid": "hybrid_lexical_embedding",
    }
    for method, mode in expected.items():
        retriever = _retriever(store, dataclasses.replace(settings, retrieval_method=method))
        result = retriever.retrieve(
            RetrievalQuery(text="Deploy the application", task_type="deploy_service")
        )[0]
        assert result.retrieval_mode == mode, method


def test_lexical_retrieval_methods_are_never_labelled_semantic(
    store: MemoryStore, settings
) -> None:
    """A lexical method must never masquerade as a semantic/neural signal."""
    store.save(make_memory(id="a", task="Deploy the application", action="deploy"))
    for method in ("tfidf", "bm25", "hybrid"):
        retriever = _retriever(store, dataclasses.replace(settings, retrieval_method=method))
        result = retriever.retrieve(
            RetrievalQuery(text="Deploy the application", task_type="deploy_service")
        )[0]
        assert "semantic" not in result.retrieval_mode
        assert result.retrieval_mode != "neural_embedding"


def test_unknown_retrieval_method_falls_back_to_default(store: MemoryStore, settings) -> None:
    """A typo must never disable retrieval; it degrades to the historical default."""
    store.save(make_memory(id="a", task="Deploy the application", action="deploy"))
    weird = _retriever(store, dataclasses.replace(settings, retrieval_method="not-a-method"))
    result = weird.retrieve(
        RetrievalQuery(text="Deploy the application", task_type="deploy_service")
    )[0]
    assert result.retrieval_mode == "hashing_embedding"


def test_low_confidence_memory_can_be_surfaced_but_flag_relevant(
    store: MemoryStore, settings
) -> None:
    """Retrieval and application are deliberately separate decisions."""
    store.save(
        make_memory(
            id="low",
            task="Deploy the application",
            task_type="deploy_service",
            action="deploy",
            confidence=0.3,
            cause_status=CauseStatus.HYPOTHESIS,
            prevention_actions=["verify_outcome:app"],
        )
    )
    results = _retriever(store, settings).retrieve(
        RetrievalQuery(text="Deploy the application", task_type="deploy_service")
    )
    assert results[0].selected is True
    # ...but it is far below the apply threshold.
    assert results[0].memory.effective_confidence < settings.min_confidence_to_apply
