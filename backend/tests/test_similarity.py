"""Tests for the pluggable retrieval similarity methods (the retrieval study)."""

from __future__ import annotations

import pytest

from backend.memory.embedding import HashingEmbeddingProvider
from backend.memory.similarity import (
    RETRIEVAL_METHODS,
    bm25_similarities,
    hybrid_similarities,
    method_similarities,
)


def test_bm25_ranks_matching_document_first() -> None:
    documents = [
        "deploy failed missing configuration database url",
        "unrelated sentence about weather and traffic",
    ]
    scores = bm25_similarities("missing configuration database", documents)
    assert scores[0] > scores[1]
    assert scores[0] == 1.0  # max-normalised to the batch
    assert scores[1] == 0.0


def test_bm25_without_overlap_is_all_zero() -> None:
    scores = bm25_similarities("completely unrelated query", ["alpha beta", "gamma delta"])
    assert scores == [0.0, 0.0]


def test_bm25_handles_empty_documents() -> None:
    assert bm25_similarities("query", []) == []


def test_hybrid_without_embedder_matches_bm25() -> None:
    documents = ["retry http 503 with backoff", "css styling and layout"]
    assert hybrid_similarities("http 503", documents, embedder=None) == bm25_similarities(
        "http 503", documents
    )


def test_hybrid_fuses_lexical_and_embedding() -> None:
    documents = ["retry http 503 with backoff", "unrelated prose about gardens"]
    hybrid = hybrid_similarities("http 503 retry", documents, embedder=HashingEmbeddingProvider())
    assert hybrid[0] > hybrid[1]


@pytest.mark.parametrize(
    ("method", "expected_mode"),
    [
        ("tfidf", "tfidf_fallback"),
        ("bm25", "bm25_lexical"),
        ("embedding", "hashing_embedding"),
        ("hybrid", "hybrid_lexical_embedding"),
    ],
)
def test_method_labels_are_truthful(method: str, expected_mode: str) -> None:
    scores, mode = method_similarities(
        method, "http 503", ["retry http 503 with backoff"], embedder=HashingEmbeddingProvider()
    )
    assert mode == expected_mode
    assert len(scores) == 1


def test_embedding_method_falls_back_to_tfidf_without_provider() -> None:
    scores, mode = method_similarities("embedding", "query", ["document"], embedder=None)
    assert mode == "tfidf_fallback"
    assert len(scores) == 1


def test_unknown_method_raises() -> None:
    with pytest.raises(ValueError):
        method_similarities("nope", "query", ["document"], embedder=None)


def test_retrieval_methods_are_the_study_set() -> None:
    assert set(RETRIEVAL_METHODS) == {"tfidf", "bm25", "embedding", "hybrid"}
