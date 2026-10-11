"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { pct } from "@/lib/format";
import type { EvaluationReport, MemoryStats } from "@/lib/types";

import { Stat } from "./ui";

// A compact, always-visible strip of headline numbers for the dashboard.
//
// The spec called for "total failures analysed" and "prevented errors". Both are
// real backend counters: `/api/memories/stats` reports how many failure
// occurrences have been analysed and stored, and the evaluation report reports
// how many of those failures were demonstrably prevented. Nothing here is
// hardcoded — when the backend is unavailable the cells fall back to "—".
export default function MetricsHeader() {
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [report, setReport] = useState<EvaluationReport | null>(null);

  useEffect(() => {
    let active = true;
    const load = async () => {
      const [statsResult, reportResult] = await Promise.allSettled([
        api.memoryStats(),
        api.evaluationReport(),
      ]);
      if (!active) return;
      if (statsResult.status === "fulfilled") setStats(statsResult.value);
      if (reportResult.status === "fulfilled") setReport(reportResult.value);
    };
    void load();
    const timer = window.setInterval(() => void load(), 15000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  const prevented = report?.aggregate.memory.prevented_failures;

  return (
    <div className="metrics-header" aria-label="key metrics">
      <Stat
        label="Failures analysed"
        value={stats ? stats.total_occurrences : "—"}
        hint="failure occurrences behind the lessons"
      />
      <Stat
        label="Lessons stored"
        value={stats ? stats.total_memories : "—"}
        hint={
          stats
            ? `${stats.repeated_failure_patterns} repeated pattern${
                stats.repeated_failure_patterns === 1 ? "" : "s"
              }`
            : "distinct failure memories"
        }
      />
      <Stat
        label="Failures prevented"
        value={prevented ?? (stats ? stats.prevention_successes : "—")}
        tone="success"
        hint={
          prevented != null
            ? "measured in the evaluation benchmark"
            : "successful memory applications"
        }
      />
      <Stat
        label="Prevention success"
        value={stats ? pct(stats.prevention_success_rate) : "—"}
        tone={
          stats?.prevention_success_rate == null
            ? undefined
            : stats.prevention_success_rate >= 0.5
              ? "success"
              : "warn"
        }
        hint={stats ? `${stats.times_applied} application${stats.times_applied === 1 ? "" : "s"}` : "—"}
      />
    </div>
  );
}
