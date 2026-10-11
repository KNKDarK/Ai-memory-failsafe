"""Pluggable text-similarity methods for the retrieval study.

Five deterministic, offline methods are supported so retrieval quality can be
compared head-to-head on the same labelled probes:

* ``tfidf``     - TF-IDF cosine (pure lexical, corpus-relative).
* ``bm25``      - Okapi BM25 (lexical, saturating term frequency).
* ``embedding`` - the configured embedding provider (feature hashing or neural).
* ``hybrid``    - a fixed-weight fusion of BM25 and the embedding signal.
* ``auto``      - the retriever's historical default (embedding if available,
  else TF-IDF); kept so existing behaviour is unchanged.

BM25 scores are unbounded, so they are max-normalised into ``[0, 1]`` for the
batch. That keeps every method on the same scale as the retriever's similarity
floor and makes the comparison honest: an all-irrelevant batch cannot produce a
high score for the best of a bad lot unless the lexical evidence really is there
(each raw score is still 0 when no query term occurs in any document).
"""

from __future__ import annotations

import math

from backend.memory.embedding import (
    EmbeddingProvider,
    cosine_similarity,
    tfidf_similarities,
    tokenize,
)

RETRIEVAL_METHODS: tuple[str, ...] = ("tfidf", "bm25", "embedding", "hybrid")
"""Methods that can be compared or selected explicitly (``auto`` is a routing
mode, not a similarity algorithm)."""


def bm25_similarities(
    query: str,
    documents: list[str],
    *,
    k1: float = 1.5,
    b: float = 0.75,
) -> list[float]:
    """Okapi BM25 relevance, max-normalised to ``[0, 1]`` per batch."""
    if not documents:
        return []
    query_terms = tokenize(query)
    doc_tokens = [tokenize(doc) for doc in documents]
    n_docs = len(doc_tokens)
    if not query_terms or n_docs == 0:
        return [0.0] * len(documents)

    avgdl = sum(len(tokens) for tokens in doc_tokens) / n_docs
    doc_freq: dict[str, int] = {}
    for tokens in doc_tokens:
        for term in set(tokens):
            doc_freq[term] = doc_freq.get(term, 0) + 1

    scores: list[float] = []
    for tokens in doc_tokens:
        term_freq: dict[str, int] = {}
        for term in tokens:
            term_freq[term] = term_freq.get(term, 0) + 1
        length = len(tokens)
        score = 0.0
        for term in query_terms:
            freq = term_freq.get(term)
            if not freq:
                continue
            count = doc_freq.get(term, 0)
            idf = math.log(1.0 + (n_docs - count + 0.5) / (count + 0.5))
            denom = freq + k1 * (1.0 - b + b * (length / avgdl if avgdl else 1.0))
            score += idf * (freq * (k1 + 1.0)) / denom
        scores.append(score)

    top = max(scores)
    if top <= 0.0:
        return [0.0] * len(documents)
    return [round(value / top, 6) for value in scores]


def _embedding_scores(query: str, documents: list[str], embedder: EmbeddingProvider) -> list[float]:
    vectors = embedder.embed([query, *documents])
    query_vec = vectors[0]
    return [cosine_similarity(query_vec, vector) for vector in vectors[1:]]


def hybrid_similarities(
    query: str,
    documents: list[str],
    *,
    embedder: EmbeddingProvider | None,
    alpha: float = 0.5,
) -> list[float]:
    """Fixed-weight fusion of BM25 and the embedding signal.

    ``alpha`` weights the embedding term; ``1 - alpha`` weights BM25. When no
    embedder is available the method degrades to pure BM25 (reported truthfully
    by the caller via the mode label).
    """
    lexical = bm25_similarities(query, documents)
    if embedder is None:
        return lexical
    semantic = _embedding_scores(query, documents, embedder)
    return [
        round(alpha * sem + (1.0 - alpha) * lex, 6)
        for lex, sem in zip(lexical, semantic, strict=True)
    ]


def method_similarities(
    method: str,
    query: str,
    documents: list[str],
    *,
    embedder: EmbeddingProvider | None,
) -> tuple[list[float], str]:
    """Score ``documents`` against ``query`` with one method.

    Returns ``(scores, mode_label)`` where the label is always truthful about
    what was actually computed (lexical vs embedding vs hybrid).
    """
    method = (method or "auto").lower()
    if method == "tfidf":
        return tfidf_similarities(query, documents), "tfidf_fallback"
    if method == "bm25":
        return bm25_similarities(query, documents), "bm25_lexical"
    if method == "embedding":
        if embedder is not None:
            label = (
                "neural_embedding" if embedder.name.startswith("openai") else "hashing_embedding"
            )
            return _embedding_scores(query, documents, embedder), label
        return tfidf_similarities(query, documents), "tfidf_fallback"
    if method == "hybrid":
        scores = hybrid_similarities(query, documents, embedder=embedder)
        label = "hybrid_lexical_embedding" if embedder is not None else "bm25_lexical"
        return scores, label
    raise ValueError(f"unknown retrieval method: {method!r}")
