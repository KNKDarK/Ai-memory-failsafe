"""Deterministic memory lifecycle: freshness, staleness, obsolescence, retirement.

The lifecycle is a *derived* view over a memory's stored state plus the clock.
It never mutates anything on its own: :func:`classify` labels a memory,
:func:`plan_transitions` returns the status changes that *would* happen (a dry
run), and :func:`apply_lifecycle` is the only function that writes.

Rules (all purely mechanical and reproducible):

* **fresh**   - recently used/created and still trustworthy.
* **stale**   - not used for ``stale_after_days`` (or already ``outdated``).
* **obsolete** - has been applied at least ``min_uses_for_obsolete`` times and
  failed at least ``obsolete_failure_ratio`` of them, or is marked ``incorrect``.
* **expired** - not used for ``retire_after_days`` (or already ``archived``).

Transitions are monotonic (``active -> outdated -> incorrect -> archived``);
a memory is never silently resurrected.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum

from backend.domain import MemoryStatus, ensure_utc, utcnow
from backend.memory.models import FailureMemory
from backend.memory.store import MemoryStore


@dataclass(frozen=True)
class LifecyclePolicy:
    """Thresholds for the deterministic lifecycle. All values are adjustable."""

    stale_after_days: float = 30.0
    retire_after_days: float = 90.0
    obsolete_failure_ratio: float = 0.5
    min_uses_for_obsolete: int = 3


class LifecycleLabel(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    OBSOLETE = "obsolete"
    EXPIRED = "expired"


_STATUS_RANK: dict[MemoryStatus, int] = {
    MemoryStatus.ACTIVE: 0,
    MemoryStatus.OUTDATED: 1,
    MemoryStatus.INCORRECT: 2,
    MemoryStatus.ARCHIVED: 3,
}

_TARGET_STATUS: dict[LifecycleLabel, MemoryStatus] = {
    LifecycleLabel.STALE: MemoryStatus.OUTDATED,
    LifecycleLabel.OBSOLETE: MemoryStatus.INCORRECT,
    LifecycleLabel.EXPIRED: MemoryStatus.ARCHIVED,
}


def age_days(memory: FailureMemory, *, now: datetime | None = None) -> float:
    """Days since the memory was last used (falling back to creation)."""
    now = ensure_utc(now or utcnow())
    reference = ensure_utc(memory.last_used_at or memory.created_at)
    return max(0.0, (now - reference).total_seconds() / 86400.0)


def classify(
    memory: FailureMemory,
    *,
    now: datetime | None = None,
    policy: LifecyclePolicy | None = None,
) -> tuple[LifecycleLabel, str]:
    """Label a single memory and explain why (never mutates)."""
    policy = policy or LifecyclePolicy()
    if memory.status is MemoryStatus.ARCHIVED:
        return LifecycleLabel.EXPIRED, "already archived (retired)"

    uses = memory.use_count
    if (
        uses >= policy.min_uses_for_obsolete
        and uses > 0
        and memory.failure_count / uses >= policy.obsolete_failure_ratio
        and memory.failure_count > memory.success_count
    ):
        ratio = memory.failure_count / uses
        return (
            LifecycleLabel.OBSOLETE,
            f"failed {memory.failure_count}/{uses} applications ({ratio:.0%}), "
            "outcomes outweigh successes",
        )
    if memory.status is MemoryStatus.INCORRECT:
        return LifecycleLabel.OBSOLETE, "marked incorrect by feedback"

    age = age_days(memory, now=now)
    if age >= policy.retire_after_days:
        return (
            LifecycleLabel.EXPIRED,
            f"unused for {age:.0f}d (retire threshold {policy.retire_after_days:.0f}d)",
        )
    if memory.status is MemoryStatus.OUTDATED or age >= policy.stale_after_days:
        return (
            LifecycleLabel.STALE,
            f"unused for {age:.0f}d (stale threshold {policy.stale_after_days:.0f}d)",
        )
    return LifecycleLabel.FRESH, f"used {age:.0f}d ago and still trustworthy"


def plan_transitions(
    memories: list[FailureMemory],
    *,
    now: datetime | None = None,
    policy: LifecyclePolicy | None = None,
) -> list[dict[str, object]]:
    """Return the status changes the policy would apply (dry run, monotonic)."""
    policy = policy or LifecyclePolicy()
    transitions: list[dict[str, object]] = []
    for memory in memories:
        label, reason = classify(memory, now=now, policy=policy)
        target = _TARGET_STATUS.get(label)
        if target is None:
            continue
        if _STATUS_RANK[target] <= _STATUS_RANK[memory.status]:
            continue
        transitions.append(
            {
                "id": memory.id,
                "label": label.value,
                "from": memory.status.value,
                "to": target.value,
                "reason": reason,
            }
        )
    return transitions


def lifecycle_report(
    memories: list[FailureMemory],
    *,
    now: datetime | None = None,
    policy: LifecyclePolicy | None = None,
) -> dict[str, object]:
    """Counts + per-memory labels + planned transitions for a memory set."""
    now = ensure_utc(now or utcnow())
    policy = policy or LifecyclePolicy()
    counts = {label.value: 0 for label in LifecycleLabel}
    items: list[dict[str, object]] = []
    for memory in memories:
        label, reason = classify(memory, now=now, policy=policy)
        counts[label.value] += 1
        items.append(
            {
                "id": memory.id,
                "status": memory.status.value,
                "label": label.value,
                "age_days": round(age_days(memory, now=now), 1),
                "reason": reason,
            }
        )
    return {
        "policy": asdict(policy),
        "counts": counts,
        "total": len(memories),
        "active": sum(1 for m in memories if m.status is MemoryStatus.ACTIVE),
        "stale": counts[LifecycleLabel.STALE.value],
        "obsolete": counts[LifecycleLabel.OBSOLETE.value],
        "expired": counts[LifecycleLabel.EXPIRED.value],
        "planned_transitions": plan_transitions(memories, now=now, policy=policy),
        "items": items,
    }


def apply_lifecycle(
    store: MemoryStore,
    *,
    now: datetime | None = None,
    policy: LifecyclePolicy | None = None,
) -> dict[str, object]:
    """Apply planned transitions to the store and return a summary + fresh report."""
    now = ensure_utc(now or utcnow())
    policy = policy or LifecyclePolicy()
    memories = store.list(include_inactive=True)
    transitions = plan_transitions(memories, now=now, policy=policy)
    for transition in transitions:
        store.set_status(str(transition["id"]), MemoryStatus(str(transition["to"])))
    return {
        "applied": len(transitions),
        "transitions": transitions,
        "report": lifecycle_report(store.list(include_inactive=True), now=now, policy=policy),
    }


def policy_from_settings(settings) -> LifecyclePolicy:
    """Build a :class:`LifecyclePolicy` from a settings object (duck-typed)."""
    return LifecyclePolicy(
        stale_after_days=getattr(settings, "lifecycle_stale_after_days", 30.0),
        retire_after_days=getattr(settings, "lifecycle_retire_after_days", 90.0),
        obsolete_failure_ratio=getattr(settings, "lifecycle_obsolete_failure_ratio", 0.5),
        min_uses_for_obsolete=getattr(settings, "lifecycle_min_uses_for_obsolete", 3),
    )
