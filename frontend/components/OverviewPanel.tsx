"use client";

import { useEffect, useState } from "react";

import { api, API_BASE, ApiError } from "@/lib/api";
import { humanize, pct } from "@/lib/format";
import type {
  ConfigResponse,
  EvaluationReport,
  FailureMemory,
  HealthResponse,
  MemoryStats,
} from "@/lib/types";

import { BarList, ColumnChart, LineChart } from "./Charts";
import { Badge, Card, ErrorBanner, KeyValue, Spinner, Stat } from "./ui";

// Cumulative memory count by creation day — a real curve built from the stored
// memories (never a hardcoded series).
function growthPoints(memories: FailureMemory[]): Array<{ label: string; value: number }> {
  const perDay = new Map<string, number>();
  for (const memory of memories) {
    const day = (memory.created_at || "").slice(0, 10);
    if (!day) continue;
    perDay.set(day, (perDay.get(day) ?? 0) + 1);
  }
  const days = [...perDay.keys()].sort();
  let running = 0;
  return days.map((day) => {
    running += perDay.get(day) ?? 0;
    return { label: day.slice(5), value: running };
  });
}

const FLOW = [
  "Task",
  "Plan",
  "Execute",
  "Detect failure",
  "Analyse cause",
  "Extract lesson",
  "Store memory",
  "Retrieve",
  "Prevent next time",
];

export default function OverviewPanel({
  health,
  config,
}: {
  health: HealthResponse | null;
  config: ConfigResponse | null;
}) {
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [report, setReport] = useState<EvaluationReport | null>(null);
  const [memories, setMemories] = useState<FailureMemory[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const [statsResult, reportResult, memoriesResult] = await Promise.allSettled([
          api.memoryStats(),
          api.evaluationReport(),
          api.listMemories({ limit: 500 }),
        ]);
        if (!active) return;
        if (statsResult.status === "fulfilled") setStats(statsResult.value);
        else if (statsResult.reason instanceof ApiError && statsResult.reason.status !== 503)
          setError(statsResult.reason.message);
        if (reportResult.status === "fulfilled") setReport(reportResult.value);
        if (memoriesResult.status === "fulfilled") setMemories(memoriesResult.value.items);
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  const baseline = report?.aggregate.baseline;
  const naive = report?.aggregate.naive;
  const memory = report?.aggregate.memory;
  const delta = baseline && memory ? memory.success_rate - baseline.success_rate : null;

  const armCategories = ["Baseline", "Naive", "Memory"];
  const armSuccess = [
    baseline?.success_rate ?? 0,
    naive?.success_rate ?? 0,
    memory?.success_rate ?? 0,
  ];
  const harmfulItems = report
    ? [
        { label: "Baseline", value: report.aggregate.baseline.harmful_memory_applications, tone: "muted" },
        { label: "Naive", value: report.aggregate.naive?.harmful_memory_applications ?? 0, tone: "danger" },
        { label: "Memory", value: report.aggregate.memory.harmful_memory_applications, tone: "success" },
      ]
    : [];
  const categoryItems = stats
    ? Object.entries(stats.by_category)
        .sort((a, b) => b[1] - a[1])
        .map(([category, count]) => ({ label: humanize(category), value: count }))
    : [];
  const topLessonItems = [...memories]
    .sort((a, b) => b.use_count - a.use_count)
    .slice(0, 6)
    .map((item) => ({
      label: item.lesson || item.failure,
      value: item.use_count,
      tone: item.use_count > 0 ? "success" : "muted",
      hint: item.lesson,
    }));
  const growth = growthPoints(memories);

  return (
    <div className="stack">
      <div className="hero">
        <h1>Failure → Cause → Lesson → Prevention memory</h1>
        <p>
          A local, offline-first memory layer for AI agents. When a task fails, the agent
          analyses the root cause, distills a reusable lesson, stores it as a structured
          memory, and retrieves it before the next attempt — so the same failure is not
          repeated. Today&apos;s dashboard reads live data from the backend at{" "}
          <span className="mono">{API_BASE}</span>.
        </p>
        <div className="flow">
          {FLOW.map((step, index) => (
            <span key={step} style={{ display: "contents" }}>
              <span>{step}</span>
              {index < FLOW.length - 1 && <span className="arrow">→</span>}
            </span>
          ))}
        </div>
      </div>

      {error && <ErrorBanner message={error} />}

      <div className="grid grid-4">
        <Stat
          label="Backend"
          value={
            health
              ? health.status === "ok"
                ? "Online"
                : "Degraded"
              : "Unreachable"
          }
          tone={health?.status === "ok" ? "success" : "danger"}
          hint={health?.error ?? undefined}
        />
        <Stat
          label="Memories"
          value={health?.memory_count ?? stats?.total_memories ?? "—"}
          hint={
            health?.active_memory_count != null
              ? `${health.active_memory_count} active`
              : undefined
          }
        />
        {stats && (
          <Stat
            label="Repeated patterns"
            value={stats.repeated_failure_patterns}
            hint={`${stats.total_occurrences} occurrences`}
          />
        )}
        {stats && (
          <Stat
            label="Prevention success rate"
            value={pct(stats.prevention_success_rate)}
            hint={`${stats.times_applied} applications`}
          />
        )}
      </div>

      <div className="grid grid-2">
        <Card title="Runtime configuration" subtitle="Non-secret settings in effect.">
          {loading && !config ? (
            <div className="row">
              <Spinner /> <span className="muted">Loading…</span>
            </div>
          ) : config ? (
            <KeyValue
              rows={[
                ["Environment", <span key="env" className="mono">{config.environment}</span>],
                [
                  "Mode",
                  <Badge key="mode" tone={config.offline ? "info" : "accent"}>
                    {config.offline ? "offline / deterministic" : "real LLM"}
                  </Badge>,
                ],
                [
                  "LLM provider",
                  <span key="llm" className="mono">
                    {config.llm.provider} ({config.llm.real_model ? "real" : "rule-based"})
                  </span>,
                ],
                ["Embedding", <span key="emb" className="mono">{`${config.embedding.provider} @ ${config.embedding.dim}d`}</span>],
                [
                  "Retrieval",
                  <span key="ret" className="mono">
                    top {config.retrieval.limit} · score ≥ {config.retrieval.min_score} ·
                    sim ≥ {config.retrieval.min_similarity}
                  </span>,
                ],
                [
                  "Weights",
                  <span key="w" className="mono">
                    sim {config.weights.similarity} · conf {config.weights.confidence} ·
                    rec {config.weights.recency} · fb {config.weights.feedback}
                  </span>,
                ],
                [
                  "Apply threshold",
                  <span key="apply" className="mono">
                    {config.min_confidence_to_apply}
                  </span>,
                ],
                [
                  "Secret redaction",
                  <Badge key="red" tone={config.redact_secrets ? "success" : "warn"}>
                    {config.redact_secrets ? "enabled" : "disabled"}
                  </Badge>,
                ],
              ]}
            />
          ) : (
            <div className="empty">Configuration unavailable.</div>
          )}
        </Card>

        <Card
          title="Latest evaluation"
          subtitle="Measured baseline vs memory-enabled comparison over simulated scenarios."
        >
          {loading ? (
            <div className="row">
              <Spinner /> <span className="muted">Loading…</span>
            </div>
          ) : report && baseline && memory ? (
            <div className="stack">
              <div className="grid grid-3">
                <Stat label="Baseline" value={pct(baseline.success_rate)} tone="danger" />
                <Stat label="Memory" value={pct(memory.success_rate)} tone="success" />
                <Stat
                  label="Delta"
                  value={delta == null ? "—" : `${delta >= 0 ? "+" : ""}${(delta * 100).toFixed(1)} pts`}
                  tone={delta && delta > 0 ? "success" : "warn"}
                />
              </div>
              <KeyValue
                rows={[
                  ["Scenarios", String(report.scenario_count)],
                  [
                    "Expectations met",
                    `${report.scenarios_expectations_met}/${report.scenario_count}`,
                  ],
                  ["Failures prevented", String(memory.prevented_failures)],
                  ["Harmful applications", String(memory.harmful_memory_applications)],
                  ["Retrieval mode", <span key="rm" className="mono">{report.retrieval_mode}</span>],
                ]}
              />
              <div className="small faint">
                Open the <b>Evaluation</b> tab for the full report.
              </div>
            </div>
          ) : (
            <div className="callout">
              No report yet. Run the benchmark from the <b>Evaluation</b> tab.
            </div>
          )}
        </Card>
      </div>

      <Card
        title="Benchmark visuals"
        subtitle="Charts drawn from real backend data — baseline vs naive vs validated memory."
      >
        <div className="grid grid-2">
          <div className="stack">
            <div className="small faint">Success rate by arm</div>
            <ColumnChart
              categories={armCategories}
              series={[
                { key: "success", label: "Success rate", tone: "success", values: armSuccess },
              ]}
              max={1}
              format={(value) => pct(value, 0)}
            />
          </div>
          <div className="stack">
            <div className="small faint">Harmful memory applications (lower is better)</div>
            <BarList
              items={harmfulItems}
              format={(value) => String(value)}
              emptyText="Run the benchmark to populate this chart."
            />
          </div>
        </div>
      </Card>

      <div className="grid grid-2">
        <Card title="Memory growth" subtitle="Cumulative stored lessons by creation day.">
          <LineChart points={growth} format={(value) => String(Math.round(value))} tone="accent" />
        </Card>
        <Card
          title="Most-applied lessons"
          subtitle="Top memories by number of retrievals applied."
        >
          <BarList
            items={topLessonItems}
            format={(value) => String(value)}
            emptyText="No memories applied yet."
          />
        </Card>
      </div>

      <Card title="Failure categories in memory">
        <BarList
          items={categoryItems}
          format={(value) => String(value)}
          emptyText="No memories stored yet."
        />
      </Card>
    </div>
  );
}
