"use client";

import { useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { categoryLabel, pct, shortId } from "@/lib/format";
import type {
  ContradictionsResponse,
  FailureMemory,
  MemoryStats,
  MemoryStatus,
} from "@/lib/types";

import { MemoryTable } from "./MemoryTable";
import { Badge, Card, Empty, ErrorBanner, Spinner, Stat } from "./ui";

const STATUS_OPTIONS: Array<MemoryStatus | ""> = [
  "",
  "active",
  "outdated",
  "incorrect",
  "archived",
];

export default function MemoryPanel() {
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [contradictions, setContradictions] = useState<ContradictionsResponse | null>(
    null,
  );
  const [memories, setMemories] = useState<FailureMemory[]>([]);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState<MemoryStatus | "">("");
  const [taskTypeInput, setTaskTypeInput] = useState("");
  const [taskType, setTaskType] = useState("");
  const [includeInactive, setIncludeInactive] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [lifecycleBusy, setLifecycleBusy] = useState<"preview" | "apply" | null>(null);
  const [lifecycleNote, setLifecycleNote] = useState<string | null>(null);

  // Debounce the free-text task-type filter so typing does not fire a request
  // per keystroke.
  useEffect(() => {
    const timer = window.setTimeout(() => setTaskType(taskTypeInput), 300);
    return () => window.clearTimeout(timer);
  }, [taskTypeInput]);

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const [statsResult, contradictionsResult, listResult] = await Promise.all([
          api.memoryStats(),
          api.contradictions(),
          api.listMemories({
            status: status || undefined,
            task_type: taskType.trim() || undefined,
            include_inactive: includeInactive,
            limit: 200,
          }),
        ]);
        if (!active) return;
        setStats(statsResult);
        setContradictions(contradictionsResult);
        setMemories(listResult.items);
        setTotal(listResult.total);
        setError(null);
      } catch (err) {
        if (active) setError(err instanceof ApiError ? err.message : String(err));
      } finally {
        if (active) setLoading(false);
      }
    };
    void load();
    return () => {
      active = false;
    };
  }, [status, taskType, includeInactive, reloadKey]);

  function refresh() {
    setLoading(true);
    setReloadKey((key) => key + 1);
  }

  function replaceMemory(updated: FailureMemory) {
    setMemories((prev) => prev.map((m) => (m.id === updated.id ? updated : m)));
  }

  function dropMemory(id: string) {
    setMemories((prev) => prev.filter((m) => m.id !== id));
    setTotal((t) => Math.max(0, t - 1));
  }

  async function previewLifecycle() {
    setLifecycleBusy("preview");
    try {
      const lifecycle = await api.lifecycle();
      setLifecycleNote(
        `Dry run: ${lifecycle.planned_transitions.length} transition(s) would apply — ` +
          `${lifecycle.counts.fresh} fresh, ${lifecycle.stale} stale, ` +
          `${lifecycle.obsolete} obsolete, ${lifecycle.expired} expired.`,
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setLifecycleBusy(null);
    }
  }

  async function applyLifecycle() {
    setLifecycleBusy("apply");
    try {
      const result = await api.applyLifecycle();
      setLifecycleNote(`Applied ${result.applied} transition(s).`);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setLifecycleBusy(null);
    }
  }

  return (
    <div className="stack">
      {stats && (
        <div className="grid grid-4">
          <Stat label="Total memories" value={stats.total_memories} />
          <Stat
            label="Repeated failure patterns"
            value={stats.repeated_failure_patterns}
            hint={`${stats.total_occurrences} total occurrences`}
          />
          <Stat
            label="Times applied"
            value={stats.times_applied}
            hint={`${stats.prevention_successes} helpful · ${stats.prevention_failures} unhelpful`}
          />
          <Stat
            label="Prevention success rate"
            value={pct(stats.prevention_success_rate)}
            tone={
              stats.prevention_success_rate == null
                ? undefined
                : stats.prevention_success_rate >= 0.5
                  ? "success"
                  : "warn"
            }
          />
        </div>
      )}

      {contradictions && contradictions.count > 0 && (
        <Card
          title={`Contradictions (${contradictions.count})`}
          subtitle="Memories that give conflicting prevention advice for the same task type and action."
        >
          <div className="stack">
            {contradictions.conflicts.map((conflict) => (
              <div className="callout" key={`${conflict.task_type}-${conflict.action}`}>
                <div className="small faint mono">
                  {conflict.task_type} · {conflict.action}
                </div>
                <ul className="evidence">
                  {conflict.memories.map((item) => (
                    <li key={item.id}>
                      <span className="mono small">{shortId(item.id)}</span> —{" "}
                      {item.prevention} (trust {item.effective_confidence.toFixed(3)}
                      {item.id === conflict.preferred_id ? ", preferred" : ""})
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </Card>
      )}

      {stats?.lifecycle && (
        <Card
          title="Memory lifecycle"
          subtitle={`Stale after ${stats.lifecycle.policy.stale_after_days}d, retired after ${stats.lifecycle.policy.retire_after_days}d. Transitions are monotonic (active → outdated → incorrect → archived); preview is a dry run and never writes.`}
          actions={
            <div className="row">
              <button
                className="btn small"
                onClick={previewLifecycle}
                disabled={lifecycleBusy !== null}
              >
                {lifecycleBusy === "preview" ? <Spinner /> : "🔍"} Preview
              </button>
              <button
                className="btn small primary"
                onClick={applyLifecycle}
                disabled={lifecycleBusy !== null}
              >
                {lifecycleBusy === "apply" ? <Spinner /> : "▶"} Apply
              </button>
            </div>
          }
        >
          <div className="pill-row">
            <Badge tone="success">fresh: {stats.lifecycle.counts.fresh}</Badge>
            <Badge tone="warn">stale: {stats.lifecycle.counts.stale}</Badge>
            <Badge tone="danger">obsolete: {stats.lifecycle.counts.obsolete}</Badge>
            <Badge tone="muted">expired: {stats.lifecycle.counts.expired}</Badge>
          </div>
          {lifecycleNote && (
            <div className="callout small" style={{ marginTop: 12 }}>
              {lifecycleNote}
            </div>
          )}
        </Card>
      )}

      <Card
        title="Memory Bank"
        subtitle="Every stored failure lesson: the failure, its extracted root cause, and the learned prevention strategy. Expand a row for trust, usage counters, and feedback."
        actions={
          <div className="row">
            <span className="small faint">{total} total</span>
            <button className="btn small" onClick={refresh} disabled={loading}>
              {loading ? <Spinner /> : "⟳"} Refresh
            </button>
          </div>
        }
      >
        <div className="field-row" style={{ marginBottom: 16 }}>
          <div className="field" style={{ maxWidth: 180 }}>
            <label htmlFor="filter-status">Status</label>
            <select
              id="filter-status"
              value={status}
              onChange={(event) => setStatus(event.target.value as MemoryStatus | "")}
            >
              {STATUS_OPTIONS.map((option) => (
                <option key={option || "all"} value={option}>
                  {option || "all"}
                </option>
              ))}
            </select>
          </div>
          <div className="field" style={{ maxWidth: 240 }}>
            <label htmlFor="filter-task-type">Task type</label>
            <input
              id="filter-task-type"
              value={taskTypeInput}
              onChange={(event) => setTaskTypeInput(event.target.value)}
              placeholder="e.g. deploy_service"
            />
          </div>
          <div className="field" style={{ flex: "0 0 auto" }}>
            <label htmlFor="filter-inactive">Include inactive</label>
            <select
              id="filter-inactive"
              value={includeInactive ? "yes" : "no"}
              onChange={(event) => setIncludeInactive(event.target.value === "yes")}
            >
              <option value="yes">yes</option>
              <option value="no">no</option>
            </select>
          </div>
        </div>

        {error && <ErrorBanner message={error} />}

        {loading ? (
          <div className="row">
            <Spinner /> <span className="muted">Loading memories…</span>
          </div>
        ) : memories.length === 0 ? (
          <Empty>
            No memories match these filters. Run a failing task in memory mode to learn
            one.
          </Empty>
        ) : (
          <MemoryTable
            memories={memories}
            onChanged={replaceMemory}
            onDeleted={dropMemory}
          />
        )}
      </Card>

      {stats && Object.keys(stats.by_category).length > 0 && (
        <Card title="Memories by failure category">
          <div className="pill-row">
            {Object.entries(stats.by_category).map(([category, count]) => (
              <span key={category} className="badge tone-muted">
                {categoryLabel(category)}: <b>{count}</b>
              </span>
            ))}
          </div>
          <div className="sep" />
          <div className="pill-row">
            {Object.entries(stats.by_status).map(([key, count]) => (
              <Badge key={key} tone="info">
                {key}: {count}
              </Badge>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
