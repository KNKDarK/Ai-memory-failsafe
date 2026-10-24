"use client";

import { useCallback, useMemo, useState } from "react";

import { api, ApiError } from "@/lib/api";
import type { Tone } from "@/lib/format";
import type { ExecutionModeLab, ReplayRunResponse } from "@/lib/types";

import { MemoryAttributionInspector } from "@/components/lab/MemoryAttributionInspector";
import { Badge, Card, ErrorBanner, Empty, Spinner, Stat } from "@/components/ui";

/* ------------------------------------------------------------------ */
/* Helpers                                                              */
/* ------------------------------------------------------------------ */

function modeTone(mode: ExecutionModeLab): Tone {
  return mode === "simulated" ? "info" : "warn";
}

function successTone(ok: boolean): Tone {
  return ok ? "success" : "danger";
}

function formatMs(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const s = ms / 1000;
  return s < 60 ? `${s.toFixed(2)} s` : `${Math.floor(s / 60)}m ${Math.floor(s % 60)}s`;
}

/* ------------------------------------------------------------------ */
/* Delta metrics — rendered dynamically from the backend delta object   */
/* ------------------------------------------------------------------ */

function renderDeltaValues(delta: Record<string, unknown>) {
  const entries = Object.entries(delta).filter(
    ([k]) => k !== "baseline" && k !== "treatment",
  );
  if (!entries.length) return null;

  return (
    <div className="delta-grid">
      {entries.map(([key, value]) => {
        const label = key.replace(/_/g, " ").replace(/\b\w/g, (c: string) => c.toUpperCase());
        let display: React.ReactNode;
        if (typeof value === "number") {
          display = Number.isInteger(value) ? value : value.toFixed(2);
        } else {
          display = String(value);
        }
        return <Stat key={key} label={label} value={display} />;
      })}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Step log row                                                         */
/* ------------------------------------------------------------------ */

function StepLogRow({ step, idx }: { step: ReplayRunResponse["baseline"]["steps"][0]; idx: number }) {
  return (
    <div className={`step-row ${step.error ? "step-error" : ""}`}>
      <span className="step-number mono">{idx}</span>
      <span className="step-action">{step.action}</span>
      {step.tool_call && <Badge tone="accent">{step.tool_call}</Badge>}
      {step.error && (
        <span className="step-error-text" title={step.error}>
          X
        </span>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Execution arm panel                                                  */
/* ------------------------------------------------------------------ */

function ExecutionArmPanel({
  trace,
  label,
  tone,
}: {
  trace: ReplayRunResponse["baseline"];
  label: string;
  tone: Tone;
}) {
  const hasMemories = trace.retrieved_memories.length > 0;
  const hasSteps = trace.steps.length > 0;

  return (
    <Card
      title={label}
      actions={
        <>
          <Badge tone={tone}>{trace.execution_mode}</Badge>
          <span className={`badge tone-${successTone(trace.success)}`}>
            {trace.success ? "Success" : "Failed"}
          </span>
        </>
      }
    >
      {/* Summary stats */}
      <div className="arm-stats">
        <Stat label="Attempts" value={trace.total_attempts} />
        <Stat label="Duration" value={formatMs(trace.execution_time_ms)} />
        <Stat label="Steps" value={trace.steps.length} />
        {hasMemories && (
          <Stat
            label="Memories Applied"
            value={trace.retrieved_memories.filter((m) => m.applied).length}
            hint={`of ${trace.retrieved_memories.length}`}
            tone="info"
          />
        )}
      </div>

      {/* Prevention injections */}
      {trace.prevention_injections.length > 0 && (
        <details className="prevention-details">
          <summary>Prevention rules ({trace.prevention_injections.length})</summary>
          <ul className="injection-list">
            {trace.prevention_injections.map((inj, i) => (
              <li key={i}>{inj}</li>
            ))}
          </ul>
        </details>
      )}

      {/* Step logs */}
      {hasSteps ? (
        <div className="step-logs">
          {trace.steps.map((step, idx) => (
            <StepLogRow key={idx} step={step} idx={idx + 1} />
          ))}
        </div>
      ) : (
        <Empty>No steps recorded</Empty>
      )}

      {/* Attribution inspector */}
      {hasMemories && (
        <MemoryAttributionInspector memories={trace.retrieved_memories} />
      )}
    </Card>
  );
}

/* ------------------------------------------------------------------ */
/* Main page                                                            */
/* ------------------------------------------------------------------ */

export default function LabPage() {
  const [scenarioId, setScenarioId] = useState("transient_api");
  const [taskInput, setTaskInput] = useState(
    "Fetch data from the billing api",
  );
  const [executionMode, setExecutionMode] = useState<ExecutionModeLab>("simulated");
  const [projectId, setProjectId] = useState("default_project");

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ReplayRunResponse | null>(null);

  const handleRun = useCallback(async () => {
    if (!scenarioId || !taskInput) return;
    setBusy(true);
    setError(null);
    try {
      const resp = await api.replayRun({
        scenario_id: scenarioId,
        task_input: taskInput,
        execution_mode: executionMode,
        project_id: projectId,
      });
      setResult(resp);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError(String(err));
      }
    } finally {
      setBusy(false);
    }
  }, [scenarioId, taskInput, executionMode, projectId]);

  const delta = useMemo(() => result?.delta ?? {}, [result]);

  return (
    <div className="lab-page">
      {/* Header */}
      <header className="lab-header">
        <h1>Memory Replay Lab</h1>
        <p className="faint">
          Side-by-side comparison of baseline (no memory) vs treatment (memory enabled) execution runs.
        </p>

        {/* Controls */}
        <div className="lab-controls">
          <label className="control-group">
            <span className="control-label">Scenario</span>
            <input
              type="text"
              value={scenarioId}
              onChange={(e) => setScenarioId(e.target.value)}
              placeholder="Scenario ID"
              className="control-input"
            />
          </label>

          <label className="control-group">
            <span className="control-label">Task Input</span>
            <input
              type="text"
              value={taskInput}
              onChange={(e) => setTaskInput(e.target.value)}
              placeholder="Task prompt / input"
              className="control-input"
            />
          </label>

          <label className="control-group">
            <span className="control-label">Project</span>
            <input
              type="text"
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
              placeholder="Project ID"
              className="control-input"
            />
          </label>

          {/* Execution mode toggle */}
          <fieldset className="mode-toggle">
            <legend>Execution Mode</legend>
            <button
              type="button"
              className={`toggle-btn ${executionMode === "simulated" ? "active" : ""}`}
              onClick={() => setExecutionMode("simulated")}
            >
              Simulated
            </button>
            <button
              type="button"
              className={`toggle-btn ${executionMode === "real" ? "active" : ""}`}
              onClick={() => setExecutionMode("real")}
            >
              Real
            </button>
          </fieldset>

          <button
            type="button"
            className="btn btn-primary run-btn"
            disabled={busy}
            onClick={handleRun}
          >
            {busy ? (
              <>
                <Spinner /> Running...
              </>
            ) : (
              "Run Replay"
            )}
          </button>
        </div>

        {/* Error banner */}
        {error && <ErrorBanner message={error} />}
      </header>

      {/* Results */}
      {!result && !busy && !error && (
        <div className="lab-empty">
          <Empty>
            Configure a scenario and press <strong>Run Replay</strong> to compare baseline vs treatment.
          </Empty>
        </div>
      )}

      {result && (
        <div className="lab-results">
          {/* Delta summary */}
          {Object.keys(delta).length > 0 && (
            <Card title="Delta Summary" actions={<Badge tone={modeTone(result.execution_mode)}>{result.execution_mode}</Badge>}>
              {renderDeltaValues(delta)}
            </Card>
          )}

          {/* Side-by-side panels */}
          <div className="lab-panels">
            <ExecutionArmPanel
              trace={result.baseline}
              label="Baseline (Memory Disabled)"
              tone="muted"
            />
            <span className="vs-divider" aria-hidden>VS</span>
            <ExecutionArmPanel
              trace={result.treatment}
              label="Treatment (Memory Enabled)"
              tone="success"
            />
          </div>

          {/* Replay metadata */}
          <Card title="Replay Metadata">
            <div className="kv">
              <div className="kv-row">
                <span className="kv-key">Replay ID</span>
                <span className="kv-val mono">{result.replay_id}</span>
              </div>
              <div className="kv-row">
                <span className="kv-key">Scenario</span>
                <span className="kv-val">{result.scenario_id}</span>
              </div>
              <div className="kv-row">
                <span className="kv-key">Mode</span>
                <span className="kv-val">{result.execution_mode}</span>
              </div>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}
