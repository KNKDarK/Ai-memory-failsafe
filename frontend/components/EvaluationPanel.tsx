"use client";

import { useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { categoryTone, humanize, pct } from "@/lib/format";
import type { AggregateMetrics, EvaluationReport, RelevanceMetrics } from "@/lib/types";

import { BarList, ColumnChart } from "./Charts";
import { Badge, Card, ErrorBanner, JsonBlock, Spinner, Stat } from "./ui";

function relevanceRows(
  label: string,
  metrics: RelevanceMetrics,
): Array<[string, string]> {
  return [
    [label, `${pct(metrics.precision)} / ${pct(metrics.recall)}`],
    ["true positives", String(metrics.true_positives)],
    ["false positives", String(metrics.false_positives)],
    ["false negatives", String(metrics.false_negatives)],
  ];
}

export default function EvaluationPanel() {
  const [report, setReport] = useState<EvaluationReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const report = await api.evaluationReport();
        if (active) setReport(report);
      } catch (err) {
        if (!active) return;
        if (err instanceof ApiError && err.status === 404) {
          setReport(null);
        } else {
          setError(err instanceof ApiError ? err.message : String(err));
        }
      } finally {
        if (active) setLoading(false);
      }
    };
    void load();
    return () => {
      active = false;
    };
  }, []);

  async function run() {
    setRunning(true);
    setError(null);
    try {
      setReport(await api.runEvaluation());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  }

  const baseline: AggregateMetrics | undefined = report?.aggregate.baseline;
  const naive: AggregateMetrics | undefined = report?.aggregate.naive;
  const memory: AggregateMetrics | undefined = report?.aggregate.memory;
  const delta =
    baseline && memory ? memory.success_rate - baseline.success_rate : null;

  return (
    <div className="stack">
      <Card
        title="Evaluation benchmark"
        subtitle="Runs every scenario twice — baseline vs memory-enabled — under identical conditions on an isolated store. All figures are measured from real runs; scenarios are simulated and labelled as such."
        actions={
          <button className="btn primary" onClick={run} disabled={running}>
            {running ? <Spinner /> : "▶"} Run evaluation
          </button>
        }
      >
        {loading ? (
          <div className="row">
            <Spinner /> <span className="muted">Loading report…</span>
          </div>
        ) : !report ? (
          <div className="callout">
            No evaluation report has been generated yet. Run the benchmark to produce a
            machine-readable JSON report and summarise it here.
          </div>
        ) : (
          <>
            <div className="small faint" style={{ marginBottom: 14 }}>
              Generated {new Date(report.generated_at).toLocaleString()} ·{" "}
              {report.scenario_count} scenarios · retrieval mode{" "}
              <span className="mono">{report.retrieval_mode}</span>
            </div>

            <div className="grid grid-4">
              <Stat
                label="Baseline success"
                value={pct(baseline?.success_rate)}
                hint={`${baseline?.successes ?? 0}/${baseline?.tasks ?? 0} tasks`}
                tone="danger"
              />
              <Stat
                label="Memory success"
                value={pct(memory?.success_rate)}
                hint={`${memory?.successes ?? 0}/${memory?.tasks ?? 0} tasks`}
                tone="success"
              />
              <Stat
                label="Success delta"
                value={delta == null ? "—" : `${delta >= 0 ? "+" : ""}${(delta * 100).toFixed(1)} pts`}
                hint="memory − baseline"
                tone={delta == null ? undefined : delta > 0 ? "success" : "warn"}
              />
              <Stat
                label="Expectations met"
                value={`${report.scenarios_expectations_met}/${report.scenario_count}`}
                tone={
                  report.scenarios_expectations_met === report.scenario_count
                    ? "success"
                    : "warn"
                }
              />
              <Stat
                label="Failures prevented"
                value={memory?.prevented_failures ?? 0}
                hint="attempts succeeding after a memory changed the plan"
              />
              <Stat
                label="Harmful applications"
                value={memory?.harmful_memory_applications ?? 0}
                tone={
                  (memory?.harmful_memory_applications ?? 0) === 0
                    ? "success"
                    : "danger"
                }
                hint="incorrect memories that were applied"
              />
              <Stat
                label="Memories created"
                value={memory?.memories_created ?? 0}
                hint="learned during memory-mode runs"
              />
              <Stat
                label="Avg attempts"
                value={
                  memory?.avg_attempts == null ? "—" : memory.avg_attempts.toFixed(2)
                }
                hint={
                  baseline?.avg_attempts == null
                    ? undefined
                    : `baseline ${baseline.avg_attempts.toFixed(2)}`
                }
              />
            </div>
          </>
        )}
      </Card>

      {error && <ErrorBanner message={error} />}

      {report && (
        <>
          <Card
            title="Retrieval relevance"
            subtitle="Two different events. Selection is measured on a read-only seed-memory preview (which seeded memories are surfaced). Application is measured on the actual memory-mode run (which memories were applied to plans); memories learned during the run are reported separately and never counted as false positives. A relevant but untrustworthy memory may be surfaced and correctly blocked, so selection precision can be lower than application precision."
          >
            <div className="grid grid-2">
              <div className="callout">
                <div className="section-title" style={{ marginTop: 0 }}>
                  Application — precision / recall
                </div>
                <div className="kv">
                  {relevanceRows("precision / recall", report.retrieval_relevance.application).map(
                    ([key, value]) => (
                      <div className="kv-row" key={key}>
                        <span className="kv-key">{key}</span>
                        <span className="kv-val mono">{value}</span>
                      </div>
                    ),
                  )}
                </div>
              </div>
              <div className="callout">
                <div className="section-title" style={{ marginTop: 0 }}>
                  Selection — precision / recall
                </div>
                <div className="kv">
                  {relevanceRows("precision / recall", report.retrieval_relevance.selection).map(
                    ([key, value]) => (
                      <div className="kv-row" key={key}>
                        <span className="kv-key">{key}</span>
                        <span className="kv-val mono">{value}</span>
                      </div>
                    ),
                  )}
                </div>
              </div>
            </div>
          </Card>

          <Card
            title="Evaluation arms"
            subtitle="The naive arm retrieves and applies every memory with no validation, isolating what the guard rails contribute. Harmful applications should fall without losing prevention."
          >
            <div className="grid grid-2">
              <div className="stack">
                <div className="small faint">Success rate by arm</div>
                <ColumnChart
                  categories={["Baseline", "Naive", "Memory"]}
                  series={[
                    {
                      key: "success",
                      label: "Success rate",
                      tone: "success",
                      values: [
                        baseline?.success_rate ?? 0,
                        naive?.success_rate ?? 0,
                        memory?.success_rate ?? 0,
                      ],
                    },
                  ]}
                  max={1}
                  format={(value) => pct(value, 0)}
                />
              </div>
              <div className="stack">
                <div className="small faint">Harmful applications (lower is better)</div>
                <BarList
                  items={[
                    {
                      label: "Baseline",
                      value: baseline?.harmful_memory_applications ?? 0,
                      tone: "muted",
                    },
                    {
                      label: "Naive",
                      value: naive?.harmful_memory_applications ?? 0,
                      tone: "danger",
                    },
                    {
                      label: "Memory",
                      value: memory?.harmful_memory_applications ?? 0,
                      tone: "success",
                    },
                  ]}
                  format={(value) => String(value)}
                />
              </div>
            </div>
            <div className="table-scroll" style={{ marginTop: 14 }}>
              <table className="table">
                <thead>
                  <tr>
                    <th>Arm</th>
                    <th>Success</th>
                    <th>Avg retries</th>
                    <th>Prevented</th>
                    <th>Harmful</th>
                  </tr>
                </thead>
                <tbody>
                  {(
                    [
                      ["Baseline (no memory)", baseline],
                      ["Naive memory", naive],
                      ["Validated memory", memory],
                    ] as Array<[string, AggregateMetrics | undefined]>
                  ).map(([label, arm]) => (
                    <tr key={label}>
                      <td>{label}</td>
                      <td className="mono">{pct(arm?.success_rate)}</td>
                      <td className="mono">
                        {arm?.avg_retries == null ? "—" : arm.avg_retries.toFixed(2)}
                      </td>
                      <td className="mono">{arm?.prevented_failures ?? 0}</td>
                      <td className="mono">{arm?.harmful_memory_applications ?? 0}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          {report.retrieval_method_comparison && (
            <Card
              title="Retrieval method comparison"
              subtitle={`Similarity-only precision/recall of each text-similarity method on ${report.retrieval_method_comparison.probe_count} labelled seed-memory probes (no ranker weights applied, so this isolates the method).`}
            >
              <ColumnChart
                categories={Object.keys(report.retrieval_method_comparison.methods)}
                series={[
                  {
                    key: "precision",
                    label: "Precision",
                    tone: "accent",
                    values: Object.values(report.retrieval_method_comparison.methods).map(
                      (metrics) => metrics.precision ?? 0,
                    ),
                  },
                  {
                    key: "recall",
                    label: "Recall",
                    tone: "success",
                    values: Object.values(report.retrieval_method_comparison.methods).map(
                      (metrics) => metrics.recall ?? 0,
                    ),
                  },
                ]}
                max={1}
                format={(value) => pct(value, 0)}
              />
              <div className="table-scroll" style={{ marginTop: 14 }}>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Method</th>
                      <th>Precision</th>
                      <th>Recall</th>
                      <th>F1</th>
                      <th>TP</th>
                      <th>FP</th>
                      <th>FN</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(report.retrieval_method_comparison.methods).map(
                      ([method, metrics]) => (
                        <tr key={method}>
                          <td className="mono">{method}</td>
                          <td className="mono">{pct(metrics.precision)}</td>
                          <td className="mono">{pct(metrics.recall)}</td>
                          <td className="mono">{pct(metrics.f1)}</td>
                          <td className="mono">{metrics.true_positives}</td>
                          <td className="mono">{metrics.false_positives}</td>
                          <td className="mono">{metrics.false_negatives}</td>
                        </tr>
                      ),
                    )}
                  </tbody>
                </table>
              </div>
            </Card>
          )}

          {report.lifecycle && (
            <Card
              title="Memory lifecycle"
              subtitle={`Deterministic labels from memory age and observed outcomes over ${report.lifecycle.unique_memories} unique memories. "Projected" advances the clock to the retire horizon (a projection, not observed data).`}
            >
              <ColumnChart
                categories={["Fresh", "Stale", "Obsolete", "Expired"]}
                series={[
                  {
                    key: "at_run",
                    label: "At run",
                    tone: "accent",
                    values: [
                      report.lifecycle.at_run.counts.fresh,
                      report.lifecycle.at_run.counts.stale,
                      report.lifecycle.at_run.counts.obsolete,
                      report.lifecycle.at_run.counts.expired,
                    ],
                  },
                  {
                    key: "projected",
                    label: `Projected (+${report.lifecycle.projected.horizon_days}d)`,
                    tone: "warn",
                    values: [
                      report.lifecycle.projected.counts.fresh,
                      report.lifecycle.projected.counts.stale,
                      report.lifecycle.projected.counts.obsolete,
                      report.lifecycle.projected.counts.expired,
                    ],
                  },
                ]}
                format={(value) => String(Math.round(value))}
              />
            </Card>
          )}

          <Card
            title="Per-scenario results"
            subtitle="Each scenario's baseline and memory outcomes against its expectation."
          >
            <div className="table-scroll">
              <table className="table">
                <thead>
                  <tr>
                    <th>Scenario</th>
                    <th>Category</th>
                    <th>Baseline</th>
                    <th>Memory</th>
                    <th>Prevented</th>
                    <th>Expectation</th>
                  </tr>
                </thead>
                <tbody>
                  {report.scenarios.map((row) => {
                    const met =
                      row.baseline.success === row.expected.baseline_success &&
                      row.memory.success === row.expected.memory_success;
                    return (
                      <tr key={row.scenario_id}>
                        <td>
                          <div style={{ fontWeight: 600 }}>{row.name}</div>
                          <div className="small faint">{row.description}</div>
                        </td>
                        <td>
                          <Badge tone={categoryTone(row.category)}>
                            {humanize(row.category)}
                          </Badge>
                        </td>
                        <td>
                          <Badge tone={row.baseline.success ? "success" : "danger"}>
                            {row.baseline.success ? "pass" : "fail"}
                          </Badge>
                        </td>
                        <td>
                          <Badge tone={row.memory.success ? "success" : "danger"}>
                            {row.memory.success ? "pass" : "fail"}
                          </Badge>
                        </td>
                        <td className="small">
                          {row.memory.prevented_failure ? "yes" : "no"}
                        </td>
                        <td>
                          <Badge tone={met ? "success" : "warn"}>
                            {met ? "met" : "unmet"}
                          </Badge>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>

          <Card title="Methodology & limitations">
            <div className="kv" style={{ marginBottom: 14 }}>
              {Object.entries(report.methodology).map(([key, value]) => (
                <div className="kv-row" key={key}>
                  <span className="kv-key mono">{humanize(key)}</span>
                  <span className="kv-val small">
                    {typeof value === "string" ? value : JSON.stringify(value)}
                  </span>
                </div>
              ))}
            </div>
            <ul className="evidence">
              {report.limitations.map((limitation, index) => (
                <li key={index}>{limitation}</li>
              ))}
            </ul>
          </Card>

          <Card title="Raw report">
            <JsonBlock data={report} label="evaluation_report.json" />
          </Card>
        </>
      )}
    </div>
  );
}
