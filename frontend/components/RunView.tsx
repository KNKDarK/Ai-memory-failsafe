"use client";

import type { FailureAnalysis, Recommendation, TaskRun } from "@/lib/types";
import {
  categoryLabel,
  causeLabel,
  causeTone,
  formatDuration,
  outcomeLabel,
  outcomeTone,
  pct,
  shortId,
} from "@/lib/format";

import { Badge, JsonBlock } from "./ui";

function AnalysisCard({ analysis }: { analysis: FailureAnalysis }) {
  return (
    <div className="callout">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div className="row">
          <Badge tone="danger">{categoryLabel(analysis.failure_category)}</Badge>
          <Badge tone={causeTone(analysis.cause_status)}>
            {causeLabel(analysis.cause_status)}
          </Badge>
        </div>
        <span className="small faint mono">
          confidence {analysis.confidence.toFixed(2)} · {analysis.analyzer}
        </span>
      </div>
      <div className="sep" />
      <div className="memory-text">
        <b>Failure:</b> {analysis.failure}
      </div>
      <div className="memory-text">
        <b>Root cause:</b> {analysis.root_cause}
      </div>
      <div className="memory-text">
        <b>Lesson:</b> {analysis.lesson}
      </div>
      <div className="memory-text">
        <b>Prevention:</b> {analysis.prevention}
      </div>
      {analysis.prevention_actions.length > 0 && (
        <div className="pill-row" style={{ marginTop: 8 }}>
          {analysis.prevention_actions.map((action) => (
            <span key={action} className="badge tone-accent mono">
              {action}
            </span>
          ))}
        </div>
      )}
      {analysis.evidence.length > 0 && (
        <ul className="evidence">
          {analysis.evidence.map((item, index) => (
            <li key={`${item}-${index}`}>{item}</li>
          ))}
        </ul>
      )}
      {analysis.alternatives.length > 0 && (
        <>
          <div className="section-title" style={{ marginBottom: 6 }}>
            Alternative causes considered
          </div>
          <ul className="evidence">
            {analysis.alternatives.map((alt, index) => (
              <li key={`${alt.cause}-${index}`}>
                {alt.cause} — {categoryLabel(alt.category)}, confidence{" "}
                {alt.confidence.toFixed(2)} ({alt.confirmed ? "confirmed" : "hypothesis"})
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function Recommendations({ items }: { items: Recommendation[] }) {
  if (items.length === 0) return null;
  return (
    <div className="table-scroll">
      <table className="table">
        <thead>
          <tr>
            <th>Memory</th>
            <th>Prevention</th>
            <th>Applicable</th>
            <th>Applied</th>
            <th>Reason</th>
          </tr>
        </thead>
        <tbody>
          {items.map((rec) => (
            <tr key={rec.memory_id}>
              <td className="mono small">{shortId(rec.memory_id)}</td>
              <td>{rec.prevention}</td>
              <td>
                <Badge tone={rec.applicable ? "info" : "muted"}>
                  {rec.applicable ? "yes" : "no"}
                </Badge>
              </td>
              <td>
                <Badge tone={rec.applied ? "success" : "muted"}>
                  {rec.applied ? "applied" : "blocked"}
                </Badge>
              </td>
              <td className="small muted">{rec.reason || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Explainability({ run }: { run: TaskRun }) {
  const attempts = run.attempts.filter((attempt) => attempt.retrieved.length > 0);
  if (attempts.length === 0) return null;
  return (
    <div className="stack">
      {attempts.map((attempt, index) => (
        <div key={attempt.execution_id}>
          <div className="small faint" style={{ marginBottom: 6 }}>
            Attempt {index + 1} · {attempt.retrieved.length} candidate
            {attempt.retrieved.length === 1 ? "" : "s"} ·{" "}
            {attempt.applied_memory_ids.length} applied
          </div>
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Memory</th>
                  <th>Rank</th>
                  <th>Similarity</th>
                  <th>Score</th>
                  <th>Selected</th>
                  <th>Applied</th>
                  <th>Matched terms</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {attempt.retrieved.map((result) => {
                  const applied = attempt.applied_memory_ids.includes(result.memory.id);
                  return (
                    <tr key={result.memory.id}>
                      <td className="mono small">{shortId(result.memory.id)}</td>
                      <td className="mono small">#{result.rank}</td>
                      <td className="mono small">{pct(result.similarity, 0)}</td>
                      <td className="mono small">{result.score.toFixed(3)}</td>
                      <td>
                        <Badge tone={result.selected ? "info" : "muted"}>
                          {result.selected ? "surfaced" : "filtered"}
                        </Badge>
                      </td>
                      <td>
                        <Badge tone={applied ? "success" : "muted"}>
                          {applied ? "applied" : "not applied"}
                        </Badge>
                      </td>
                      <td className="small mono">
                        {result.matched_terms.length
                          ? result.matched_terms.join(", ")
                          : "—"}
                      </td>
                      <td className="small muted">{result.reason || "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </div>
  );
}

export function RunView({ run }: { run: TaskRun }) {
  return (
    <div className="stack">
      <div className="row" style={{ gap: 8 }}>
        <Badge tone={run.final_success ? "success" : "danger"}>
          {run.final_success ? "Success" : "Failure"}
        </Badge>
        <Badge tone={outcomeTone(run.final_outcome)}>
          {outcomeLabel(run.final_outcome)}
        </Badge>
        <Badge tone={run.mode === "memory" ? "accent" : "muted"}>{run.mode} mode</Badge>
        {run.prevented_failure && <Badge tone="success">Failure prevented</Badge>}
        <span className="small faint">
          {run.attempts_used} attempt{run.attempts_used === 1 ? "" : "s"} ·{" "}
          {formatDuration(run.duration_ms)} · task type{" "}
          <span className="mono">{run.task_type}</span>
        </span>
      </div>

      {run.mode === "naive" && (
        <div className="notice">
          Naive mode applies every retrieved memory with <b>no validation</b> — no
          status, confidence, relevance, or contradiction gating. It is a research
          arm for comparison and is not a recommended operating mode.
        </div>
      )}

      {run.prevention_evidence && (
        <div className="notice">{run.prevention_evidence}</div>
      )}

      {(run.memory_ids_applied.length > 0 ||
        run.memory_ids_created.length > 0 ||
        run.memory_ids_reinforced.length > 0 ||
        run.retrieved_memory_ids.length > 0) && (
        <div className="grid grid-3">
          <div>
            <div className="stat-label">Applied memories</div>
            <div className="pill-row" style={{ marginTop: 6 }}>
              {run.memory_ids_applied.length ? (
                run.memory_ids_applied.map((id) => (
                  <span key={id} className="badge tone-success mono">
                    {shortId(id)}
                  </span>
                ))
              ) : (
                <span className="small faint">none</span>
              )}
            </div>
          </div>
          <div>
            <div className="stat-label">Learned this run</div>
            <div className="pill-row" style={{ marginTop: 6 }}>
              {run.memory_ids_created.length ? (
                run.memory_ids_created.map((id) => (
                  <span key={id} className="badge tone-accent mono">
                    {shortId(id)}
                  </span>
                ))
              ) : (
                <span className="small faint">none</span>
              )}
            </div>
          </div>
          <div>
            <div className="stat-label">Retrieved / surfaced</div>
            <div className="pill-row" style={{ marginTop: 6 }}>
              {run.retrieved_memory_ids.length ? (
                run.retrieved_memory_ids.map((id) => (
                  <span key={id} className="badge tone-info mono">
                    {shortId(id)}
                  </span>
                ))
              ) : (
                <span className="small faint">none</span>
              )}
            </div>
          </div>
        </div>
      )}

      {run.attempts.some((attempt) => attempt.retrieved.length > 0) && (
        <div>
          <div className="section-title">Why each memory was (or wasn&apos;t) used</div>
          <Explainability run={run} />
        </div>
      )}

      {run.analyses.length > 0 && (
        <div>
          <div className="section-title">Failure analysis</div>
          <div className="stack">
            {run.analyses.map((analysis) => (
              <AnalysisCard key={analysis.execution_id} analysis={analysis} />
            ))}
          </div>
        </div>
      )}

      <div>
        <div className="section-title">Execution timeline</div>
        <div className="timeline">
          {run.attempts.map((attempt, attemptIndex) => (
            <div className="attempt" key={attempt.execution_id}>
              <div className="attempt-head">
                <span className="badge tone-muted">Attempt {attemptIndex + 1}</span>
                <Badge tone={attempt.success ? "success" : "danger"}>
                  {attempt.success ? "succeeded" : "failed"}
                </Badge>
                <Badge tone={outcomeTone(attempt.outcome)}>
                  {outcomeLabel(attempt.outcome)}
                </Badge>
                <span className="small faint">
                  plan strategy <span className="mono">{attempt.plan.strategy}</span> ·{" "}
                  {formatDuration(attempt.duration_ms)} · {attempt.retries} retr
                  {attempt.retries === 1 ? "y" : "ies"}
                </span>
                <div className="grow" />
                <span className="tiny faint mono">
                  {shortId(attempt.execution_id, 12)}
                </span>
              </div>

              {attempt.plan.notes.length > 0 && (
                <div className="small muted" style={{ padding: "9px 13px 0" }}>
                  {attempt.plan.notes.join(" · ")}
                </div>
              )}

              {attempt.traces.map((trace) => (
                <div className="step" key={`${attempt.execution_id}-${trace.index}`}>
                  <div
                    className={`step-icon ${trace.result.ok ? "result-ok" : "result-fail"}${
                      trace.step.is_prevention ? " prevention" : ""
                    }`}
                  >
                    {trace.result.ok ? "✓" : "✕"}
                  </div>
                  <div>
                    <div className="step-title">
                      <span>{trace.step.description || trace.step.tool}</span>
                      <span className="badge tone-muted mono">{trace.step.tool}</span>
                      {trace.step.is_prevention && (
                        <Badge tone="accent">prevention</Badge>
                      )}
                      {trace.step.optional && <Badge tone="muted">optional</Badge>}
                    </div>
                    <div className="step-meta">
                      <span>{formatDuration(trace.result.duration_ms)}</span>
                      <span className="mono">{trace.result.outcome_type}</span>
                      {trace.step.prevention_source && (
                        <span>
                          source <span className="mono">{shortId(trace.step.prevention_source)}</span>
                        </span>
                      )}
                      {trace.result.error_code && (
                        <span className="mono">{trace.result.error_code}</span>
                      )}
                    </div>
                    <div className="step-args">
                      {Object.keys(trace.step.args).length > 0 ? (
                        JSON.stringify(trace.step.args)
                      ) : (
                        <span className="args-empty">no arguments</span>
                      )}
                    </div>
                    {trace.result.error && (
                      <div className="step-error">{trace.result.error}</div>
                    )}
                    {trace.result.evidence.length > 0 && (
                      <ul className="evidence">
                        {trace.result.evidence.map((item, index) => (
                          <li key={`${item}-${index}`}>{item}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>

      {run.attempts.some((a) => a.recommendations.length > 0) && (
        <div>
          <div className="section-title">Memory recommendations</div>
          <div className="stack">
            {run.attempts
              .filter((a) => a.recommendations.length > 0)
              .map((attempt, index) => (
                <div key={attempt.execution_id}>
                  <div className="small faint" style={{ marginBottom: 6 }}>
                    Attempt {index + 1}
                  </div>
                  <Recommendations items={attempt.recommendations} />
                </div>
              ))}
          </div>
        </div>
      )}

      <JsonBlock data={run} />
    </div>
  );
}
