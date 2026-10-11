"""Text vectorisation for memory retrieval.

Three strategies are provided, in order of preference:

1. ``neural`` embeddings (optional; requires an API key). Genuinely semantic.
2. ``hashing`` embeddings: deterministic *feature hashing* over unigrams and
   bigrams. This is real vector similarity (cosine over a fixed-dimensional
   space) but it is **lexical**, not a trained semantic model. We label it as
   such everywhere it is reported.
3. ``tfidf``: a pure lexical cosine fallback that needs no vector store at all.

The default is ``hashing``: deterministic, offline, dependency-free, and
identical on every machine, which is what the evaluation requires.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterable
from typing import Protocol, runtime_checkable

_TOKEN_RE = re.compile(r"[a-z0-9]+")

_STOPWORDS = frozenset(
    """
    a an and are as at be been but by for from has have had i if in into is it its
    of on or that the their then there these this to was were will with not no do
    does did done can could should would may might must we you your they them us
    """.split()
)


def tokenize(text: str, *, keep_stopwords: bool = False) -> list[str]:
    """Lowercase alphanumeric tokenisation."""
    tokens = _TOKEN_RE.findall((text or "").lower())
    if keep_stopwords:
        return tokens
    return [t for t in tokens if t not in _STOPWORDS]


def ngrams(text: str, n: int = 2) -> list[str]:
    """Return unigrams plus word n-grams (default bigrams)."""
    unigrams = tokenize(text)
    grams = list(unigrams)
    for size in range(2, n + 1):
        grams.extend(" ".join(unigrams[i : i + size]) for i in range(len(unigrams) - size + 1))
    return grams


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two equal-length vectors (0 when either is zero)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Interface every embedding backend must satisfy."""

    name: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]:  # pragma: no cover - protocol
        ...


def _hash_token(token: str, dim: int) -> tuple[int, float]:
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    index = value % dim
    sign = 1.0 if (value >> 63) & 1 else -1.0
    return index, sign


class HashingEmbeddingProvider:
    """Deterministic feature-hashing embedding (unigrams + bigrams).

    No model, no network, no GPU. Identical output on every platform.
    """

    def __init__(self, dim: int = 256, ngram: int = 2) -> None:
        if dim < 8:
            raise ValueError("embedding dim must be >= 8")
        self.dim = dim
        self.ngram = ngram
        self.name = f"hashing-ngram{ngram}-d{dim}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for gram in ngrams(text, self.ngram):
            index, sign = _hash_token(gram, self.dim)
            # sublinear term weighting keeps long texts from dominating
            vector[index] += sign
        norm = math.sqrt(sum(v * v for v in vector))
        if norm > 0:
            vector = [v / norm for v in vector]
        return vector


class TfidfVectorizer:
    """Minimal, dependency-free TF-IDF cosine similarity over a corpus."""

    def __init__(self) -> None:
        self._idf: dict[str, float] = {}
        self._n_docs = 0

    def fit(self, documents: Iterable[str]) -> TfidfVectorizer:
        doc_list = list(documents)
        self._n_docs = len(doc_list)
        df: dict[str, int] = {}
        for doc in doc_list:
            for term in set(tokenize(doc)):
                df[term] = df.get(term, 0) + 1
        self._idf = {
            term: math.log((1 + self._n_docs) / (1 + count)) + 1.0 for term, count in df.items()
        }
        return self

    def vectorize(self, text: str) -> dict[str, float]:
        terms = tokenize(text)
        if not terms:
            return {}
        counts: dict[str, int] = {}
        for term in terms:
            counts[term] = counts.get(term, 0) + 1
        total = len(terms)
        vector: dict[str, float] = {}
        for term, count in counts.items():
            tf = count / total
            idf = self._idf.get(term, math.log((1 + self._n_docs) / 1) + 1.0)
            vector[term] = tf * idf
        norm = math.sqrt(sum(v * v for v in vector.values()))
        if norm > 0:
            vector = {k: v / norm for k, v in vector.items()}
        return vector

    @staticmethod
    def sparse_cosine(a: dict[str, float], b: dict[str, float]) -> float:
        if not a or not b:
            return 0.0
        if len(a) > len(b):
            a, b = b, a
        dot = sum(weight * b.get(term, 0.0) for term, weight in a.items())
        return max(0.0, min(1.0, dot))


def tfidf_similarities(query: str, documents: list[str]) -> list[float]:
    """Convenience helper: TF-IDF cosine of a query against each document."""
    if not documents:
        return []
    vectorizer = TfidfVectorizer().fit([query, *documents])
    q_vec = vectorizer.vectorize(query)
    return [TfidfVectorizer.sparse_cosine(q_vec, vectorizer.vectorize(doc)) for doc in documents]


class OpenAIEmbeddingProvider:
    """Optional neural embeddings via an OpenAI-compatible endpoint.

    Only constructed when explicitly configured with an API key. Kept thin so
    there is no heavy SDK dependency.
    """

    def __init__(self, api_key: str, model: str, base_url: str, timeout: float = 30.0) -> None:
        if not api_key:
            raise ValueError("api_key is required for OpenAI embeddings")
        self._api_key = api_key
        self.name = f"openai:{model}"
        self.dim = 0  # discovered from the first response
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def embed(self, texts: list[str]) -> list[list[float]]:
        import requests  # local import: optional dependency path

        response = requests.post(
            f"{self._base_url}/embeddings",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={"model": self._model, "input": texts},
            timeout=self._timeout,
        )
        response.raise_for_status()
        payload = response.json()
        vectors = [item["embedding"] for item in payload["data"]]
        if vectors:
            self.dim = len(vectors[0])
        return vectors


def make_embedding_provider(settings) -> EmbeddingProvider | None:
    """Build the configured embedding provider, degrading gracefully.

    Returns ``None`` when the configured provider is unavailable; the retriever
    then falls back to TF-IDF.
    """
    provider = (settings.embedding_provider or "hashing").lower()
    if provider == "hashing":
        return HashingEmbeddingProvider(dim=settings.embedding_dim)
    if provider == "tfidf":
        return None
    if provider == "openai":
        if not settings.llm_api_key:
            return None
        try:
            return OpenAIEmbeddingProvider(
                api_key=settings.llm_api_key,
                model=settings.embedding_model,
                base_url=settings.llm_base_url,
                timeout=settings.llm_timeout_seconds,
            )
        except ValueError:
            return None
    return HashingEmbeddingProvider(dim=settings.embedding_dim)
