"use client";

import { useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { categoryTone, humanize, shortId } from "@/lib/format";
import type { ScenarioRunResponse, ScenarioSummary } from "@/lib/types";

import { RetrievalResultCard } from "./RetrievalResultCard";
import { RunView } from "./RunView";
import { Badge, Card, Empty, ErrorBanner, JsonBlock, Spinner } from "./ui";

export default function ScenarioPanel() {
  const [scenarios, setScenarios] = useState<ScenarioSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [runningId, setRunningId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ScenarioRunResponse | null>(null);

  useEffect(() => {
    let active = true;
    api
      .listScenarios()
      .then((items) => {
        if (active) setScenarios(items);
      })
      .catch((err) => {
        if (active) setError(err instanceof ApiError ? err.message : String(err));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  async function run(id: string) {
    setRunningId(id);
    setError(null);
    setDetail(null);
    try {
      const result = await api.runScenario(id);
      setDetail(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setRunningId(null);
    }
  }

  return (
    <div className="stack">
      <Card
        title="Simulated scenarios"
        subtitle="Each scenario runs twice — baseline (no memory) then memory-enabled — on an isolated store. All scenarios are simulated with deterministic fault injection."
      >
        {loading ? (
          <div className="row">
            <Spinner /> <span className="muted">Loading scenarios…</span>
          </div>
        ) : scenarios.length === 0 ? (
          <Empty>No scenarios available.</Empty>
        ) : (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Scenario</th>
                  <th>Category</th>
                  <th>Task</th>
                  <th>Baseline</th>
                  <th>Memory</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {scenarios.map((scenario) => (
                  <tr key={scenario.id}>
                    <td>
                      <div style={{ fontWeight: 600 }}>{scenario.name}</div>
                      <div className="small faint">{scenario.description}</div>
                    </td>
                    <td>
                      <Badge tone={categoryTone(scenario.category)}>
                        {humanize(scenario.category)}
                      </Badge>
                    </td>
                    <td className="small mono wrap-anywhere">{scenario.task}</td>
                    <td className="small">
                      {scenario.expected.baseline_success ? "✓" : "✕"}
                    </td>
                    <td className="small">
                      {scenario.expected.memory_success ? "✓" : "✕"}
                    </td>
                    <td>
                      <button
                        className="btn small"
                        onClick={() => run(scenario.id)}
                        disabled={runningId !== null}
                      >
                        {runningId === scenario.id ? <Spinner /> : "▶"} Run
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {error && <ErrorBanner message={error} />}

      {detail && (
        <>
          <Card
            title={detail.scenario.name}
            subtitle={detail.scenario.description}
            actions={
              <div className="row">
                <Badge tone={categoryTone(detail.scenario.category)}>
                  {humanize(detail.scenario.category)}
                </Badge>
                {detail.scenario.simulated && <Badge tone="info">simulated</Badge>}
              </div>
            }
          >
            <div className="grid grid-4">
              <div className="stat">
                <div className="stat-label">Baseline</div>
                <div
                  className="stat-value mono"
                  style={{
                    color: detail.baseline.final_success
                      ? "var(--success)"
                      : "var(--danger)",
                  }}
                >
                  {detail.baseline.final_success ? "Success" : "Failed"}
                </div>
                <div className="stat-hint">
                  {detail.baseline.attempts_used} attempt(s)
                </div>
              </div>
              <div className="stat">
                <div className="stat-label">Memory</div>
                <div
                  className="stat-value mono"
                  style={{
                    color: detail.memory.final_success
                      ? "var(--success)"
                      : "var(--danger)",
                  }}
                >
                  {detail.memory.final_success ? "Success" : "Failed"}
                </div>
                <div className="stat-hint">{detail.memory.attempts_used} attempt(s)</div>
              </div>
              <div className="stat">
                <div className="stat-label">Memory delta</div>
                <div className="stat-value mono">
                  {detail.baseline.final_success === detail.memory.final_success
                    ? "—"
                    : "improved"}
                </div>
                <div className="stat-hint">
                  {detail.memory.prevented_failure ? "failure prevented" : "no change"}
                </div>
              </div>
              <div className="stat">
                <div className="stat-label">Memories</div>
                <div className="stat-value mono">
                  {detail.memory_stats.after.total_memories}
                </div>
                <div className="stat-hint">
                  seeded {detail.seeded_memory_ids.length}
                </div>
              </div>
            </div>

            {detail.seeded_memory_ids.length > 0 && (
              <div className="small faint" style={{ marginTop: 14 }}>
                Seeded memories:{" "}
                {detail.seeded_memory_ids.map((id) => (
                  <span key={id} className="badge tone-muted mono" style={{ marginRight: 6 }}>
                    {shortId(id)}
                  </span>
                ))}
              </div>
            )}
          </Card>

          <Card
            title="Retrieval for this scenario"
            subtitle="Which memories were surfaced for the task, and why. 'Selected' means it cleared both the score floor and the text-similarity floor."
          >
            {detail.retrieval.length === 0 ? (
              <Empty>No seeded memories were available to retrieve.</Empty>
            ) : (
              <div className="stack">
                {detail.retrieval.map((result) => (
                  <RetrievalResultCard key={result.memory.id} result={result} />
                ))}
              </div>
            )}
          </Card>

          <Card title="Baseline run" subtitle="No retrieval, no learning.">
            <RunView run={detail.baseline} />
          </Card>

          <Card title="Memory-enabled run" subtitle="Retrieve, apply, learn, feed back.">
            <RunView run={detail.memory} />
          </Card>

          <Card
            title="Raw metrics"
            subtitle="Measured values collected by the evaluation metrics layer."
          >
            <JsonBlock
              data={{ metrics: detail.metrics, memory_stats: detail.memory_stats }}
            />
          </Card>
        </>
      )}
    </div>
  );
}
