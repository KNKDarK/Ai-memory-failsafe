"""Tests for the deterministic memory lifecycle (stale/obsolete/expired)."""

from __future__ import annotations

from datetime import timedelta

from backend.domain import MemoryStatus, utcnow
from backend.memory.lifecycle import (
    LifecycleLabel,
    LifecyclePolicy,
    age_days,
    apply_lifecycle,
    classify,
    lifecycle_report,
    plan_transitions,
    policy_from_settings,
)
from backend.memory.store import MemoryStore
from backend.tests.factories import make_memory


def _aged(*, created_days: float = 0.0, used_days: float | None = None, **kwargs):
    now = utcnow()
    extra = {"created_at": now - timedelta(days=created_days)}
    if used_days is not None:
        extra["last_used_at"] = now - timedelta(days=used_days)
    return make_memory(**{**kwargs, **extra})


def test_fresh_memory_is_fresh() -> None:
    label, reason = classify(make_memory())
    assert label is LifecycleLabel.FRESH
    assert reason


def test_stale_by_age() -> None:
    label, _ = classify(_aged(created_days=40))
    assert label is LifecycleLabel.STALE


def test_stale_uses_last_used_at() -> None:
    label, _ = classify(_aged(created_days=0, used_days=45))
    assert label is LifecycleLabel.STALE


def test_expired_past_retire_horizon() -> None:
    label, _ = classify(_aged(created_days=100))
    assert label is LifecycleLabel.EXPIRED


def test_obsolete_by_failure_ratio() -> None:
    memory = make_memory(use_count=4, success_count=1, failure_count=3)
    label, reason = classify(memory)
    assert label is LifecycleLabel.OBSOLETE
    assert "failed 3/4" in reason


def test_obsolete_when_marked_incorrect() -> None:
    memory = make_memory(status=MemoryStatus.INCORRECT)
    label, _ = classify(memory)
    assert label is LifecycleLabel.OBSOLETE


def test_archived_is_expired() -> None:
    memory = make_memory(status=MemoryStatus.ARCHIVED)
    label, _ = classify(memory)
    assert label is LifecycleLabel.EXPIRED


def test_age_days_uses_reference_time() -> None:
    now = utcnow()
    memory = make_memory(created_at=now - timedelta(days=7))
    assert age_days(memory, now=now) == 7.0


def test_plan_transitions_are_monotonic() -> None:
    now = utcnow()
    fresh = make_memory(id="fresh", created_at=now)
    stale = make_memory(id="stale", created_at=now - timedelta(days=40))
    archived = make_memory(id="archived", status=MemoryStatus.ARCHIVED)
    transitions = plan_transitions([fresh, stale, archived], now=now, policy=LifecyclePolicy())

    by_id = {t["id"]: t for t in transitions}
    assert "fresh" not in by_id
    assert by_id["stale"]["to"] == "outdated"
    assert by_id["stale"]["from"] == "active"
    # An archived memory is terminal; it is never moved backwards.
    assert "archived" not in by_id


def test_lifecycle_report_counts() -> None:
    now = utcnow()
    memories = [
        make_memory(id="fresh", created_at=now),
        make_memory(id="stale", created_at=now - timedelta(days=40)),
        make_memory(id="expired", created_at=now - timedelta(days=120)),
    ]
    report = lifecycle_report(memories, now=now, policy=LifecyclePolicy())
    assert report["counts"]["fresh"] == 1
    assert report["stale"] == 1
    assert report["expired"] == 1
    assert report["total"] == 3
    assert len(report["planned_transitions"]) == 2


def test_apply_lifecycle_updates_store() -> None:
    now = utcnow()
    store = MemoryStore(":memory:")
    store.save(make_memory(id="stale", created_at=now - timedelta(days=40)))
    store.save(make_memory(id="fresh", created_at=now))

    result = apply_lifecycle(store, now=now, policy=LifecyclePolicy())
    assert result["applied"] == 1
    assert store.get("stale").status is MemoryStatus.OUTDATED
    assert store.get("fresh").status is MemoryStatus.ACTIVE


def test_policy_from_settings_reads_attributes() -> None:
    class _Settings:
        lifecycle_stale_after_days = 10.0
        lifecycle_retire_after_days = 20.0
        lifecycle_obsolete_failure_ratio = 0.25
        lifecycle_min_uses_for_obsolete = 2

    policy = policy_from_settings(_Settings())
    assert policy == LifecyclePolicy(10.0, 20.0, 0.25, 2)
