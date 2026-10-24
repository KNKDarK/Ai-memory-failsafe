"use client";

import { Badge, Dot } from "@/components/ui";
import type { Tone } from "@/lib/format";
import type { MemoryAttributionLab } from "@/lib/types";

interface MemoryAttributionInspectorProps {
  memories: MemoryAttributionLab[];
}

function strategyTone(strategy: string): Tone {
  switch (strategy.toLowerCase()) {
    case "bm25":
      return "accent";
    case "tfidf":
      return "info";
    case "embedding":
      return "warn";
    case "hybrid":
      return "success";
    default:
      return "muted";
  }
}

function rejectionReasonTone(reason?: string | null): Tone {
  switch (reason) {
    case "contradiction_detected":
      return "danger";
    case "below_confidence_gate":
      return "warn";
    default:
      return "muted";
  }
}

function rejectionLabel(reason?: string | null): string {
  switch (reason) {
    case "contradiction_detected":
      return "Contradiction detected";
    case "below_confidence_gate":
      return "Below confidence gate";
    default:
      return reason ?? "";
  }
}

function verificationLabel(verified: boolean): string {
  return verified ? "Confirmed" : "Unverified";
}

function verificationTone(verified: boolean): Tone {
  return verified ? "success" : "warn";
}

/**
 * MemoryAttributionInspector — renders retrieved failure-memory lessons with:
 *   - confidence percentage bars
 *   - retrieval strategy badges
 *   - root-cause verification status (Confirmed / Unverified)
 *   - rejection reasons when a lesson was retrieved but not applied
 */
export function MemoryAttributionInspector({ memories }: MemoryAttributionInspectorProps) {
  if (!memories.length) return null;

  return (
    <div className="attribution-inspector">
      <h3 className="attribution-title">Memory Attribution</h3>
      <div className="attribution-list">
        {memories.map((m, idx) => (
          <div key={m.lesson_id || `item-${idx}`} className="attribution-card">
            {/* Header: lesson text + status badges */}
            <div className="attribution-header">
              <p className="attribution-lesson">{m.lesson_text}</p>
              <div className="attribution-badges">
                <Badge tone={strategyTone(m.retrieval_strategy)}>
                  {m.retrieval_strategy}
                </Badge>
                <Dot tone={verificationTone(m.is_root_cause_verified)} />
                <span className={`badge verification ${verificationTone(m.is_root_cause_verified)}`}>
                  {verificationLabel(m.is_root_cause_verified)}
                </span>
              </div>
            </div>

            {/* Confidence bar */}
            <div className="attribution-confidence">
              <div className="confidence-row">
                <span className="confidence-label">Confidence</span>
                <span className="confidence-value mono">{Math.round(m.confidence_score * 100)}%</span>
              </div>
              <div className="bar confidence-bar" title={`${m.confidence_score.toFixed(3)}`}>
                <div
                  className={`bar-fill ${m.confidence_score >= 0.7 ? "success" : m.confidence_score >= 0.4 ? "warn" : "danger"}`}
                  style={{ width: `${m.confidence_score * 100}%` }}
                />
              </div>
            </div>

            {/* Similarity score */}
            <div className="attribution-meta">
              <span className="meta-item faint">
                Similarity: {(m.similarity_score * 100).toFixed(1)}%
              </span>
              {m.retrieved && (
                <>
                  <span className={`meta-dot tone-${m.applied ? "success" : "warn"}`} />
                  <span className="meta-item">
                    {m.applied ? "Applied" : "Retrieved, not applied"}
                  </span>
                </>
              )}
            </div>

            {/* Rejection reason — shown when retrieved but not applied */}
            {!m.applied && m.retrieved && m.rejection_reason && (
              <div className="attribution-rejection">
                <Dot tone={rejectionReasonTone(m.rejection_reason)} />
                <Badge tone={rejectionReasonTone(m.rejection_reason)}>
                  {rejectionLabel(m.rejection_reason)}
                </Badge>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
