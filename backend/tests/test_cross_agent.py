"""Cross-agent learning: provenance, sharing boundaries, and reuse."""

from __future__ import annotations

from backend.memory.models import FailureMemory, RetrievalQuery
from backend.memory.store import MemoryStore
from backend.services import Runtime
from backend.tests.factories import deploy_env, make_memory


def test_agent_a_learns_and_agent_b_reuses_the_shared_lesson(runtime: Runtime) -> None:
    agent = runtime.agent()

    learner = agent.run_task(
        "Deploy the application",
        deploy_env(),
        mode="memory",
        max_attempts=2,
        agent_id="agent-a",
    )
    assert learner.final_success is True
    assert learner.memory_ids_created
    memory = runtime.store.get(learner.memory_ids_created[0])
    assert memory is not None
    assert memory.agent_id == "agent-a"
    assert memory.shared is True

    consumer = agent.run_task(
        "Deploy the application",
        deploy_env(),
        mode="memory",
        max_attempts=2,
        agent_id="agent-b",
    )
    assert consumer.final_success is True
    assert consumer.attempts_used == 1
    assert memory.id in consumer.memory_ids_applied

    reused = runtime.store.get(memory.id)
    assert reused is not None
    assert "agent-b" in reused.used_by_agent_ids


def test_unshared_memory_stays_private_to_its_origin(runtime: Runtime) -> None:
    private = make_memory(id="private", agent_id="agent-a", shared=False)
    runtime.store.save(private)

    own = runtime.agent().preview_retrieval(
        "Deploy the application", deploy_env(), agent_id="agent-a"
    )
    other = runtime.agent().preview_retrieval(
        "Deploy the application", deploy_env(), agent_id="agent-b"
    )

    assert [result.memory.id for result in own if result.selected] == ["private"]
    assert [result.memory.id for result in other if result.selected] == []


def test_low_confidence_shared_memory_is_not_cross_agent_verified(
    runtime: Runtime,
) -> None:
    weak = make_memory(
        id="weak",
        agent_id="agent-a",
        shared=True,
        confidence=0.2,
    )
    runtime.store.save(weak)

    results = runtime.agent().preview_retrieval(
        "Deploy the application", deploy_env(), agent_id="agent-b"
    )
    assert [result.memory.id for result in results if result.selected] == []


def test_merging_same_lesson_records_contributing_agents(store: MemoryStore) -> None:
    first, created = store.merge_or_store(make_memory(id="a", agent_id="agent-a"))
    second, created_again = store.merge_or_store(make_memory(id="b", agent_id="agent-b"))

    assert created is True
    assert created_again is False
    assert second.id == first.id
    assert second.agent_id == "agent-a"
    assert second.contributing_agent_ids == ["agent-b"]

    store.record_use(second.id, success=True, agent_id="agent-b")
    updated = store.get(second.id)
    assert updated is not None
    assert "agent-b" in updated.used_by_agent_ids


def test_agent_stats_show_cross_agent_reuse(store: MemoryStore) -> None:
    memory = make_memory(id="m1", agent_id="agent-a")
    store.save(memory)
    store.record_use(memory.id, success=True, agent_id="agent-b")

    stats = store.agent_stats()
    assert stats["total_agents"] == 2
    assert stats["cross_agent_memories"] == 1
    assert stats["cross_agent_reuse_events"] == 1
    by_agent = {item["agent_id"]: item for item in stats["agents"]}
    assert by_agent["agent-a"]["memories_created"] == 1
    assert by_agent["agent-b"]["memories_used"] == 1


def test_store_roundtrips_cross_agent_fields(store: MemoryStore) -> None:
    memory: FailureMemory = make_memory(
        id="roundtrip",
        agent_id="agent-a",
        contributing_agent_ids=["agent-b"],
        used_by_agent_ids=["agent-c"],
        shared=False,
    )
    store.save(memory)

    loaded = store.get("roundtrip")
    assert loaded is not None
    assert loaded.agent_id == "agent-a"
    assert loaded.contributing_agent_ids == ["agent-b"]
    assert loaded.used_by_agent_ids == ["agent-c"]
    assert loaded.shared is False


def test_cross_agent_scope_is_ignored_without_requesting_agent(
    store: MemoryStore, settings
) -> None:
    from backend.memory.embedding import make_embedding_provider
    from backend.memory.ranking import MemoryRanker
    from backend.memory.retriever import MemoryRetriever

    store.save(make_memory(id="a", agent_id="agent-a", shared=False))
    retriever = MemoryRetriever(
        store,
        settings,
        embedder=make_embedding_provider(settings),
        ranker=MemoryRanker(settings),
    )
    results = retriever.retrieve(
        RetrievalQuery(text="Deploy the application", task_type="deploy_service")
    )
    assert [result.memory.id for result in results] == ["a"]
