"""Automatic retrieval-strategy selection.

The retriever can be configured with ``RETRIEVAL_METHOD=adaptive``. Instead of
fixing one text-similarity method, it runs a deterministic, explainable
multi-armed bandit over the methods that are actually available:

* every strategy is tried at least once (systematic experimentation);
* afterwards the strategy with the highest **UCB1** score is chosen, which
  balances the observed success rate against uncertainty;
* outcomes are persisted per ``(task_type, strategy)`` and shared across
  agents, so one agent's experiments benefit the others;
* ties are broken by the fixed candidate order, never by randomness, so a run
  is reproducible.

An "outcome" is measured at the agent level: an attempt that retrieved at least
one selected memory succeeded or failed. This makes the selector optimise for
the method that actually helps the agent, not merely for offline similarity.
"""

from __future__ import annotations

import math

from backend.memory.similarity import RETRIEVAL_METHODS
from backend.memory.store import MemoryStore

DEFAULT_EXPLORATION = 0.35


class StrategySelector:
    """Deterministic UCB1 selection over retrieval similarity methods."""

    def __init__(
        self,
        store: MemoryStore,
        *,
        exploration: float = DEFAULT_EXPLORATION,
        candidates: tuple[str, ...] | list[str] | None = None,
    ) -> None:
        self.store = store
        self.exploration = max(0.0, float(exploration))
        self._candidates = tuple(candidates or RETRIEVAL_METHODS)

    def candidates(self, *, embedder_available: bool = True) -> tuple[str, ...]:
        """Methods that can produce a distinct signal in this deployment.

        Without an embedder the ``embedding`` method silently degrades to
        TF-IDF and ``hybrid`` to BM25, so selecting them would compare a method
        against itself. They are excluded rather than reported as something
        they are not.
        """
        if embedder_available:
            return self._candidates
        return tuple(method for method in self._candidates if method in {"tfidf", "bm25"})

    def choose(
        self,
        task_type: str,
        *,
        embedder_available: bool = True,
    ) -> dict:
        """Choose a strategy and explain the decision.

        Untried candidates are explored first in a fixed order. Once every
        candidate has evidence, the highest UCB1 score wins.
        """
        candidates = self.candidates(embedder_available=embedder_available)
        if not candidates:  # pragma: no cover - defensive: RETRIEVAL_METHODS is non-empty
            raise ValueError("no retrieval strategies are available")

        normalized_task = (task_type or "").strip().lower() or "generic"
        stats = self.store.strategy_stats_for(normalized_task)
        trials = {method: int(stats.get(method, {}).get("trials", 0)) for method in candidates}
        total_trials = sum(trials.values())

        for method in candidates:
            if trials[method] == 0:
                return {
                    "task_type": normalized_task,
                    "strategy": method,
                    "reason": "exploring an untried strategy",
                    "trials": 0,
                    "success_rate": 0.0,
                    "ucb_score": None,
                    "total_trials": total_trials,
                }

        scored: list[tuple[float, int, str]] = []
        for index, method in enumerate(candidates):
            method_stats = stats.get(method, {})
            successes = int(method_stats.get("successes", 0))
            success_rate = successes / trials[method] if trials[method] else 0.0
            bonus = self.exploration * math.sqrt(
                math.log(max(total_trials, 1)) / max(trials[method], 1)
            )
            scored.append((success_rate + bonus, -index, method))

        best_score, _, best = max(scored)
        best_stats = stats.get(best, {})
        return {
            "task_type": normalized_task,
            "strategy": best,
            "reason": (
                f"highest UCB1 score {best_score:.3f} "
                f"({int(best_stats.get('successes', 0))}/{trials[best]} successes, "
                f"exploration {self.exploration:.2f})"
            ),
            "trials": trials[best],
            "success_rate": round(int(best_stats.get("successes", 0)) / trials[best], 4),
            "ucb_score": round(best_score, 4),
            "total_trials": total_trials,
        }

    def record(
        self,
        task_type: str,
        strategy: str,
        *,
        success: bool,
        agent_id: str | None = None,
    ) -> dict:
        """Persist one observed outcome (delegates to the store)."""
        return self.store.record_strategy_outcome(
            task_type, strategy, success=success, agent_id=agent_id
        )
