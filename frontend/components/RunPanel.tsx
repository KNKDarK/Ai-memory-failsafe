"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { PRESET_BY_ID, TASK_PRESETS } from "@/lib/presets";
import type { CompareResult, EnvironmentSpec, ExecutionMode, TaskRun } from "@/lib/types";

import { RunView } from "./RunView";
import { Card, ErrorBanner, Spinner } from "./ui";

type Busy = "run" | "compare" | null;

// One chat turn: a task prompt and the agent's eventual answer (a single run
// result or a baseline-vs-memory comparison). Results land asynchronously, so a
// turn can exist in a pending state first.
interface ChatTurn {
  id: string;
  task: string;
  mode: ExecutionMode;
  maxAttempts: number;
  run?: TaskRun;
  compare?: CompareResult;
  error?: string;
}

let turnSeq = 0;
function nextTurnId() {
  turnSeq += 1;
  return `turn-${Date.now()}-${turnSeq}`;
}

export default function RunPanel() {
  const [presetId, setPresetId] = useState(TASK_PRESETS[0].id);
  const [task, setTask] = useState(TASK_PRESETS[0].task);
  const [maxAttempts, setMaxAttempts] = useState(2);
  const [mode, setMode] = useState<ExecutionMode>("memory");
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [advancedJson, setAdvancedJson] = useState("");
  const [advancedError, setAdvancedError] = useState<string | null>(null);

  const [busy, setBusy] = useState<Busy>(null);
  const [error, setError] = useState<string | null>(null);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const chatRef = useRef<HTMLDivElement | null>(null);

  const preset = PRESET_BY_ID[presetId];

  const environment = useMemo<EnvironmentSpec | null>(() => {
    if (!advancedOpen) return preset.environment;
    const text = advancedJson.trim();
    if (!text) return preset.environment;
    try {
      return JSON.parse(text) as EnvironmentSpec;
    } catch {
      return null;
    }
  }, [advancedOpen, advancedJson, preset.environment]);

  // Keep the newest exchange in view as turns stream in.
  useEffect(() => {
    const el = chatRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns, busy]);

  function selectPreset(id: string) {
    const next = PRESET_BY_ID[id];
    if (!next) return;
    setPresetId(id);
    setTask(next.task);
    setAdvancedJson(JSON.stringify(next.environment, null, 2));
    setAdvancedError(null);
  }

  function validateAdvanced() {
    if (!advancedOpen) return null;
    const text = advancedJson.trim();
    if (!text) return null;
    try {
      JSON.parse(text);
      return null;
    } catch (err) {
      return err instanceof Error ? err.message : "invalid JSON";
    }
  }

  function resolveTurn(id: string, patch: Partial<ChatTurn>) {
    setTurns((prev) => prev.map((turn) => (turn.id === id ? { ...turn, ...patch } : turn)));
  }

  async function handleRun() {
    const parsedError = validateAdvanced();
    if (parsedError) {
      setAdvancedError(parsedError);
      return;
    }
    const submitTask = task.trim();
    if (!submitTask) {
      setError("Enter a task first.");
      return;
    }
    const turn: ChatTurn = {
      id: nextTurnId(),
      task: submitTask,
      mode,
      maxAttempts,
    };
    setTurns((prev) => [...prev, turn]);
    setTask("");
    setBusy("run");
    setError(null);
    try {
      const result = await api.runTask({
        task: submitTask,
        mode,
        max_attempts: maxAttempts,
        environment,
      });
      resolveTurn(turn.id, { run: result });
    } catch (err) {
      resolveTurn(turn.id, {
        error: err instanceof ApiError ? err.message : String(err),
      });
    } finally {
      setBusy(null);
    }
  }

  async function handleCompare() {
    const parsedError = validateAdvanced();
    if (parsedError) {
      setAdvancedError(parsedError);
      return;
    }
    const submitTask = task.trim();
    if (!submitTask) {
      setError("Enter a task first.");
      return;
    }
    const turn: ChatTurn = {
      id: nextTurnId(),
      task: submitTask,
      mode,
      maxAttempts,
    };
    setTurns((prev) => [...prev, turn]);
    setTask("");
    setBusy("compare");
    setError(null);
    try {
      const result = await api.compareTask({
        task: submitTask,
        max_attempts: maxAttempts,
        environment,
      });
      resolveTurn(turn.id, { compare: result });
    } catch (err) {
      resolveTurn(turn.id, {
        error: err instanceof ApiError ? err.message : String(err),
      });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="stack">
      <Card
        title="Agent Sandbox"
        subtitle="Give the agent a task. It plans, executes against an in-memory sandbox, and — in memory mode — retrieves and applies lessons learned from past failures."
      >
        <div className="stack">
          <div className="field-row">
            <div className="field">
              <label htmlFor="preset">Environment preset</label>
              <select
                id="preset"
                value={presetId}
                onChange={(event) => selectPreset(event.target.value)}
              >
                {TASK_PRESETS.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.label}
                  </option>
                ))}
              </select>
              <div className="small faint">{preset.description}</div>
            </div>

            <div className="field" style={{ maxWidth: 260 }}>
              <label htmlFor="mode">Mode</label>
              <select
                id="mode"
                value={mode}
                onChange={(event) => setMode(event.target.value as ExecutionMode)}
              >
                <option value="memory">memory (retrieve + validate + learn)</option>
                <option value="naive">naive (apply everything, no validation)</option>
                <option value="baseline">baseline (no memory)</option>
              </select>
            </div>

            <div className="field" style={{ maxWidth: 140 }}>
              <label htmlFor="attempts">Max attempts</label>
              <input
                id="attempts"
                type="number"
                min={1}
                max={6}
                value={maxAttempts}
                onChange={(event) =>
                  setMaxAttempts(Math.max(1, Math.min(6, Number(event.target.value) || 1)))
                }
              />
            </div>
          </div>

          <div>
            <button
              className="btn ghost small"
              onClick={() => {
                setAdvancedOpen((open) => !open);
                if (!advancedOpen && !advancedJson) {
                  setAdvancedJson(JSON.stringify(preset.environment, null, 2));
                }
              }}
            >
              {advancedOpen ? "▾" : "▸"} Advanced: custom environment JSON
            </button>
            {advancedOpen && (
              <div className="field" style={{ marginTop: 10 }}>
                <textarea
                  value={advancedJson}
                  onChange={(event) => {
                    setAdvancedJson(event.target.value);
                    setAdvancedError(null);
                  }}
                  rows={9}
                  spellCheck={false}
                  className="mono"
                  aria-label="environment JSON"
                />
                <div className="small faint">
                  A full <span className="mono">EnvironmentSpec</span>: config, secrets,
                  packages, registry, services, faults. Everything is simulated.
                </div>
                {advancedError && (
                  <div className="small" style={{ color: "var(--danger)" }}>
                    Invalid JSON: {advancedError}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </Card>

      {error && <ErrorBanner message={error} />}

      <Card
        title="Conversation"
        subtitle="Each turn is one task prompt and the agent's execution trace, step by step."
        actions={
          turns.length > 0 ? (
            <button
              className="btn ghost small"
              onClick={() => setTurns([])}
              disabled={busy !== null}
            >
              ⌫ Clear
            </button>
          ) : undefined
        }
      >
        {turns.length === 0 ? (
          <div className="callout">
            Pick a preset and press <b>Run Agent</b>. Run it once as <b>baseline</b> (it
            fails), then as <b>memory</b> with a higher attempt budget, or use{" "}
            <b>Compare</b> to see both side by side. The memory-mode run analyses the
            failure, stores a lesson, retrieves it on the next attempt, and can prevent
            the failure.
          </div>
        ) : (
          <div className="chat" ref={chatRef}>
            {turns.map((turn) => (
              <div className="chat-turn" key={turn.id}>
                <div className="chat-msg user">
                  <div className="chat-avatar" aria-hidden>
                    you
                  </div>
                  <div className="chat-bubble">
                    <div className="chat-role">
                      task · {turn.mode} · {turn.maxAttempts} attempt
                      {turn.maxAttempts === 1 ? "" : "s"}
                    </div>
                    <div className="chat-task">{turn.task}</div>
                  </div>
                </div>

                <div className="chat-msg agent">
                  <div className="chat-avatar" aria-hidden>
                    ⛭
                  </div>
                  <div className="chat-bubble">
                    <div className="chat-role">agent</div>
                    {turn.error ? (
                      <ErrorBanner message={turn.error} />
                    ) : turn.run ? (
                      <RunView run={turn.run} />
                    ) : turn.compare ? (
                      <div className="grid grid-2">
                        <div>
                          <div className="row" style={{ marginBottom: 10 }}>
                            <span className="badge tone-muted">Baseline</span>
                            <span className="small faint">
                              no retrieval, no learning
                            </span>
                          </div>
                          <RunView run={turn.compare.baseline} />
                        </div>
                        <div>
                          <div className="row" style={{ marginBottom: 10 }}>
                            <span className="badge tone-accent">Memory</span>
                            <span className="small faint">retrieve + apply + learn</span>
                          </div>
                          <RunView run={turn.compare.memory} />
                        </div>
                      </div>
                    ) : (
                      <div className="row">
                        <Spinner /> <span className="muted">Running…</span>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        <div className="sep" />

        <div className="composer">
          <div className="field composer-input">
            <label htmlFor="task">Task prompt</label>
            <textarea
              id="task"
              value={task}
              onChange={(event) => setTask(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  if (busy === null) void handleRun();
                }
              }}
              placeholder="e.g. Deploy the application"
              rows={1}
            />
          </div>
          <button className="btn primary" onClick={handleRun} disabled={busy !== null}>
            {busy === "run" ? <Spinner /> : "▶"} Run Agent
          </button>
          <button className="btn" onClick={handleCompare} disabled={busy !== null}>
            {busy === "compare" ? <Spinner /> : "⇄"} Compare
          </button>
        </div>
        <div className="small faint" style={{ marginTop: 8 }}>
          Enter to run · Shift+Enter for a newline
        </div>
      </Card>
    </div>
  );
}
