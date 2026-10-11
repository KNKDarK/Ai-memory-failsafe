"""Wiring helpers that assemble a complete runtime from settings.

Centralising construction keeps the API, the CLI, and the evaluation harness
using exactly the same components (and therefore comparable behaviour).
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.agent.agent import FailureMemoryAgent
from backend.agent.executor import AgentExecutor
from backend.agent.planner import TaskPlanner
from backend.analysis.failure_analyzer import FailureAnalyzer
from backend.config import Settings, get_settings
from backend.memory.embedding import EmbeddingProvider, make_embedding_provider
from backend.memory.ranking import MemoryRanker
from backend.memory.retriever import MemoryRetriever
from backend.memory.store import MemoryStore


@dataclass
class Runtime:
    settings: Settings
    store: MemoryStore
    embedder: EmbeddingProvider | None
    retriever: MemoryRetriever
    analyzer: FailureAnalyzer
    planner: TaskPlanner
    executor: AgentExecutor

    def agent(self) -> FailureMemoryAgent:
        return FailureMemoryAgent(
            self.store,
            self.settings,
            analyzer=self.analyzer,
            planner=self.planner,
            executor=self.executor,
            retriever=self.retriever,
        )


def build_runtime(settings: Settings | None = None, store: MemoryStore | None = None) -> Runtime:
    settings = settings or get_settings()
    settings.ensure_data_dir()
    store = store or MemoryStore(settings.memory_database)
    embedder = make_embedding_provider(settings)
    retriever = MemoryRetriever(
        store,
        settings,
        embedder=embedder,
        ranker=MemoryRanker(settings),
    )
    return Runtime(
        settings=settings,
        store=store,
        embedder=embedder,
        retriever=retriever,
        analyzer=FailureAnalyzer(settings),
        planner=TaskPlanner(),
        executor=AgentExecutor(settings),
    )
