"""Failure-memory retrieval, ranking, and explanation.

Pipeline:

``query -> candidate set -> similarity -> weighted score -> threshold ->
contradiction suppression -> ranked results (with explanations)``

Similarity uses a neural embedding provider when one is configured; otherwise it
falls back to a deterministic hashing embedding or plain TF-IDF. The mode used
is reported on every result so the system never claims semantic retrieval when
it only performed lexical matching.
"""

from __future__ import annotations

from datetime import datetime

from backend.domain import MemoryStatus, utcnow
from backend.memory.embedding import (
    EmbeddingProvider,
    cosine_similarity,
    tfidf_similarities,
    tokenize,
)
from backend.memory.models import (
    FailureMemory,
    RetrievalQuery,
    RetrievalResult,
)
from backend.memory.ranking import MemoryRanker
from backend.memory.similarity import method_similarities
from backend.memory.store import MemoryStore, normalize_text
from backend.memory.strategies import DEFAULT_EXPLORATION, StrategySelector


def memory_document(memory: FailureMemory) -> str:
    """The searchable text representation of a memory."""
    return " ".join(
        [
            memory.task,
            memory.task_type,
            memory.action,
            memory.failure,
            memory.failure_category.value,
            memory.root_cause,
            memory.lesson,
            memory.prevention,
            " ".join(memory.tags),
        ]
    )


def query_document(query: RetrievalQuery) -> str:
    parts = [query.text]
    if query.task_type:
        parts.append(query.task_type)
    if query.action:
        parts.append(query.action)
    parts.extend(query.tags)
    return " ".join(p for p in parts if p)


class MemoryRetriever:
    """Retrieves the most relevant, trustworthy memories for a task."""

    def __init__(
        self,
        store: MemoryStore,
        settings,
        *,
        embedder: EmbeddingProvider | None = None,
        ranker: MemoryRanker | None = None,
        strategy_selector: StrategySelector | None = None,
    ) -> None:
        self.store = store
        self.settings = settings
        self.embedder = embedder
        self.ranker = ranker or MemoryRanker(settings)
        self.strategy_selector = strategy_selector or StrategySelector(
            store,
            exploration=getattr(settings, "retrieval_strategy_exploration", DEFAULT_EXPLORATION),
        )

    # ------------------------------------------------------------------ #
    def retrieve(
        self,
        query: RetrievalQuery | str,
        *,
        now: datetime | None = None,
    ) -> list[RetrievalResult]:
        if isinstance(query, str):
            query = RetrievalQuery(text=query)
        now = now or utcnow()

        candidates = self.store.list(
            include_inactive=query.include_inactive,
        )
        if not candidates:
            return []

        # Filter out statuses that must never be surfaced by default.
        if not query.include_inactive:
            candidates = [m for m in candidates if m.status == MemoryStatus.ACTIVE]
        # Cross-agent scope: own/shared lessons only when a requesting agent is
        # identified. No agent id preserves the historical store-wide view.
        candidates = self._cross_agent_candidates(candidates, query)
        if not candidates:
            return []

        q_text = query_document(query)
        similarities, mode, strategy = self._similarities(
            q_text, candidates, task_type=query.task_type
        )
        q_terms = set(tokenize(q_text))
        min_similarity = getattr(self.settings, "retrieval_min_similarity", 0.0)

        results: list[RetrievalResult] = []
        for memory, similarity in zip(candidates, similarities, strict=True):
            score, components = self.ranker.score(memory, similarity, now=now)
            matched = [
                term
                for term in tokenize(memory_document(memory))
                if term in q_terms and term not in {""}
            ]
            # de-duplicate while preserving order
            seen: set[str] = set()
            matched_terms = [t for t in matched if not (t in seen or seen.add(t))][:12]
            reason = self.ranker.explain(memory, components, matched_terms, mode)
            if strategy:
                reason = f"adaptive strategy {strategy}; {reason}"
            # Two gates: an overall score floor *and* a text-similarity floor.
            # The second stops a confident but textually unrelated memory from
            # being surfaced on the strength of confidence/recency alone.
            relevant = similarity >= min_similarity
            selected = score >= query.min_score and relevant
            if not relevant:
                reason += (
                    f"; not selected: text similarity {similarity:.2f} below "
                    f"relevance floor {min_similarity:.2f}"
                )
            results.append(
                RetrievalResult(
                    memory=memory,
                    score=score,
                    similarity=round(similarity, 4),
                    components=components,
                    matched_terms=matched_terms,
                    selected=selected,
                    reason=reason,
                    retrieval_strategy=strategy,
                    retrieval_mode=mode,
                )
            )

        results.sort(key=lambda r: (-r.score, -r.memory.effective_confidence, r.memory.id))
        results = self._suppress_contradictions(results)
        for index, result in enumerate(results, start=1):
            result.rank = index
        # Hard safety cap so a huge store cannot flood a caller; callers apply
        # their own limit via ``retrieve_selected``.
        return results[:50]

    def retrieve_selected(
        self, query: RetrievalQuery | str, *, now: datetime | None = None
    ) -> list[RetrievalResult]:
        """Return only results above the relevance threshold, ranked and limited.

        This is what the agent uses, so unrelated memories never reach the prompt.
        """
        if isinstance(query, str):
            query = RetrievalQuery(text=query)
        results = [r for r in self.retrieve(query, now=now) if r.selected]
        limit = query.limit if query.limit is not None else self.settings.retrieval_limit
        return results[:limit]

    # ------------------------------------------------------------------ #
    def _cross_agent_candidates(
        self, memories: list[FailureMemory], query: RetrievalQuery
    ) -> list[FailureMemory]:
        """Apply the requesting agent's visibility rules.

        * Own lessons are always visible (created, reinforced, or previously
          used by the agent).
        * Other agents' lessons require ``shared=True``, an enabled
          cross-agent policy, and enough effective confidence to count as
          *verified*. This prevents a single low-trust observation from
          leaking across agents.
        """
        agent_id = (query.agent_id or "").strip()
        if not agent_id:
            return memories
        share_enabled = bool(getattr(self.settings, "cross_agent_learning", True))
        min_confidence = float(getattr(self.settings, "cross_agent_min_confidence", 0.55))

        def visible(memory: FailureMemory) -> bool:
            if (
                memory.agent_id == agent_id
                or agent_id in memory.contributing_agent_ids
                or agent_id in memory.used_by_agent_ids
            ):
                return True
            if not query.cross_agent or not share_enabled or not memory.shared:
                return False
            return memory.effective_confidence >= min_confidence

        return [memory for memory in memories if visible(memory)]

    # ------------------------------------------------------------------ #
    def _similarities(
        self,
        query_text: str,
        memories: list[FailureMemory],
        *,
        task_type: str | None = None,
    ) -> tuple[list[float], str, str]:
        """Return ``(scores, mode_label, adaptive_strategy)``.

        The third value is non-empty only when automatic strategy selection
        chose the method; callers use it to feed the outcome back into the
        bandit. Explicit and ``auto`` methods always report an empty strategy
        so they are never accidentally recorded as an experiment.
        """
        docs = [memory_document(m) for m in memories]
        method = (getattr(self.settings, "retrieval_method", "auto") or "auto").lower()
        if method == "adaptive":
            selection = self.strategy_selector.choose(
                task_type or "generic",
                embedder_available=self.embedder is not None,
            )
            chosen = selection["strategy"]
            scores, label = method_similarities(chosen, query_text, docs, embedder=self.embedder)
            return scores, label, chosen
        if method != "auto":
            try:
                scores, label = method_similarities(
                    method, query_text, docs, embedder=self.embedder
                )
                return scores, label, ""
            except ValueError:
                # Unknown method configured; fall back to the default routing so a
                # typo can never disable retrieval entirely.
                pass
        if self.embedder is not None:
            try:
                vectors = self.embedder.embed([query_text, *docs])
                query_vec = vectors[0]
                sims = [cosine_similarity(query_vec, v) for v in vectors[1:]]
                mode = (
                    "neural_embedding"
                    if self.embedder.name.startswith("openai")
                    else "hashing_embedding"
                )
                return sims, mode, ""
            except Exception:  # pragma: no cover - network/provider failure path
                # Any provider failure degrades to the deterministic fallback.
                pass
        return tfidf_similarities(query_text, docs), "tfidf_fallback", ""

    # ------------------------------------------------------------------ #
    def _suppress_contradictions(self, results: list[RetrievalResult]) -> list[RetrievalResult]:
        """Drop lower-confidence memories that contradict a higher-ranked one.

        Two memories contradict when they target the same ``task_type`` and
        ``action`` but recommend different preventions. We keep the one with the
        higher effective confidence and annotate the suppressed memory instead of
        silently removing it, so the decision is auditable.
        """
        winners: dict[tuple[str, str], RetrievalResult] = {}
        for result in results:
            key = (normalize_text(result.memory.task_type), normalize_text(result.memory.action))
            if not key[0] and not key[1]:
                continue
            current = winners.get(key)
            if current is None:
                winners[key] = result
                continue
            same_prevention = normalize_text(current.memory.prevention) == normalize_text(
                result.memory.prevention
            )
            if same_prevention:
                # Keep the higher-scoring one.
                if result.score > current.score:
                    winners[key] = result
                continue
            # Contradiction: highest effective confidence wins.
            if result.memory.effective_confidence > current.memory.effective_confidence:
                current.selected = False
                current.reason += (
                    f"; suppressed as contradictory to {result.memory.id[:8]} "
                    f"(lower effective confidence)"
                )
                winners[key] = result
            else:
                result.selected = False
                result.reason += (
                    f"; suppressed as contradictory to {current.memory.id[:8]} "
                    f"(lower effective confidence)"
                )
        return results


def find_contradictions(memories: list[FailureMemory]) -> list[dict]:
    """Detect stored memories that give conflicting prevention advice."""
    groups: dict[tuple[str, str], list[FailureMemory]] = {}
    for memory in memories:
        key = (normalize_text(memory.task_type), normalize_text(memory.action))
        groups.setdefault(key, []).append(memory)

    conflicts: list[dict] = []
    for key, group in groups.items():
        if len(group) < 2:
            continue
        preventions = {normalize_text(m.prevention): m for m in group}
        if len(preventions) > 1:
            ordered = sorted(group, key=lambda m: -m.effective_confidence)
            conflicts.append(
                {
                    "task_type": key[0],
                    "action": key[1],
                    "preferred_id": ordered[0].id,
                    "memories": [
                        {
                            "id": m.id,
                            "prevention": m.prevention,
                            "effective_confidence": round(m.effective_confidence, 4),
                        }
                        for m in ordered
                    ],
                }
            )
    return conflicts
