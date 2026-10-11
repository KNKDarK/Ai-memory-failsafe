"use client";

import { useState } from "react";

import { api, ApiError } from "@/lib/api";
import { categoryLabel, causeLabel, causeTone, formatDate, pct, statusTone } from "@/lib/format";
import type {
  FailureMemory,
  FeedbackVerdict,
  MemoryFeedback,
  MemoryStatus,
} from "@/lib/types";

import { Badge, Bar, JsonBlock, Spinner } from "./ui";

const VERDICTS: FeedbackVerdict[] = ["useful", "unhelpful", "outdated", "incorrect"];
const STATUSES: MemoryStatus[] = ["active", "outdated", "incorrect", "archived"];

export function MemoryCard({
  memory,
  onChanged,
  onDeleted,
}: {
  memory: FailureMemory;
  onChanged: (updated: FailureMemory) => void;
  onDeleted: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [feedback, setFeedback] = useState<MemoryFeedback[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function loadDetail() {
    if (open) {
      setOpen(false);
      return;
    }
    setOpen(true);
    if (feedback !== null) return;
    try {
      const detail = await api.getMemory(memory.id);
      setFeedback(detail.feedback);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }

  async function giveFeedback(verdict: FeedbackVerdict) {
    setBusy(`verdict:${verdict}`);
    setError(null);
    try {
      const result = await api.addFeedback(memory.id, verdict);
      onChanged(result.memory);
      setFeedback((prev) => [result.feedback, ...(prev ?? [])]);
      setOpen(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  async function changeStatus(status: MemoryStatus) {
    setBusy(`status:${status}`);
    setError(null);
    try {
      const result = await api.setStatus(memory.id, status);
      onChanged(result.memory);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }

  async function remove() {
    if (typeof window !== "undefined" && !window.confirm("Delete this memory permanently?")) {
      return;
    }
    setBusy("delete");
    setError(null);
    try {
      await api.deleteMemory(memory.id);
      onDeleted(memory.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
      setBusy(null);
    }
  }

  return (
    <div className="memory-card">
      <div className="memory-head">
        <div className="grow">
          <div className="memory-title">{memory.lesson}</div>
          <div className="small faint mono">
            {memory.task_type} · {memory.action || "—"} ·{" "}
            {categoryLabel(memory.failure_category)}
          </div>
        </div>
        <div className="row" style={{ gap: 6 }}>
          <Badge tone={statusTone(memory.status)}>{memory.status}</Badge>
          <Badge tone={causeTone(memory.cause_status)}>
            {causeLabel(memory.cause_status)}
          </Badge>
          <Badge tone="muted">{pct(memory.effective_confidence, 0)} trust</Badge>
        </div>
      </div>

      <div className="score-grid">
        <div className="score-cell">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <span className="faint">effective confidence</span>
            <span className="mono">{memory.effective_confidence.toFixed(3)}</span>
          </div>
          <Bar value={memory.effective_confidence} />
        </div>
        <div className="score-cell">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <span className="faint">stored confidence</span>
            <span className="mono">{memory.confidence.toFixed(3)}</span>
          </div>
          <Bar value={memory.confidence} />
        </div>
      </div>

      <div className="memory-text">
        <b>Failure:</b> {memory.failure}
      </div>
      <div className="memory-text">
        <b>Root cause:</b> {memory.root_cause}
      </div>
      <div className="memory-text">
        <b>Prevention:</b> {memory.prevention}
      </div>

      {memory.prevention_actions.length > 0 && (
        <div className="pill-row">
          {memory.prevention_actions.map((action) => (
            <span key={action} className="badge tone-accent mono">
              {action}
            </span>
          ))}
        </div>
      )}

      <div className="row" style={{ gap: 12, fontSize: 11.5 }}>
        <span className="faint">
          occurrences <b className="mono">{memory.occurrence_count}</b>
        </span>
        <span className="faint">
          applied <b className="mono">{memory.uses}</b>
        </span>
        <span className="faint">
          success rate <b className="mono">{pct(memory.success_rate)}</b>
        </span>
        <span className="faint">
          helped <b className="mono">{memory.success_count}</b>
        </span>
        <span className="faint">
          failed <b className="mono">{memory.failure_count}</b>
        </span>
        <span className="faint">created {formatDate(memory.created_at)}</span>
      </div>

      <div className="memory-actions">
        <span className="small faint">Mark:</span>
        {VERDICTS.map((verdict) => (
          <button
            key={verdict}
            className="btn small"
            onClick={() => giveFeedback(verdict)}
            disabled={busy !== null}
          >
            {busy === `verdict:${verdict}` ? <Spinner /> : verdict}
          </button>
        ))}
        <span className="small faint" style={{ marginLeft: 6 }}>
          Status:
        </span>
        <select
          aria-label="memory status"
          value={memory.status}
          onChange={(event) => changeStatus(event.target.value as MemoryStatus)}
          disabled={busy !== null}
          style={{ width: "auto", padding: "4px 8px", fontSize: 12 }}
        >
          {STATUSES.map((status) => (
            <option key={status} value={status}>
              {status}
            </option>
          ))}
        </select>
        <button className="btn ghost small" onClick={loadDetail}>
          {open ? "▾" : "▸"} Feedback history
        </button>
        <button
          className="btn danger small"
          onClick={remove}
          disabled={busy !== null}
          style={{ marginLeft: "auto" }}
        >
          {busy === "delete" ? <Spinner /> : "Delete"}
        </button>
      </div>

      {error && (
        <div className="small" style={{ color: "var(--danger)" }}>
          {error}
        </div>
      )}

      {open && (
        <div className="callout">
          {feedback === null ? (
            <div className="row">
              <Spinner /> <span className="muted">Loading feedback…</span>
            </div>
          ) : feedback.length === 0 ? (
            <span className="muted">No feedback recorded yet.</span>
          ) : (
            <ul className="evidence">
              {feedback.map((item) => (
                <li key={item.id}>
                  <b>{item.verdict}</b> · {formatDate(item.created_at)}
                  {item.comment ? ` — ${item.comment}` : ""}
                </li>
              ))}
            </ul>
          )}
          <div style={{ marginTop: 10 }}>
            <JsonBlock data={memory} label="Memory JSON" />
          </div>
        </div>
      )}
    </div>
  );
}
