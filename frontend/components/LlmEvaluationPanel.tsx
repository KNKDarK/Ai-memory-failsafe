"use client";

import { useEffect, useRef, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { categoryTone, humanize, pct } from "@/lib/format";
import type {
  AggregateMetrics,
  LlmArmMode,
  LlmEvaluationReport,
  LlmReportSummary,
  LlmRunRow,
  ScenarioSummary,
} from "@/lib/types";

import { ColumnChart } from "./Charts";
import { Badge, Card, ErrorBanner, JsonBlock, Spinner, Stat } from "./ui";

const ARM_LABELS: Record<LlmArmMode, string> = {
  baseline: "Baseline (no memory)",
  naive: "Naive memory (unfiltered)",
  memory: "Validated memory",
};

function shortId(id: string): string {
  return id.length > 14 ? `${id.slice(0, 12)}…` : id;
}

function RowDetails({ row }: { row: LlmRunRow }) {
  const rows: Array<[string, string]> = [
    ["outcome", row.final_outcome],
    ["attempts", `${row.attempts_used}/${row.maximum_attempts}`],
    ["retrieved by controller", row.retrieved_ids.map(shortId).join(", ") || "—"],
    ["suggested by model", row.llm_suggested_ids.map(shortId).join(", ") || "—"],
    ["applied (gates decided)", row.applied_ids.map(shortId).join(", ") || "—"],
    ["harmful applied", row.harmful_applied_ids.join(", ") || "none"],
    ["memories created", row.memories_created.map(shortId).join(", ") || "—"],
    [
      "prevention evidence",
      row.prevention_evidence ?? (row.prevented_failure ? "yes" : "no"),
    ],
  ];
  return (
    <div className="callout" style={{ margin: "6px 0" }}>
      <div className="kv">
        {rows.map(([key, value]) => (
          <div className="kv-row" key={key}>
            <span className="kv-key">{key}</span>
            <span className="kv-val mono small">{value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function LlmEvaluationPanel() {
  const [scenarios, setScenarios] = useState<ScenarioSummary[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [modes, setModes] = useState<Set<LlmArmMode>>(
    new Set<LlmArmMode>(["baseline", "naive", "memory"]),
  );
  const [repetitions, setRepetitions] = useState(1);

  const [report, setReport] = useState<LlmEvaluationReport | null>(null);
  const [history, setHistory] = useState<LlmReportSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    let active = true;
    const load = async () => {
      const [scenariosResult, historyResult] = await Promise.allSettled([
        api.listScenarios(),
        api.llmReports(),
      ]);
      if (!active) return;
      if (scenariosResult.status === "fulfilled") {
        setScenarios(scenariosResult.value);
      }
      if (historyResult.status === "fulfilled") {
        setHistory(historyResult.value.reports);
      }
      setLoading(false);
    };
    void load();
    return () => {
      active = false;
      abortRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    if (!running) return;
    const started = Date.now();
    const timer = window.setInterval(
      () => setElapsed(Math.round((Date.now() - started) / 1000)),
      1000,
    );
    return () => window.clearInterval(timer);
  }, [running]);

  function toggleScenario(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleMode(mode: LlmArmMode) {
    setModes((prev) => {
      const next = new Set(prev);
      if (next.has(mode)) next.delete(mode);
      else next.add(mode);
      return next;
    });
  }

  async function run() {
    if (modes.size === 0) {
      setError("Select at least one arm to run.");
      return;
    }
    setRunning(true);
    setError(null);
    setElapsed(0);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const result = await api.runLlmEvaluation(
        {
          scenarios: selected.size > 0 ? [...selected] : null,
          repetitions,
          modes: [...modes],
        },
        controller.signal,
      );
      setReport(result);
      setHistory((await api.llmReports().catch(() => ({ reports: [] }))).reports);
    } catch (err) {
      if (controller.signal.aborted) {
        setError(
          "Stopped waiting for the result. The benchmark may still finish on the " +
            "server; refresh the run history to see whether a report was saved.",
        );
      } else {
        setError(err instanceof ApiError ? err.message : String(err));
      }
    } finally {
      setRunning(false);
      abortRef.current = null;
    }
  }

  async function loadReport(runId: string) {
    setError(null);
    try {
      setReport(await api.llmReport(runId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }

  const armEntries = (
    [
      ["baseline", report?.aggregate?.baseline],
      ["naive", report?.aggregate?.naive],
      ["memory", report?.aggregate?.memory],
    ] as Array<[LlmArmMode, AggregateMetrics | undefined]>
  ).filter(([mode]) => !report || report.modes.includes(mode));

  return (
    <div className="stack">
      <Card
        title="LLM evaluation benchmark"
        subtitle="Runs the same scenarios through the configured local model in three comparable arms: baseline (the model plans from scratch), naive memory (the model sees unfiltered retrieved memories — a research arm that never bypasses the tool allowlist), and validated memory (the model sees only gate-passing memories; the deterministic trust gates still decide what is applied). Nothing runs automatically — start it explicitly."
        actions={
          <div className="row">
            {running && (
              <>
                <span className="tiny faint mono">{elapsed}s</span>
                <button
                  className="btn ghost"
                  onClick={() => abortRef.current?.abort()}
                >
                  ■ Stop waiting
                </button>
              </>
            )}
            <button className="btn primary" onClick={run} disabled={running}>
              {running ? <Spinner /> : "▶"} Run LLM benchmark
            </button>
          </div>
        }
      >
        <div className="small faint" style={{ marginBottom: 10 }}>
          While a benchmark is running the dashboard stays responsive; results
          appear here when the run finishes (no fake progress is shown).
        </div>
        <div className="grid grid-2">
          <div className="stack">
            <div className="section-title">Arms</div>
            {(["baseline", "naive", "memory"] as LlmArmMode[]).map((mode) => (
              <label key={mode} className="row small">
                <input
                  type="checkbox"
                  checked={modes.has(mode)}
                  onChange={() => toggleMode(mode)}
                />
                {ARM_LABELS[mode]}
              </label>
            ))}
            <div className="section-title" style={{ marginTop: 10 }}>
              Repetitions
            </div>
            <input
              type="number"
              min={1}
              max={10}
              value={repetitions}
              onChange={(event) =>
                setRepetitions(
                  Math.min(10, Math.max(1, Number(event.target.value) || 1)),
                )
              }
              style={{ width: 90 }}
              aria-label="repetitions"
            />
          </div>
          <div className="stack">
            <div className="section-title">Scenario subset</div>
            {loading ? (
              <Spinner />
            ) : (
              <div
                className="small"
                style={{ maxHeight: 220, overflowY: "auto" }}
              >
                {scenarios.map((scenario) => (
                  <label key={scenario.id} className="row small">
                    <input
                      type="checkbox"
                      checked={selected.has(scenario.id)}
                      onChange={() => toggleScenario(scenario.id)}
                    />
                    {scenario.name}
                    <Badge tone={categoryTone(scenario.category)}>
                      {humanize(scenario.category)}
                    </Badge>
                  </label>
                ))}
                <div className="tiny faint">
                  Nothing selected = every scenario.
                </div>
              </div>
            )}
          </div>
        </div>
      </Card>

      {error && <ErrorBanner message={error} />}

      {report && (
        <>
          <Card
            title="Run result"
            subtitle={`Run ${report.run_id} · ${report.benchmark_version} · generated ${new Date(report.generated_at).toLocaleString()}`}
          >
            <div className="row" style={{ marginBottom: 12 }}>
              <Badge
                tone={
                  report.status === "completed"
                    ? "success"
                    : report.status === "aborted"
                      ? "danger"
                      : "warn"
                }
              >
                {report.status}
              </Badge>
              <Badge tone={report.model_real ? "accent" : "muted"}>
                {report.model_real ? "real model" : "no real model"}
              </Badge>
              <span className="small faint mono">
                {report.llm_provider}
                {report.llm_model ? ` · ${report.llm_model}` : ""}
              </span>
            </div>

            {report.error && (
              <div className="callout" style={{ marginBottom: 12 }}>
                <strong>{report.status === "skipped" ? "Not run: " : "Error: "}</strong>
                {report.error}
              </div>
            )}

            {report.model_info && Object.keys(report.model_info).length > 0 && (
              <div className="kv" style={{ marginBottom: 12 }}>
                {Object.entries(report.model_info).map(([key, value]) => (
                  <div className="kv-row" key={key}>
                    <span className="kv-key mono">{humanize(key)}</span>
                    <span className="kv-val small">
                      {typeof value === "string" || typeof value === "number"
                        ? String(value)
                        : JSON.stringify(value)}
                    </span>
                  </div>
                ))}
              </div>
            )}

            {report.status === "completed" && report.aggregate && (
              <>
                <div className="grid grid-4">
                  <Stat
                    label="Model calls"
                    value={report.model_stats.model_calls}
                    hint={`${report.model_stats.model_call_errors} failed`}
                    tone={report.model_stats.model_call_errors > 0 ? "warn" : undefined}
                  />
                  <Stat
                    label="Tokens (out)"
                    value={report.model_stats.completion_tokens ?? "—"}
                    hint={`in ${report.model_stats.prompt_tokens ?? "—"}`}
                  />
                  <Stat
                    label="Speed"
                    value={
                      report.model_stats.tokens_per_second == null
                        ? "—"
                        : `${report.model_stats.tokens_per_second}/s`
                    }
                    hint={
                      report.model_stats.avg_latency_ms == null
                        ? undefined
                        : `avg ${report.model_stats.avg_latency_ms} ms/call`
                    }
                  />
                  <Stat
                    label="Scenarios"
                    value={`${report.scenario_count}×${report.repetitions}`}
                    hint={`modes: ${report.modes.join(", ")}`}
                  />
                </div>

                <div className="grid grid-2" style={{ marginTop: 14 }}>
                  <div className="stack">
                    <div className="small faint">Success rate by arm</div>
                    <ColumnChart
                      categories={armEntries.map(([mode]) => mode)}
                      series={[
                        {
                          key: "success",
                          label: "Success rate",
                          tone: "success",
                          values: armEntries.map(
                            ([, agg]) => agg?.success_rate ?? 0,
                          ),
                        },
                      ]}
                      max={1}
                      format={(value) => pct(value, 0)}
                    />
                  </div>
                  <div className="stack">
                    <div className="small faint">
                      Harmful memory applications (lower is better)
                    </div>
                    <ColumnChart
                      categories={armEntries.map(([mode]) => mode)}
                      series={[
                        {
                          key: "harmful",
                          label: "Harmful applications",
                          tone: "danger",
                          values: armEntries.map(
                            ([, agg]) => agg?.harmful_memory_applications ?? 0,
                          ),
                        },
                      ]}
                      format={(value) => String(Math.round(value))}
                    />
                  </div>
                </div>

                <div className="table-scroll" style={{ marginTop: 14 }}>
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Arm</th>
                        <th>Success</th>
                        <th>Attempts</th>
                        <th>Prevented</th>
                        <th>Harmful</th>
                      </tr>
                    </thead>
                    <tbody>
                      {armEntries.map(([mode, agg]) => (
                        <tr key={mode}>
                          <td>{ARM_LABELS[mode]}</td>
                          <td className="mono">{pct(agg?.success_rate)}</td>
                          <td className="mono">
                            {agg?.avg_attempts?.toFixed(2) ?? "—"}
                          </td>
                          <td className="mono">{agg?.prevented_failures ?? 0}</td>
                          <td className="mono">
                            {agg?.harmful_memory_applications ?? 0}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </Card>

          {report.status === "completed" && report.scenarios.length > 0 && (
            <Card
              title="Per-scenario results"
              subtitle="Expand a row to see which memories reached the model (suggested) versus which the trust gates actually applied, per arm."
            >
              <div className="table-scroll">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Scenario</th>
                      {report.modes.map((mode) => (
                        <th key={mode}>{mode}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {report.scenarios.map((row) => (
                      <ScenarioRow key={row.scenario_id} row={row} modes={report.modes} />
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}

          {report.retrieval_relevance && (
            <Card
              title="Retrieval relevance"
              subtitle="Selection is measured on the seeded-memory preview; application is measured on what the validated arm actually applied. Memories learned during a run are never counted as false positives."
            >
              <div className="grid grid-2">
                {(
                  [
                    ["Application", report.retrieval_relevance.application],
                    ["Selection", report.retrieval_relevance.selection],
                  ] as Array<[string, typeof report.retrieval_relevance.application] | [string, typeof report.retrieval_relevance.selection]>
                ).map(([label, metrics]) => (
                  <div className="callout" key={label}>
                    <div className="section-title" style={{ marginTop: 0 }}>
                      {label} — precision / recall
                    </div>
                    <div className="small mono">
                      {pct(metrics.precision)} / {pct(metrics.recall)} · TP{" "}
                      {metrics.true_positives} FP {metrics.false_positives} FN{" "}
                      {metrics.false_negatives}
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          )}

          {report.repetition_variance && (
            <Card
              title="Repetition variance"
              subtitle="Per-repetition success rates — a reminder that single-run differences on a small scenario set are mostly noise."
            >
              <div className="table-scroll">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Arm</th>
                      <th>Success rate per repetition</th>
                      <th>Std</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(report.repetition_variance).map(
                      ([mode, variance]) => (
                        <tr key={mode}>
                          <td>{mode}</td>
                          <td className="mono small">
                            {variance.success_rate_by_repetition
                              .map((rate) => pct(rate))
                              .join(" · ")}
                          </td>
                          <td className="mono">{variance.success_rate_std}</td>
                        </tr>
                      ),
                    )}
                  </tbody>
                </table>
              </div>
            </Card>
          )}

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
            <JsonBlock data={report} label={`llm_benchmark_${report.run_id}.json`} />
          </Card>
        </>
      )}

      <Card
        title="Run history"
        subtitle="Saved reports, newest first. Each run writes a uniquely-named JSON file that is never overwritten."
      >
        {history.length === 0 ? (
          <div className="small faint">No LLM benchmark reports saved yet.</div>
        ) : (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Generated</th>
                  <th>Status</th>
                  <th>Model</th>
                  <th>Scenarios</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {history.map((entry) => (
                  <tr key={entry.run_id}>
                    <td className="mono small">{entry.run_id}</td>
                    <td className="small">
                      {entry.generated_at
                        ? new Date(entry.generated_at).toLocaleString()
                        : "—"}
                    </td>
                    <td>
                      <Badge
                        tone={
                          entry.status === "completed"
                            ? "success"
                            : entry.status === "aborted"
                              ? "danger"
                              : "muted"
                        }
                      >
                        {entry.status ?? "unknown"}
                      </Badge>
                    </td>
                    <td className="small mono">{entry.llm_model ?? "—"}</td>
                    <td className="mono">{entry.scenario_count}</td>
                    <td>
                      <button
                        className="btn ghost small"
                        onClick={() => loadReport(entry.run_id)}
                      >
                        Load
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

function ScenarioRow({
  row,
  modes,
}: {
  row: LlmEvaluationReport["scenarios"][number];
  modes: LlmArmMode[];
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <tr>
        <td>
          <button className="btn ghost small" onClick={() => setOpen(!open)}>
            {open ? "▾" : "▸"}
          </button>{" "}
          <span style={{ fontWeight: 600 }}>{row.name}</span>
          <div className="small faint">{row.description}</div>
        </td>
        {modes.map((mode) => {
          const arm = row[mode];
          return (
            <td key={mode}>
              {arm ? (
                <div className="small">
                  <Badge tone={arm.success ? "success" : "danger"}>
                    {arm.success ? "pass" : "fail"}
                  </Badge>{" "}
                  <span className="faint mono">
                    {arm.attempts_used} att · applied {arm.applied_ids.length}
                  </span>
                </div>
              ) : (
                <span className="faint">—</span>
              )}
            </td>
          );
        })}
      </tr>
      {open && (
        <tr>
          <td colSpan={modes.length + 1}>
            {modes.map((mode) => {
              const arm = row[mode];
              if (!arm) return null;
              return (
                <div key={mode}>
                  <div className="section-title">{ARM_LABELS[mode]}</div>
                  <RowDetails row={arm} />
                  {(row.repetition_results[mode] ?? []).length > 1 && (
                    <div className="small faint mono" style={{ marginBottom: 8 }}>
                      repetitions:{" "}
                      {(row.repetition_results[mode] ?? [])
                        .map((rep) => (rep.success ? "pass" : "fail"))
                        .join(" · ")}
                    </div>
                  )}
                </div>
              );
            })}
            {row.notes && <div className="small faint">{row.notes}</div>}
          </td>
        </tr>
      )}
    </>
  );
}
