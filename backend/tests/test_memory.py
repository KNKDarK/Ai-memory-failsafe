"""Persistence, deduplication, feedback, and trust tests for the memory store."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.domain import FeedbackVerdict, MemoryStatus
from backend.memory.models import FailureMemory
from backend.memory.store import MemoryStore, dedup_key, normalize_text
from backend.tests.factories import make_memory

MALFORMED_COLUMNS = (
    "id, schema_version, task, task_type, action, failure, failure_category, root_cause, "
    "cause_status, evidence, lesson, prevention, prevention_actions, tags, confidence, "
    "status, occurrence_count, use_count, success_count, failure_count, helpful_count, "
    "unhelpful_count, created_at, updated_at"
)


def test_save_and_get_roundtrip(store: MemoryStore) -> None:
    memory = make_memory(id="m-roundtrip")
    store.save(memory)

    loaded = store.get("m-roundtrip")
    assert loaded is not None
    assert loaded.task == memory.task
    assert loaded.prevention_actions == memory.prevention_actions
    assert loaded.confidence == memory.confidence


def test_persists_across_connections(tmp_path) -> None:
    path = str(tmp_path / "memory.db")
    first = MemoryStore(path)
    first.save(make_memory(id="persisted"))
    assert first.count() == 1
    first.close()

    second = MemoryStore(path)
    try:
        loaded = second.get("persisted")
        assert loaded is not None
        assert loaded.id == "persisted"
        assert second.count() == 1
    finally:
        second.close()


def test_malformed_rows_are_skipped_not_fatal(store: MemoryStore) -> None:
    store.save(make_memory(id="good"))
    # Inject a row that violates the enum + JSON invariants.
    store._conn.execute(
        f"INSERT INTO failure_memories ({MALFORMED_COLUMNS}) VALUES ("  # noqa: SLF001
        "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "bad",
            1,
            "task",
            "generic",
            "act",
            "fail",
            "not_a_real_category",
            "cause",
            "confirmed",
            "{not json",
            "lesson",
            "prevention",
            "[]",
            "[]",
            "not-a-float",
            "active",
            1,
            0,
            0,
            0,
            0,
            0,
            "2020-01-01T00:00:00+00:00",
            "2020-01-01T00:00:00+00:00",
        ),
    )
    store._conn.commit()

    rows = store.list()
    assert [m.id for m in rows] == ["good"]
    assert store.malformed_row_count() == 1


def test_merge_or_store_deduplicates(store: MemoryStore) -> None:
    first, created = store.merge_or_store(make_memory(id="a", confidence=0.6))
    assert created is True

    second, created_again = store.merge_or_store(
        make_memory(id="b", confidence=0.9, evidence=["extra evidence"])
    )
    assert created_again is False
    assert second.id == first.id  # merged into the original row
    assert second.occurrence_count == 2
    assert second.confidence == 0.9
    assert "extra evidence" in second.evidence
    assert store.count() == 1


def test_merge_refreshes_a_discredited_memory(store: MemoryStore) -> None:
    store.save(make_memory(id="a", status=MemoryStatus.INCORRECT, prevention="old prevention"))
    merged, created = store.merge_or_store(make_memory(id="b", prevention="new prevention"))
    assert created is False
    assert merged.status is MemoryStatus.ACTIVE
    assert merged.prevention == "new prevention"


def test_record_use_updates_counters(store: MemoryStore) -> None:
    store.save(make_memory(id="a"))
    store.record_use("a", success=True)
    store.record_use("a", success=False)

    loaded = store.get("a")
    assert loaded is not None
    assert loaded.use_count == 2
    assert loaded.success_count == 1
    assert loaded.failure_count == 1
    assert loaded.last_used_at is not None


def test_feedback_updates_counts_and_status(store: MemoryStore) -> None:
    store.save(make_memory(id="a"))
    updated, feedback = store.add_feedback("a", FeedbackVerdict.USEFUL)
    assert updated is not None and feedback.verdict is FeedbackVerdict.USEFUL
    assert updated.helpful_count == 1

    store.add_feedback("a", FeedbackVerdict.UNHELPFUL)
    store.add_feedback("a", FeedbackVerdict.OUTDATED)
    reloaded = store.get("a")
    assert reloaded is not None
    assert reloaded.unhelpful_count == 1
    assert reloaded.status is MemoryStatus.OUTDATED

    store.add_feedback("a", FeedbackVerdict.INCORRECT)
    assert store.get("a").status is MemoryStatus.INCORRECT  # type: ignore[union-attr]

    assert len(store.list_feedback("a")) == 4


def test_feedback_for_missing_memory_is_recorded_but_returns_none(store: MemoryStore) -> None:
    memory, feedback = store.add_feedback("ghost", FeedbackVerdict.USEFUL)
    assert memory is None
    assert feedback.memory_id == "ghost"


def test_set_status_and_delete(store: MemoryStore) -> None:
    store.save(make_memory(id="a"))
    updated = store.set_status("a", MemoryStatus.ARCHIVED)
    assert updated is not None and updated.status is MemoryStatus.ARCHIVED
    assert store.count(include_inactive=False) == 0

    assert store.delete("a") is True
    assert store.delete("a") is False
    assert store.count() == 0


def test_list_filters(store: MemoryStore) -> None:
    store.save(make_memory(id="a", task_type="build_project"))
    store.save(make_memory(id="b", task_type="deploy_service"))
    store.save(make_memory(id="c", status=MemoryStatus.ARCHIVED))

    assert {m.id for m in store.list()} == {"a", "b", "c"}
    assert {m.id for m in store.list(include_inactive=False)} == {"a", "b"}
    assert {m.id for m in store.list(task_type="build_project")} == {"a"}
    assert [m.id for m in store.list(limit=1)] == [m.id for m in store.list()][:1]
    assert store.count(status=MemoryStatus.ARCHIVED) == 1
    assert store.count(task_type="build_project") == 1
    assert store.count(include_inactive=False) == 2


def test_stats_aggregate(store: MemoryStore) -> None:
    store.save(make_memory(id="a", occurrence_count=3))
    store.save(make_memory(id="b", status=MemoryStatus.ARCHIVED))
    store.record_use("a", success=True)

    stats = store.stats()
    assert stats["total_memories"] == 2
    assert stats["repeated_failure_patterns"] == 1
    assert stats["times_applied"] == 1
    assert stats["prevention_successes"] == 1
    assert stats["by_status"]["archived"] == 1


def test_effective_confidence_penalised_by_status_and_failures() -> None:
    healthy = make_memory(confidence=0.8, success_count=5)
    failing = make_memory(confidence=0.8, failure_count=20)
    incorrect = make_memory(confidence=0.8, status=MemoryStatus.INCORRECT)

    assert healthy.effective_confidence > failing.effective_confidence
    assert incorrect.effective_confidence < 0.1


def test_blank_required_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        make_memory(task="   ")
    with pytest.raises(ValidationError):
        make_memory(prevention="")


def test_normalize_and_dedup_key_are_deterministic() -> None:
    assert normalize_text("  Deploy   The APP!! ") == "deploy the app"
    first = dedup_key("deploy_service", "deploy", "missing_configuration", "missing DATABASE_URL")
    second = dedup_key("deploy_service", "deploy", "missing_configuration", "missing database url")
    assert first == second


def test_failure_memory_is_immutable_for_validators() -> None:
    memory = FailureMemory.model_validate(
        {
            "id": "x",
            "task": "task",
            "failure": "fail",
            "root_cause": "cause",
            "lesson": "lesson",
            "prevention": "prevention",
        }
    )
    assert memory.status is MemoryStatus.ACTIVE
    assert memory.failure_category.value == "unknown"
