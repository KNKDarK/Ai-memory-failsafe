"""Baseline vs. memory-enabled evaluation harness.

Runs every scenario twice under identical conditions:

* **baseline** - the agent has no memory (no retrieval, no learning).
* **memory**   - the agent retrieves relevant lessons before each attempt and
  learns from failures.

Outputs a machine-readable JSON report and a readable Markdown summary. All
figures are measured from real runs; scenarios are simulated and labelled as
such. No improvement percentage is claimed beyond what the runs show.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import time
from datetime import timedelta
from pathlib import Path

from backend.agent.models import TaskRun
from backend.agent.planner import detect_task_type
from backend.config import Settings, get_settings
from backend.domain import utcnow
from backend.evaluation import metrics as metrics_mod
from backend.evaluation.scenarios import Scenario, build_scenarios
from backend.memory.lifecycle import lifecycle_report, policy_from_settings
from backend.memory.models import FailureMemory, RetrievalQuery, RetrievalResult
from backend.memory.retriever import memory_document, query_document
from backend.memory.similarity import RETRIEVAL_METHODS, method_similarities
from backend.services import Runtime, build_runtime

LIMITATIONS = [
    "Scenarios are simulated with deterministic fault injection; they stand in for "
    "real-world failures and are labelled as simulated throughout.",
    "The agent is rule-based and deterministic; it does not use a general-purpose "
    "planning model, so prevention only works for the explicit prevention vocabulary.",
    "The default retrieval similarity is a lexical hashing embedding, not a trained "
    "semantic model. It is reported as 'hashing_embedding'; a neural provider is optional.",
    "Deterministic tool durations are used for reproducibility; wall-clock time is "
    "reported separately and may vary by machine.",
    "'Prevented failures' counts attempts that succeeded after applying a memory that "
    "matched the scenario's fault category; it is a change relative to the same "
    "scenario's baseline, not a causal claim about arbitrary tasks.",
    "The retrieval method comparison ranks the scenario's seeded memories by similarity "
    "alone (no confidence/recency/feedback weights), so it isolates the text-similarity "
    "method rather than the full retriever.",
    "The retrieval method comparison runs on the small set of labelled seed-memory probes "
    "embedded in the scenarios, on which textually-related methods can tie; that tie is "
    "expected and shows the validation gates, not the choice of similarity function, are "
    "what block harmful application. A larger probe corpus would separate the methods.",
    "The 'naive' arm removes every retrieval gate to model memory applied without "
    "validation; it is a research baseline, not a recommended operating mode.",
    "Lifecycle 'projected' counts advance the clock deterministically to the retire "
    "horizon over memories created during the run; they are projections, not observed "
    "longitudinal data.",
]


def _eval_settings(base: Settings) -> Settings:
    return dataclasses.replace(base, memory_database=":memory:")


def _retrieval_mode(runtime: Runtime) -> str:
    if runtime.embedder is None:
        return "tfidf_fallback"
    if runtime.embedder.name.startswith("openai"):
        return "neural_embedding"
    return "hashing_embedding"


class Benchmark:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    # ------------------------------------------------------------------ #
    def _run_mode(self, scenario: Scenario, mode: str) -> tuple[dict, Runtime]:
        runtime = build_runtime(_eval_settings(self.settings))
        for memory in scenario.seed_memories:
            runtime.store.save(memory)
        agent = runtime.agent()
        env = scenario.environment.clone()
        started = time.perf_counter()
        run = agent.run_task(scenario.task, env, mode=mode, max_attempts=scenario.max_attempts)
        wall_clock_ms = round((time.perf_counter() - started) * 1000, 3)
        row = metrics_mod.collect_run_metrics(run, scenario, mode=mode)
        row["wall_clock_ms"] = wall_clock_ms
        return row, runtime

    def _probe(self, scenario: Scenario, memory_row: dict) -> dict | None:
        """Build one retrieval-relevance probe for a scenario.

        The probe records **two distinct events** that must never be conflated:

        * ``seed_preview_selected_ids`` - what the retriever surfaces in a
          read-only preview over the scenario's *seeded* memories only.
        * ``run_applied_ids`` - which memory ids the real memory-mode run applied
          to its plans. This set may contain memories *learned during the run*,
          which were never present in the seed preview.

        Returns ``None`` when the scenario has no seeded memories, because then
        there is nothing to label at retrieval time.
        """
        if not scenario.seed_memories:
            return None
        runtime = build_runtime(_eval_settings(self.settings))
        for memory in scenario.seed_memories:
            runtime.store.save(memory)
        agent = runtime.agent()
        results = agent.preview_retrieval(scenario.task, scenario.environment.clone())
        selected = [r.memory.id for r in results if r.selected]

        # Similarity-only comparison data for the retrieval study. This is kept
        # independent of the ranker's confidence/recency/feedback weights so the
        # text-similarity methods are compared on equal footing.
        plan = runtime.planner.plan(scenario.task, scenario.environment.clone())
        tools = [step.tool for step in plan.steps]
        query_text = query_document(
            RetrievalQuery(
                text=scenario.task,
                task_type=detect_task_type(scenario.task),
                action=tools[0] if tools else None,
            )
        )
        documents = [memory_document(memory) for memory in scenario.seed_memories]
        method_scores: dict[str, dict[str, float]] = {}
        for method in RETRIEVAL_METHODS:
            scores, _label = method_similarities(
                method, query_text, documents, embedder=runtime.embedder
            )
            method_scores[method] = {
                memory.id: round(score, 6)
                for memory, score in zip(scenario.seed_memories, scores, strict=True)
            }

        return {
            "scenario_id": scenario.id,
            "seed_memory_ids": [memory.id for memory in scenario.seed_memories],
            "query_text": query_text,
            # Selection event (seed-memory preview only).
            "seed_preview_selected_ids": selected,
            "expected_selected": list(scenario.expect_retrieval_of),
            "expected_unselected": list(scenario.expect_no_retrieval_of),
            # Application event (the actual memory-mode run).
            "run_applied_ids": list(memory_row["applied_ids"]),
            "run_created_ids": list(memory_row["memories_created"]),
            "run_reinforced_ids": list(memory_row["memories_reinforced"]),
            "harmful_memory_ids": list(scenario.harmful_memory_ids),
            # Per-method similarity scores for the retrieval comparison study.
            "method_scores": method_scores,
        }

    def run(self, scenario_ids: list[str] | None = None) -> dict:
        scenarios = build_scenarios()
        if scenario_ids:
            wanted = set(scenario_ids)
            scenarios = [s for s in scenarios if s.id in wanted]

        per_scenario_rows: list[dict] = []
        comparison_rows: list[dict] = []
        probes: list[dict] = []
        retrieval_mode = "tfidf_fallback"
        lifecycle_memories: dict[str, FailureMemory] = {}

        for scenario in scenarios:
            baseline_row, _ = self._run_mode(scenario, "baseline")
            naive_row, _ = self._run_mode(scenario, "naive")
            memory_row, memory_runtime = self._run_mode(scenario, "memory")
            per_scenario_rows.extend([baseline_row, naive_row, memory_row])
            retrieval_mode = _retrieval_mode(memory_runtime)
            for memory in memory_runtime.store.list(include_inactive=True):
                lifecycle_memories[memory.id] = memory

            probe = self._probe(scenario, memory_row)
            if probe is not None:
                probes.append(probe)

            comparison_rows.append(
                {
                    "scenario_id": scenario.id,
                    "name": scenario.name,
                    "category": scenario.category,
                    "description": scenario.description,
                    "simulated": scenario.simulated,
                    "notes": scenario.notes,
                    "expected": {
                        "baseline_success": scenario.expected_baseline_success,
                        "memory_success": scenario.expected_memory_success,
                        "prevention_expected": scenario.expect_prevention,
                    },
                    "baseline": baseline_row,
                    "naive": naive_row,
                    "memory": memory_row,
                    "prevention_evidence": memory_row["prevention_evidence"],
                }
            )

        baseline = metrics_mod.aggregate(per_scenario_rows, "baseline")
        naive = metrics_mod.aggregate(per_scenario_rows, "naive")
        memory = metrics_mod.aggregate(per_scenario_rows, "memory")
        arms = metrics_mod.arm_comparison({"baseline": baseline, "naive": naive, "memory": memory})
        comparison = metrics_mod.compare(baseline, memory, per_scenario_rows)
        relevance = metrics_mod.retrieval_relevance(probes)
        method_comparison = metrics_mod.retrieval_method_comparison(
            probes,
            floor=self.settings.retrieval_min_similarity,
            limit=self.settings.retrieval_limit,
        )
        lifecycle = self._lifecycle_section(list(lifecycle_memories.values()))

        expectations_met = sum(
            1
            for row in comparison_rows
            if row["baseline"]["expectation_met"] and row["memory"]["expectation_met"]
        )

        report = {
            "schema_version": 1,
            "generated_at": utcnow().isoformat(),
            "simulated": True,
            "retrieval_mode": retrieval_mode,
            "settings": {
                "llm_provider": self.settings.llm_provider,
                "llm_real": self.settings.llm_enabled,
                "embedding_provider": self.settings.embedding_provider,
                "retrieval_limit": self.settings.retrieval_limit,
                "retrieval_min_score": self.settings.retrieval_min_score,
                "retrieval_min_similarity": self.settings.retrieval_min_similarity,
                "retrieval_method": self.settings.retrieval_method,
                "min_confidence_to_apply": self.settings.min_confidence_to_apply,
                "lifecycle": {
                    "stale_after_days": self.settings.lifecycle_stale_after_days,
                    "retire_after_days": self.settings.lifecycle_retire_after_days,
                    "obsolete_failure_ratio": self.settings.lifecycle_obsolete_failure_ratio,
                    "min_uses_for_obsolete": self.settings.lifecycle_min_uses_for_obsolete,
                },
            },
            "scenario_count": len(scenarios),
            "scenarios_expectations_met": expectations_met,
            "scenarios": comparison_rows,
            "aggregate": {"baseline": baseline, "naive": naive, "memory": memory},
            "arms": arms,
            "comparison": comparison,
            "retrieval_relevance": relevance,
            "retrieval_method_comparison": method_comparison,
            "lifecycle": lifecycle,
            "methodology": {
                "modes": {
                    "baseline": "no retrieval, no learning",
                    "naive": "retrieve + apply everything, no validation (research arm)",
                    "memory": "retrieve + validate + apply + learn + feedback",
                },
                "same_conditions": (
                    "Each scenario reuses the identical task, environment clone, and attempt "
                    "budget for all arms; only memory availability/validation differs."
                ),
                "prevention_definition": (
                    "A run is a 'prevented failure' when an attempt after the first succeeds "
                    "and at least one retrieved memory was applied to the plan."
                ),
                "retrieval_method_comparison": (
                    "Similarity-only precision/recall/F1 of each text-similarity method on the "
                    "labelled seed-memory probes (no ranker weights applied)."
                ),
                "lifecycle": (
                    "Lifecycle labels are derived deterministically from memory age and observed "
                    "application outcomes; 'projected' advances the clock to the retire horizon."
                ),
                "attempt_budget": "Per-scenario max_attempts, identical in all arms.",
            },
            "limitations": LIMITATIONS,
        }
        return report

    def _lifecycle_section(self, memories: list[FailureMemory]) -> dict:
        """Deterministic lifecycle counts for the memories produced by the run.

        ``at_run`` labels memories at the moment the benchmark finished;
        ``projected`` labels the very same memories after advancing the clock to
        the retire horizon, showing what the policy *would* retire. Both are
        derived from real memory records (no synthetic scores).
        """
        policy = policy_from_settings(self.settings)
        now = utcnow()
        at_run = lifecycle_report(memories, now=now, policy=policy)
        horizon = int(policy.retire_after_days) + 1
        projected = lifecycle_report(memories, now=now + timedelta(days=horizon), policy=policy)

        def counts(report: dict) -> dict:
            return {
                "total": report["total"],
                "active": report["active"],
                "counts": report["counts"],
                "stale": report["stale"],
                "obsolete": report["obsolete"],
                "expired": report["expired"],
                "planned_transitions": len(report["planned_transitions"]),
            }

        return {
            "unique_memories": len({memory.id for memory in memories}),
            "at_run": counts(at_run),
            "projected": {"horizon_days": horizon, **counts(projected)},
        }


# --------------------------------------------------------------------------- #
# Single-scenario detail run (used by the API demo endpoint)
# --------------------------------------------------------------------------- #
@dataclasses.dataclass
class ScenarioRunDetail:
    """A self-contained baseline + memory run of one scenario (isolated store)."""

    scenario: Scenario
    baseline_run: TaskRun
    memory_run: TaskRun
    probe: list[RetrievalResult]
    baseline_metrics: dict
    memory_metrics: dict
    memory_stats_before: dict
    memory_stats_after: dict
    seeded_memory_ids: list[str]


def run_scenario_detail(settings: Settings, scenario: Scenario) -> ScenarioRunDetail:
    """Run one scenario in both modes on an isolated in-memory store.

    Baseline first (no retrieval, no learning), then memory mode on a fresh
    store where the agent may learn across attempts. Both modes see an identical
    environment clone and attempt budget, so the only difference is memory.
    """
    baseline_runtime = build_runtime(_eval_settings(settings))
    baseline_run = baseline_runtime.agent().run_task(
        scenario.task,
        scenario.environment.clone(),
        mode="baseline",
        max_attempts=scenario.max_attempts,
    )
    baseline_metrics = metrics_mod.collect_run_metrics(baseline_run, scenario, mode="baseline")

    memory_runtime = build_runtime(_eval_settings(settings))
    seeded_memory_ids: list[str] = []
    for memory in scenario.seed_memories:
        memory_runtime.store.save(memory)
        seeded_memory_ids.append(memory.id)
    memory_stats_before = memory_runtime.store.stats()
    memory_run = memory_runtime.agent().run_task(
        scenario.task,
        scenario.environment.clone(),
        mode="memory",
        max_attempts=scenario.max_attempts,
    )
    memory_stats_after = memory_runtime.store.stats()
    memory_metrics = metrics_mod.collect_run_metrics(memory_run, scenario, mode="memory")

    probe_runtime = build_runtime(_eval_settings(settings))
    for memory in scenario.seed_memories:
        probe_runtime.store.save(memory)
    probe = probe_runtime.agent().preview_retrieval(scenario.task, scenario.environment.clone())

    return ScenarioRunDetail(
        scenario=scenario,
        baseline_run=baseline_run,
        memory_run=memory_run,
        probe=probe,
        baseline_metrics=baseline_metrics,
        memory_metrics=memory_metrics,
        memory_stats_before=memory_stats_before,
        memory_stats_after=memory_stats_after,
        seeded_memory_ids=seeded_memory_ids,
    )


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _num(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def format_markdown(report: dict) -> str:
    baseline = report["aggregate"]["baseline"]
    memory = report["aggregate"]["memory"]
    comparison = report["comparison"]
    lines: list[str] = []
    lines.append("# AI Agent Failure Memory — Evaluation Report")
    lines.append("")
    lines.append(f"Generated: {report['generated_at']}")
    lines.append(f"Simulated scenarios: {report['scenario_count']} (all runs are simulated)")
    lines.append(f"Retrieval mode: {report['retrieval_mode']}")
    lines.append(
        f"LLM provider: {report['settings']['llm_provider']} (real model: {report['settings']['llm_real']})"
    )
    lines.append("")
    lines.append("## Baseline vs memory-enabled")
    lines.append("")
    lines.append("| Metric | Baseline | Memory-enabled | Δ |")
    lines.append("| --- | --- | --- | --- |")
    lines.append(
        f"| Success rate | {_pct(baseline['success_rate'])} | {_pct(memory['success_rate'])} | {_pct(comparison['success_rate_delta'])} |"
    )
    lines.append(
        f"| Failure rate | {_pct(baseline['failure_rate'])} | {_pct(memory['failure_rate'])} | {_pct(comparison['failure_rate_delta'])} |"
    )
    lines.append(
        f"| Repeated-failure rate | {_pct(baseline['repeated_failure_rate'])} | {_pct(memory['repeated_failure_rate'])} | |"
    )
    lines.append(
        f"| Avg attempts | {_num(baseline['avg_attempts'])} | {_num(memory['avg_attempts'])} | {_num(comparison['avg_attempts_delta'])} |"
    )
    lines.append(
        f"| Avg retries | {_num(baseline['avg_retries'])} | {_num(memory['avg_retries'])} | {_num(comparison['avg_retries_delta'])} |"
    )
    lines.append(
        f"| Avg steps | {_num(baseline['avg_steps'])} | {_num(memory['avg_steps'])} | {_num(comparison['avg_steps_delta'])} |"
    )
    lines.append(
        f"| Prev. failures prevented | {baseline['prevented_failures']} | {memory['prevented_failures']} | {comparison['prevented_failures']} |"
    )
    lines.append(
        f"| Memories created | {baseline['memories_created']} | {memory['memories_created']} | |"
    )
    lines.append(
        f"| Harmful memory applications | {baseline['harmful_memory_applications']} | {memory['harmful_memory_applications']} | |"
    )
    lines.append("")
    lines.append(
        f"Prevention effectiveness on fixable scenarios: {_pct(comparison['prevention_effectiveness'])}"
    )
    lines.append(f"({comparison['fixable_scenarios_prevented']}/{comparison['fixable_scenarios']})")
    lines.append("")
    lines.append("## Evaluation arms (baseline / naive / validated memory)")
    lines.append("")
    lines.append(
        "The **naive** arm retrieves and applies every memory with no validation "
        "(no status, confidence, relevance, or contradiction gating). Comparing it to "
        "the validated **memory** arm isolates what the guard rails contribute: harmful "
        "applications should fall while prevention is retained."
    )
    lines.append("")
    lines.append("| Arm | Success rate | Avg retries | Prevented failures | Harmful applications |")
    lines.append("| --- | --- | --- | --- | --- |")
    arms = report.get("arms", {})
    for key, label in (
        ("baseline", "Baseline (no memory)"),
        ("naive", "Naive memory"),
        ("memory", "Validated memory"),
    ):
        arm = arms.get(key, {})
        lines.append(
            f"| {label} | {_pct(arm.get('success_rate'))} | {_num(arm.get('avg_retries'))} "
            f"| {arm.get('prevented_failures', 0)} | {arm.get('harmful_memory_applications', 0)} |"
        )
    lines.append("")
    lines.append("## Retrieval relevance")
    lines.append("")
    relevance = report["retrieval_relevance"]
    application = relevance["application"]
    selection = relevance["selection"]
    lines.append(
        "Two measurements are reported over two **different events**. "
        "**Selection** is measured on a read-only *seed-memory preview*: which of "
        "the scenario's seeded memories the retriever surfaces before any run. "
        "**Application** is measured on the *actual memory-mode run*: which memory "
        "ids were applied to plans. Application false positives count only seeded "
        "memories labelled as never-applicable, so a valid memory *learned during "
        "the run* is reported separately and is never counted as a false positive; "
        "an applied id that is neither seeded nor reported as learned is surfaced as "
        "an unknown (hallucinated) application. "
        "A relevant but untrustworthy memory may be surfaced yet correctly blocked "
        "from application, so selection precision can be lower than application "
        "precision."
    )
    lines.append("")
    lines.append("| Metric | Precision | Recall | TP | FP | FN |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    lines.append(
        f"| Application | {_pct(application['precision'])} | {_pct(application['recall'])} "
        f"| {application['true_positives']} | {application['false_positives']} "
        f"| {application['false_negatives']} |"
    )
    lines.append(
        f"| Selection | {_pct(selection['precision'])} | {_pct(selection['recall'])} "
        f"| {selection['true_positives']} | {selection['false_positives']} "
        f"| {selection['false_negatives']} |"
    )
    lines.append("")
    lines.append("## Retrieval method comparison (similarity only)")
    lines.append("")
    method_comparison = report.get("retrieval_method_comparison", {})
    lines.append(
        f"Selection rule: {method_comparison.get('selection_rule', 'n/a')} over "
        f"{method_comparison.get('probe_count', 0)} labelled seed-memory probes. "
        "Ranking uses similarity alone (no confidence/recency/feedback weights), so "
        "this isolates the text-similarity method."
    )
    lines.append("")
    lines.append("| Method | Precision | Recall | F1 | TP | FP | FN |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for method, metrics in method_comparison.get("methods", {}).items():
        lines.append(
            f"| {method} | {_pct(metrics['precision'])} | {_pct(metrics['recall'])} "
            f"| {_pct(metrics['f1'])} | {metrics['true_positives']} "
            f"| {metrics['false_positives']} | {metrics['false_negatives']} |"
        )
    lines.append("")
    lines.append("## Memory lifecycle")
    lines.append("")
    lifecycle = report.get("lifecycle", {})
    at_run = lifecycle.get("at_run", {})
    projected = lifecycle.get("projected", {})
    lines.append(
        f"{lifecycle.get('unique_memories', 0)} unique memories were observed over the run. "
        "Labels (fresh/stale/obsolete/expired) are derived deterministically from memory "
        "age and observed application outcomes."
    )
    lines.append("")
    lines.append("| View | Fresh | Stale | Obsolete | Expired | Total |")
    lines.append("| --- | --- | --- | --- | --- | --- |")

    def _lifecycle_counts(view: dict) -> tuple[int, int, int, int, int]:
        counts = view.get("counts", {})
        return (
            counts.get("fresh", 0),
            counts.get("stale", 0),
            counts.get("obsolete", 0),
            counts.get("expired", 0),
            view.get("total", 0),
        )

    fresh, stale, obsolete, expired, total = _lifecycle_counts(at_run)
    lines.append(f"| At run | {fresh} | {stale} | {obsolete} | {expired} | {total} |")
    fresh, stale, obsolete, expired, total = _lifecycle_counts(projected)
    lines.append(
        f"| Projected (+{projected.get('horizon_days', '?')}d) "
        f"| {fresh} | {stale} | {obsolete} | {expired} | {total} |"
    )
    lines.append("")
    lines.append("## Per-scenario results")
    lines.append("")
    lines.append("| Scenario | Category | Baseline | Memory | Prevented | Expectation met |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for row in report["scenarios"]:
        b = "✅" if row["baseline"]["success"] else "❌"
        m = "✅" if row["memory"]["success"] else "❌"
        prevented = "yes" if row["memory"]["prevented_failure"] else "no"
        met = (
            "✅"
            if (row["baseline"]["expectation_met"] and row["memory"]["expectation_met"])
            else "⚠️"
        )
        lines.append(f"| {row['name']} | {row['category']} | {b} | {m} | {prevented} | {met} |")
    lines.append("")
    lines.append("## Methodology")
    lines.append("")
    for key, value in report["methodology"].items():
        lines.append(f"- **{key}**: {value}")
    lines.append("")
    lines.append("## Limitations")
    lines.append("")
    for limitation in report["limitations"]:
        lines.append(f"- {limitation}")
    lines.append("")
    return "\n".join(lines)


def write_report(report: dict, path: str | Path) -> Path:
    target = Path(path)
    if target.parent and str(target.parent) not in {"", "."}:
        target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2))
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the failure-memory evaluation benchmark")
    parser.add_argument("--output", default=None, help="Path for the JSON report")
    parser.add_argument("--json-only", action="store_true", help="Print only the JSON report")
    parser.add_argument("--scenarios", nargs="*", default=None, help="Subset of scenario ids")
    args = parser.parse_args(argv)

    settings = get_settings()
    report = Benchmark(settings).run(args.scenarios)
    output = args.output or settings.evaluation_report_path
    path = write_report(report, output)

    if args.json_only:
        print(json.dumps(report, indent=2))
    else:
        print(format_markdown(report))
        print(f"\nJSON report written to: {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
