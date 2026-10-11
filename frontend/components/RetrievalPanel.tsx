"use client";

import { useState } from "react";

import { api, ApiError } from "@/lib/api";
import { shortId } from "@/lib/format";
import type { RetrievalPreviewResponse } from "@/lib/types";

import { RetrievalResultCard } from "./RetrievalResultCard";
import { Card, Empty, ErrorBanner, Spinner } from "./ui";

export default function RetrievalPanel() {
  const [task, setTask] = useState("Deploy the application");
  const [limit, setLimit] = useState(5);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RetrievalPreviewResponse | null>(null);

  async function preview() {
    if (!task.trim()) {
      setError("Enter a task to preview retrieval for.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const response = await api.previewRetrieval({ task: task.trim(), limit });
      setResult(response);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <Card
        title="Retrieval preview"
        subtitle="Ask what the agent would retrieve for a task without executing anything. Scores combine text similarity, confidence, recency, and feedback; a candidate is only selected if it clears both the score floor and the text-similarity floor."
      >
        <div className="stack">
          <div className="field">
            <label htmlFor="preview-task">Task</label>
            <input
              id="preview-task"
              value={task}
              onChange={(event) => setTask(event.target.value)}
              placeholder="e.g. Build the project"
            />
          </div>
          <div className="field-row">
            <div className="field" style={{ maxWidth: 180 }}>
              <label htmlFor="preview-limit">Candidate limit</label>
              <input
                id="preview-limit"
                type="number"
                min={1}
                max={50}
                value={limit}
                onChange={(event) =>
                  setLimit(Math.max(1, Math.min(50, Number(event.target.value) || 1)))
                }
              />
            </div>
            <div className="field" style={{ flex: "0 0 auto" }}>
              <label>&nbsp;</label>
              <button className="btn primary" onClick={preview} disabled={busy}>
                {busy ? <Spinner /> : "⌕"} Preview retrieval
              </button>
            </div>
          </div>
        </div>
      </Card>

      {error && <ErrorBanner message={error} />}

      {result && (
        <Card
          title="Retrieval results"
          subtitle={
            result.retrieval_mode
              ? `retrieval mode: ${result.retrieval_mode}`
              : "no memories in scope"
          }
          actions={
            <div className="row">
              <span className="small faint">
                {result.candidate_count} candidate(s)
              </span>
              <span className="small faint">
                {result.selected_ids.length} selected
              </span>
            </div>
          }
        >
          {result.results.length === 0 ? (
            <Empty>
              No memories exist yet for this store. Run a failing task first so a lesson
              can be learned and stored.
            </Empty>
          ) : (
            <>
              {result.selected_ids.length > 0 && (
                <div className="small faint" style={{ marginBottom: 12 }}>
                  Selected:{" "}
                  {result.selected_ids.map((id) => (
                    <span
                      key={id}
                      className="badge tone-success mono"
                      style={{ marginRight: 6 }}
                    >
                      {shortId(id)}
                    </span>
                  ))}
                </div>
              )}
              <div className="stack">
                {result.results.map((item) => (
                  <RetrievalResultCard key={item.memory.id} result={item} />
                ))}
              </div>
            </>
          )}
        </Card>
      )}
    </div>
  );
}
