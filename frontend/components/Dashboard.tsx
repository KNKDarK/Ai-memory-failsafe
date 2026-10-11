"use client";

import { useEffect, useState } from "react";

import { api, API_BASE, ApiError } from "@/lib/api";
import type { ConfigResponse, HealthResponse } from "@/lib/types";

import EvaluationPanel from "./EvaluationPanel";
import MemoryPanel from "./MemoryPanel";
import MetricsHeader from "./MetricsHeader";
import OverviewPanel from "./OverviewPanel";
import RetrievalPanel from "./RetrievalPanel";
import RunPanel from "./RunPanel";
import ScenarioPanel from "./ScenarioPanel";
import { Badge, Spinner } from "./ui";

type TabId = "overview" | "run" | "scenarios" | "retrieval" | "memories" | "evaluation";

const TABS: Array<{ id: TabId; label: string }> = [
  { id: "overview", label: "Overview" },
  { id: "run", label: "Agent Sandbox" },
  { id: "scenarios", label: "Scenarios" },
  { id: "retrieval", label: "Retrieval" },
  { id: "memories", label: "Memory Bank" },
  { id: "evaluation", label: "Evaluation" },
];

export default function Dashboard() {
  const [tab, setTab] = useState<TabId>("overview");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [config, setConfig] = useState<ConfigResponse | null>(null);
  const [checking, setChecking] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    const run = async () => {
      const [healthResult, configResult] = await Promise.allSettled([
        api.health(),
        api.config(),
      ]);
      if (!active) return;
      if (healthResult.status === "fulfilled") {
        setHealth(healthResult.value);
      } else {
        setHealth({
          status: "degraded",
          memory_database_available: false,
          error:
            healthResult.reason instanceof ApiError
              ? healthResult.reason.message
              : String(healthResult.reason),
          environment: "unknown",
        });
      }
      if (configResult.status === "fulfilled") {
        setConfig(configResult.value);
      }
      setChecking(false);
    };
    void run();
    const timer = window.setInterval(() => {
      void run();
    }, 15000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [reloadKey]);

  function recheck() {
    setChecking(true);
    setReloadKey((key) => key + 1);
  }

  const online = health?.status === "ok";

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark" aria-hidden>
            ⛭
          </div>
          <div>
            <div className="brand-title">AI Agent Failure Memory</div>
            <div className="brand-sub">
              failure → cause → lesson → prevention · local &amp; offline
            </div>
          </div>
        </div>
        <div className="topbar-meta">
          <Badge tone={online ? "success" : "danger"}>
            {online ? <span className="dot" /> : <span className="dot" />}
            {online ? "backend online" : "backend degraded"}
          </Badge>
          {config && (
            <Badge tone={config.offline ? "info" : "accent"}>
              {config.offline ? "offline / deterministic" : "real LLM"}
            </Badge>
          )}
          <span className="tiny faint mono">{API_BASE}</span>
          <button className="btn ghost small" onClick={recheck}>
            {checking ? <Spinner /> : "⟳"} Recheck
          </button>
        </div>
      </header>

      <nav className="nav" aria-label="sections">
        {TABS.map((item) => (
          <button
            key={item.id}
            className={tab === item.id ? "active" : ""}
            onClick={() => setTab(item.id)}
            aria-current={tab === item.id ? "page" : undefined}
          >
            {item.label}
          </button>
        ))}
      </nav>

      <main className="content">
        <MetricsHeader />
        {tab === "overview" && <OverviewPanel health={health} config={config} />}
        {tab === "run" && <RunPanel />}
        {tab === "scenarios" && <ScenarioPanel />}
        {tab === "retrieval" && <RetrievalPanel />}
        {tab === "memories" && <MemoryPanel />}
        {tab === "evaluation" && <EvaluationPanel />}
      </main>

      <footer className="footer">
        <span>
          Offline-first &amp; deterministic by default. Tools run only against an in-memory
          sandbox; no host, network, or filesystem access.
        </span>
        <span>
          All improvement figures are measured from real runs. Scenarios are simulated and
          labelled as such.
        </span>
      </footer>
    </div>
  );
}
