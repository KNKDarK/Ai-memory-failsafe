"use client";

import type { RetrievalResult } from "@/lib/types";
import { num, shortId } from "@/lib/format";

import { Badge, Bar } from "./ui";

export function RetrievalResultCard({ result }: { result: RetrievalResult }) {
  const { memory, components } = result;
  return (
    <div className="memory-card">
      <div className="memory-head">
        <div className="grow">
          <div className="memory-title">{memory.lesson}</div>
          <div className="small faint mono">
            {memory.task_type} · {memory.action || "—"} · {memory.failure_category}
          </div>
        </div>
        <Badge tone={result.selected ? "success" : "muted"}>
          {result.selected ? "selected" : "not selected"}
        </Badge>
      </div>

      <div className="row" style={{ gap: 14 }}>
        <span className="small faint">
          score <b className="mono">{num(result.score, 3)}</b>
        </span>
        <span className="small faint">
          similarity <b className="mono">{num(result.similarity, 3)}</b>
        </span>
        <span className="small faint">
          effective confidence{" "}
          <b className="mono">{num(memory.effective_confidence, 3)}</b>
        </span>
        <span className="small faint">
          status <b className="mono">{memory.status}</b>
        </span>
        <span className="tiny faint mono">id {shortId(memory.id)}</span>
      </div>

      <div className="score-grid">
        <div className="score-cell">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <span className="faint">similarity</span>
            <span className="mono">{num(components.similarity, 3)}</span>
          </div>
          <Bar value={components.similarity} />
        </div>
        <div className="score-cell">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <span className="faint">confidence</span>
            <span className="mono">{num(components.confidence, 3)}</span>
          </div>
          <Bar value={components.confidence} />
        </div>
        <div className="score-cell">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <span className="faint">recency</span>
            <span className="mono">{num(components.recency, 3)}</span>
          </div>
          <Bar value={components.recency} />
        </div>
        <div className="score-cell">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <span className="faint">feedback</span>
            <span className="mono">{num(components.feedback, 3)}</span>
          </div>
          <Bar value={components.feedback} />
        </div>
      </div>

      <div className="memory-text">
        <b>Prevention:</b> {memory.prevention}
      </div>

      {result.matched_terms.length > 0 && (
        <div className="pill-row">
          {result.matched_terms.map((term) => (
            <span key={term} className="badge tone-muted mono">
              {term}
            </span>
          ))}
        </div>
      )}

      {result.reason && <div className="small muted">{result.reason}</div>}
    </div>
  );
}
