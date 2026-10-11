"""SQLite-backed persistent storage for failure memories.

The store is deliberately dependency-free (stdlib ``sqlite3``) and works with a
file path or ``:memory:``. Every row that leaves the database is re-validated
through the Pydantic model, so malformed or incomplete rows are skipped safely
instead of crashing the application.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import threading
import uuid
from collections.abc import Iterable

from pydantic import ValidationError

from backend.domain import FeedbackVerdict, MemoryStatus, utcnow
from backend.memory.models import SCHEMA_VERSION, FailureMemory, MemoryFeedback

logger = logging.getLogger("failure_memory.store")

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^a-z0-9 ]+")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS failure_memories (
    id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    task TEXT NOT NULL,
    task_type TEXT NOT NULL,
    action TEXT NOT NULL,
    failure TEXT NOT NULL,
    failure_category TEXT NOT NULL,
    root_cause TEXT NOT NULL,
    cause_status TEXT NOT NULL,
    evidence TEXT NOT NULL,
    lesson TEXT NOT NULL,
    prevention TEXT NOT NULL,
    prevention_actions TEXT NOT NULL,
    tags TEXT NOT NULL,
    confidence REAL NOT NULL,
    status TEXT NOT NULL,
    occurrence_count INTEGER NOT NULL DEFAULT 1,
    use_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    helpful_count INTEGER NOT NULL DEFAULT 0,
    unhelpful_count INTEGER NOT NULL DEFAULT 0,
    source_execution_id TEXT,
    dedup_key TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_used_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_memories_task_type ON failure_memories(task_type);
CREATE INDEX IF NOT EXISTS idx_memories_dedup ON failure_memories(dedup_key);
CREATE INDEX IF NOT EXISTS idx_memories_status ON failure_memories(status);

CREATE TABLE IF NOT EXISTS memory_feedback (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    verdict TEXT NOT NULL,
    comment TEXT NOT NULL DEFAULT '',
    execution_id TEXT,
    applied INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (memory_id) REFERENCES failure_memories(id)
);

CREATE INDEX IF NOT EXISTS idx_feedback_memory ON memory_feedback(memory_id);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def normalize_text(text: str) -> str:
    """Deterministic normalisation used for dedup keys and lexical matching."""
    lowered = (text or "").lower().strip()
    lowered = _PUNCT_RE.sub(" ", lowered)
    return _WS_RE.sub(" ", lowered).strip()


def dedup_key(task_type: str, action: str, failure_category: str, root_cause: str) -> str:
    canonical = "|".join(
        [
            normalize_text(task_type),
            normalize_text(action),
            normalize_text(failure_category),
            normalize_text(root_cause),
        ]
    )
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


class MemoryStore:
    """Thread-safe SQLite store for :class:`FailureMemory` rows."""

    def __init__(self, path: str = ":memory:") -> None:
        self.path = path or ":memory:"
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )
            self._conn.commit()

    # ------------------------------------------------------------------ #
    # Serialisation helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _json(value: Iterable[str]) -> str:
        return json.dumps(list(value), ensure_ascii=True)

    @staticmethod
    def _to_row(memory: FailureMemory) -> tuple:
        return (
            memory.id,
            memory.schema_version,
            memory.task,
            memory.task_type,
            memory.action,
            memory.failure,
            memory.failure_category.value,
            memory.root_cause,
            memory.cause_status.value,
            MemoryStore._json(memory.evidence),
            memory.lesson,
            memory.prevention,
            MemoryStore._json(memory.prevention_actions),
            MemoryStore._json(memory.tags),
            float(memory.confidence),
            memory.status.value,
            memory.occurrence_count,
            memory.use_count,
            memory.success_count,
            memory.failure_count,
            memory.helpful_count,
            memory.unhelpful_count,
            memory.source_execution_id,
            dedup_key(
                memory.task_type,
                memory.action,
                memory.failure_category.value,
                memory.root_cause,
            ),
            memory.created_at.isoformat(),
            memory.updated_at.isoformat(),
            memory.last_used_at.isoformat() if memory.last_used_at else None,
        )

    @staticmethod
    def _safe_json_list(raw: object) -> list[str]:
        if raw is None:
            return []
        if isinstance(raw, list | tuple):
            return [str(x) for x in raw]
        try:
            parsed = json.loads(str(raw))
        except (json.JSONDecodeError, TypeError):
            return []
        if isinstance(parsed, list):
            return [str(x) for x in parsed]
        return []

    @classmethod
    def _row_to_memory(cls, row: sqlite3.Row) -> FailureMemory | None:
        """Convert a DB row to a model, returning ``None`` when malformed."""
        data = dict(row)
        data.pop("dedup_key", None)
        data["evidence"] = cls._safe_json_list(data.get("evidence"))
        data["prevention_actions"] = cls._safe_json_list(data.get("prevention_actions"))
        data["tags"] = cls._safe_json_list(data.get("tags"))
        for nullable in ("last_used_at", "source_execution_id"):
            if data.get(nullable) in ("", None):
                data[nullable] = None
        try:
            return FailureMemory.model_validate(data)
        except ValidationError as exc:
            # Do not leak the row contents into logs; ids are enough to debug.
            logger.warning(
                "Skipping malformed memory row id=%s: %s",
                data.get("id", "<unknown>"),
                exc.error_count(),
            )
            return None

    # ------------------------------------------------------------------ #
    # Writes
    # ------------------------------------------------------------------ #
    def save(self, memory: FailureMemory) -> FailureMemory:
        """Insert or fully replace a memory row."""
        row = self._to_row(memory)
        columns = (
            "id, schema_version, task, task_type, action, failure, failure_category, "
            "root_cause, cause_status, evidence, lesson, prevention, prevention_actions, "
            "tags, confidence, status, occurrence_count, use_count, success_count, "
            "failure_count, helpful_count, unhelpful_count, source_execution_id, "
            "dedup_key, created_at, updated_at, last_used_at"
        )
        placeholders = ", ".join(["?"] * len(row))
        with self._lock:
            self._conn.execute(
                f"INSERT OR REPLACE INTO failure_memories ({columns}) VALUES ({placeholders})",
                row,
            )
            self._conn.commit()
        return memory

    def find_by_dedup(self, memory: FailureMemory) -> FailureMemory | None:
        key = dedup_key(
            memory.task_type, memory.action, memory.failure_category.value, memory.root_cause
        )
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM failure_memories WHERE dedup_key = ? LIMIT 1", (key,)
            ).fetchone()
        return self._row_to_memory(row) if row else None

    def merge_or_store(self, memory: FailureMemory) -> tuple[FailureMemory, bool]:
        """Store a memory, merging with an existing equivalent one if present.

        Merging increments the occurrence counter, unions evidence/tags, and
        keeps the highest confidence. It returns ``(memory, created)`` where
        ``created`` is False when an existing memory was updated.
        """
        existing = self.find_by_dedup(memory)
        if existing is None:
            return self.save(memory), True

        merged = existing.model_copy(
            update={
                "occurrence_count": existing.occurrence_count + 1,
                "evidence": _union(existing.evidence, memory.evidence),
                "tags": _union(existing.tags, memory.tags),
                "confidence": max(existing.confidence, memory.confidence),
                "cause_status": (
                    memory.cause_status
                    if memory.cause_status == existing.cause_status
                    else existing.cause_status
                ),
                "updated_at": utcnow(),
            }
        )
        # If the stored memory was discredited, refresh it from the new evidence.
        if existing.status in {MemoryStatus.INCORRECT, MemoryStatus.OUTDATED}:
            merged = merged.model_copy(
                update={
                    "lesson": memory.lesson,
                    "prevention": memory.prevention,
                    "prevention_actions": memory.prevention_actions,
                    "status": MemoryStatus.ACTIVE,
                }
            )
        return self.save(merged), False

    def record_use(
        self, memory_id: str, *, success: bool, applied: bool = True
    ) -> FailureMemory | None:
        """Update usage statistics after a memory was (or was not) applied."""
        memory = self.get(memory_id)
        if memory is None:
            return None
        updated = memory.model_copy(
            update={
                "use_count": memory.use_count + 1,
                "success_count": memory.success_count + (1 if success else 0),
                "failure_count": memory.failure_count + (0 if success else 1),
                "last_used_at": utcnow(),
                "updated_at": utcnow(),
            }
        )
        return self.save(updated)

    def add_feedback(
        self,
        memory_id: str,
        verdict: FeedbackVerdict,
        *,
        comment: str = "",
        execution_id: str | None = None,
        applied: bool = False,
    ) -> tuple[FailureMemory | None, MemoryFeedback]:
        """Attach feedback and update the memory's trust counters/status."""
        memory = self.get(memory_id)
        feedback = MemoryFeedback(
            id=uuid.uuid4().hex,
            memory_id=memory_id,
            verdict=verdict,
            comment=comment or "",
            execution_id=execution_id,
            applied=applied,
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO memory_feedback (id, memory_id, verdict, comment, execution_id, "
                "applied, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    feedback.id,
                    feedback.memory_id,
                    feedback.verdict.value,
                    feedback.comment,
                    feedback.execution_id,
                    1 if feedback.applied else 0,
                    feedback.created_at.isoformat(),
                ),
            )
            self._conn.commit()

        if memory is None:
            return None, feedback

        update: dict = {"updated_at": utcnow()}
        if verdict == FeedbackVerdict.USEFUL:
            update["helpful_count"] = memory.helpful_count + 1
        elif verdict == FeedbackVerdict.UNHELPFUL:
            update["unhelpful_count"] = memory.unhelpful_count + 1
        elif verdict == FeedbackVerdict.OUTDATED:
            update["status"] = MemoryStatus.OUTDATED
        elif verdict == FeedbackVerdict.INCORRECT:
            update["status"] = MemoryStatus.INCORRECT

        updated = memory.model_copy(update=update)
        return self.save(updated), feedback

    def set_status(self, memory_id: str, status: MemoryStatus) -> FailureMemory | None:
        memory = self.get(memory_id)
        if memory is None:
            return None
        return self.save(memory.model_copy(update={"status": status, "updated_at": utcnow()}))

    def delete(self, memory_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM failure_memories WHERE id = ?", (memory_id,))
            self._conn.execute("DELETE FROM memory_feedback WHERE memory_id = ?", (memory_id,))
            self._conn.commit()
        return cursor.rowcount > 0

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    def get(self, memory_id: str) -> FailureMemory | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM failure_memories WHERE id = ?", (memory_id,)
            ).fetchone()
        return self._row_to_memory(row) if row else None

    def list(
        self,
        *,
        status: MemoryStatus | None = None,
        task_type: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        include_inactive: bool = True,
    ) -> list[FailureMemory]:
        clauses: list[str] = []
        params: list[object] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        elif not include_inactive:
            clauses.append("status = ?")
            params.append(MemoryStatus.ACTIVE.value)
        if task_type:
            clauses.append("task_type = ?")
            params.append(task_type)
        query = "SELECT * FROM failure_memories"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY updated_at DESC"
        if limit is not None:
            query += " LIMIT ? OFFSET ?"
            params.extend([int(limit), int(offset)])
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        memories = [self._row_to_memory(row) for row in rows]
        return [m for m in memories if m is not None]

    def all_active(self) -> list[FailureMemory]:
        return self.list(status=MemoryStatus.ACTIVE, include_inactive=False)

    def list_feedback(self, memory_id: str) -> list[MemoryFeedback]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM memory_feedback WHERE memory_id = ? ORDER BY created_at DESC",
                (memory_id,),
            ).fetchall()
        feedback: list[MemoryFeedback] = []
        for row in rows:
            try:
                data = dict(row)
                data["applied"] = bool(data["applied"])
                feedback.append(MemoryFeedback.model_validate(data))
            except (ValidationError, KeyError) as exc:
                logger.warning("Skipping malformed feedback row: %s", type(exc).__name__)
        return feedback

    def count(
        self,
        *,
        status: MemoryStatus | None = None,
        task_type: str | None = None,
        include_inactive: bool = True,
    ) -> int:
        clauses: list[str] = []
        params: list[object] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        elif not include_inactive:
            clauses.append("status = ?")
            params.append(MemoryStatus.ACTIVE.value)
        if task_type:
            clauses.append("task_type = ?")
            params.append(task_type)
        query = "SELECT COUNT(*) AS n FROM failure_memories"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        with self._lock:
            row = self._conn.execute(query, params).fetchone()
        return int(row["n"]) if row else 0

    def stats(self) -> dict:
        """Aggregate counters for dashboards and the evaluation report."""
        memories = self.list()
        by_status: dict[str, int] = {}
        by_category: dict[str, int] = {}
        repeated = 0
        total_occurrences = 0
        for memory in memories:
            by_status[memory.status.value] = by_status.get(memory.status.value, 0) + 1
            by_category[memory.failure_category.value] = (
                by_category.get(memory.failure_category.value, 0) + 1
            )
            total_occurrences += memory.occurrence_count
            if memory.occurrence_count > 1:
                repeated += 1
        applied = sum(m.use_count for m in memories)
        successes = sum(m.success_count for m in memories)
        failures = sum(m.failure_count for m in memories)
        return {
            "total_memories": len(memories),
            "by_status": by_status,
            "by_category": by_category,
            "repeated_failure_patterns": repeated,
            "total_occurrences": total_occurrences,
            "times_applied": applied,
            "prevention_successes": successes,
            "prevention_failures": failures,
            "prevention_success_rate": (successes / applied) if applied else None,
        }

    def malformed_row_count(self) -> int:
        """Count rows that fail validation (used by integrity checks/tests)."""
        with self._lock:
            rows = self._conn.execute("SELECT * FROM failure_memories").fetchall()
        return sum(1 for row in rows if self._row_to_memory(row) is None)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> MemoryStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _union(a: Iterable[str], b: Iterable[str]) -> list[str]:
    out: list[str] = []
    for item in list(a) + list(b):
        text = str(item).strip()
        if text and text not in out:
            out.append(text)
    return out
