"""Metric collection and aggregation for the evaluation harness.

Metrics are computed only from values the agent actually produced (attempts,
traces, retrieval results). Nothing is hard-coded or estimated.
"""

from __future__ import annotations

from backend.agent.models import TaskRun
from backend.evaluation.scenarios import Scenario


def _selected_ids(run: TaskRun) -> list[str]:
    ids: list[str] = []
    for attempt in run.attempts:
        for result in attempt.retrieved:
            if result.selected and result.memory.id not in ids:
                ids.append(result.memory.id)
    return ids


def collect_run_metrics(run: TaskRun, scenario: Scenario, *, mode: str) -> dict:
    failures = sum(1 for attempt in run.attempts if not attempt.success)
    applied = list(run.memory_ids_applied)
    harmful_applied = [mid for mid in applied if mid in scenario.harmful_memory_ids]
    return {
        "scenario_id": scenario.id,
        "scenario_name": scenario.name,
        "category": scenario.category,
        "mode": mode,
        "task": run.task,
        "success": run.final_success,
        "final_outcome": run.final_outcome.value,
        "attempts_used": len(run.attempts),
        "maximum_attempts": run.max_attempts,
        "failures": failures,
        "repeated_failure": failures > 1,
        "retries": sum(attempt.retries for attempt in run.attempts),
        "steps": sum(len(attempt.traces) for attempt in run.attempts),
        "duration_ms": sum(attempt.duration_ms for attempt in run.attempts),
        "retrieved_ids": list(run.retrieved_memory_ids),
        "selected_ids": _selected_ids(run),
        "applied_ids": applied,
        "llm_suggested_ids": list(run.llm_suggested_memory_ids),
        "harmful_applied_ids": harmful_applied,
        "prevented_failure": run.prevented_failure,
        "prevention_evidence": run.prevention_evidence,
        "memories_created": list(run.memory_ids_created),
        "memories_reinforced": list(run.memory_ids_reinforced),
        "expectation_met": _expectation_met(run, scenario, mode),
    }


def _expectation_met(run: TaskRun, scenario: Scenario, mode: str) -> bool | None:
    if mode == "memory":
        expected_success = scenario.expected_memory_success
    elif mode == "baseline":
        expected_success = scenario.expected_baseline_success
    else:
        # The naive arm has no per-scenario expectation label; its safety is
        # reported directly through harmful applications in the arms table.
        return None
    if run.final_success != expected_success:
        return False
    # Harmful memories must never be applied in either mode.
    if any(mid in scenario.harmful_memory_ids for mid in run.memory_ids_applied):
        return False
    return True


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 3)


def aggregate(per_scenario: list[dict], mode: str) -> dict:
    rows = [row for row in per_scenario if row["mode"] == mode]
    tasks = len(rows)
    successes = sum(1 for row in rows if row["success"])
    repeated = sum(1 for row in rows if row["repeated_failure"])
    prevented = sum(1 for row in rows if row["prevented_failure"])
    harmful = sum(len(row["harmful_applied_ids"]) for row in rows)
    created = sum(len(row["memories_created"]) for row in rows)
    return {
        "tasks": tasks,
        "successes": successes,
        "failures": tasks - successes,
        "success_rate": _rate(successes, tasks),
        "failure_rate": _rate(tasks - successes, tasks),
        "repeated_failure_tasks": repeated,
        "repeated_failure_rate": _rate(repeated, tasks),
        "prevented_failures": prevented,
        "harmful_memory_applications": harmful,
        "memories_created": created,
        "total_attempts": sum(row["attempts_used"] for row in rows),
        "avg_attempts": _mean([row["attempts_used"] for row in rows]),
        "total_retries": sum(row["retries"] for row in rows),
        "avg_retries": _mean([row["retries"] for row in rows]),
        "avg_steps": _mean([row["steps"] for row in rows]),
        "avg_duration_ms": _mean([row["duration_ms"] for row in rows]),
    }


def compare(baseline: dict, memory: dict, per_scenario: list[dict]) -> dict:
    fixable = [
        row for row in per_scenario if row["category"] == "fixable" and row["mode"] == "memory"
    ]
    prevented_in_fixable = sum(1 for row in fixable if row["prevented_failure"])

    def delta(a, b):
        if a is None or b is None:
            return None
        return round(b - a, 4)

    return {
        "success_rate_baseline": baseline.get("success_rate"),
        "success_rate_memory": memory.get("success_rate"),
        "success_rate_delta": delta(baseline.get("success_rate"), memory.get("success_rate")),
        "failure_rate_baseline": baseline.get("failure_rate"),
        "failure_rate_memory": memory.get("failure_rate"),
        "failure_rate_delta": delta(baseline.get("failure_rate"), memory.get("failure_rate")),
        "repeated_failure_rate_baseline": baseline.get("repeated_failure_rate"),
        "repeated_failure_rate_memory": memory.get("repeated_failure_rate"),
        "avg_attempts_baseline": baseline.get("avg_attempts"),
        "avg_attempts_memory": memory.get("avg_attempts"),
        "avg_attempts_delta": delta(baseline.get("avg_attempts"), memory.get("avg_attempts")),
        "avg_retries_baseline": baseline.get("avg_retries"),
        "avg_retries_memory": memory.get("avg_retries"),
        "avg_retries_delta": delta(baseline.get("avg_retries"), memory.get("avg_retries")),
        "avg_steps_baseline": baseline.get("avg_steps"),
        "avg_steps_memory": memory.get("avg_steps"),
        "avg_steps_delta": delta(baseline.get("avg_steps"), memory.get("avg_steps")),
        "avg_duration_ms_baseline": baseline.get("avg_duration_ms"),
        "avg_duration_ms_memory": memory.get("avg_duration_ms"),
        "avg_duration_ms_delta": delta(
            baseline.get("avg_duration_ms"), memory.get("avg_duration_ms")
        ),
        "prevented_failures": memory.get("prevented_failures"),
        "harmful_memory_applications": memory.get("harmful_memory_applications"),
        "fixable_scenarios": len(fixable),
        "fixable_scenarios_prevented": prevented_in_fixable,
        "prevention_effectiveness": _rate(prevented_in_fixable, len(fixable)),
        "incorrect_memory_effects": memory.get("harmful_memory_applications"),
    }


def arm_comparison(arms: dict[str, dict]) -> dict:
    """Side-by-side comparison of the evaluation arms (baseline/naive/memory).

    This is the research view: the ``naive`` arm retrieves and applies memories
    without validation, so its success rate and *harmful applications* show what
    the guard rails buy over applying memory blindly.
    """
    return {
        name: {
            "success_rate": arm.get("success_rate"),
            "avg_attempts": arm.get("avg_attempts"),
            "avg_retries": arm.get("avg_retries"),
            "prevented_failures": arm.get("prevented_failures"),
            "harmful_memory_applications": arm.get("harmful_memory_applications"),
            "memories_created": arm.get("memories_created"),
        }
        for name, arm in arms.items()
    }


RETRIEVAL_SCOPE = {
    "selection_event": (
        "seed_memory_preview: a read-only retrieval over the scenario's seeded memories, "
        "run before any attempt. Scored against the scenario's seed-memory labels."
    ),
    "application_event": (
        "actual_memory_run: the memory ids actually applied to plans during the memory-mode "
        "run. Only applied *seed* ids are scored; memories the run reported learning are "
        "reported separately and are never counted as false positives. An applied id that "
        "is neither seeded nor reported as learned is surfaced as an unknown (hallucinated) "
        "application."
    ),
}


def retrieval_relevance(probes: list[dict]) -> dict:
    """Precision/recall over labelled retrieval probes.

    The probe deliberately separates two *distinct* events, which must not be read
    as one retrieval:

    * **selection** is measured on the *seed-memory preview* - which seeded
      memories the retriever surfaces when the store contains only the scenario's
      seed memories. It is scored against the seed-memory labels
      (``expected_selected`` / ``expected_unselected``).
    * **application** is measured on the *actual memory-mode run* - which memory
      ids were applied to plans. Application false positives come only from the
      authoritative "must never be applied" label (``harmful_memory_ids``), and
      only seed ids are considered, so a valid memory *learned during the run* is
      expected and is never counted as a false positive. An applied id that is
      neither a seed id nor one the run reported learning is surfaced separately
      as an unknown (hallucinated) application rather than being silently ignored.

    A relevant but untrustworthy memory may be surfaced yet correctly blocked from
    application, so selection precision can legitimately be lower than application
    precision. Each probe also keeps the historical flat fields for compatibility.
    """
    app_tp = app_fp = app_fn = 0
    sel_tp = sel_fp = sel_fn = 0
    details: list[dict] = []
    for probe in probes:
        expected = set(probe["expected_selected"])
        selection_forbidden = set(probe.get("expected_unselected", []))
        # Application safety uses the authoritative "must never be applied" label,
        # not only the ids flagged as unselected candidates.
        application_forbidden = set(probe.get("harmful_memory_ids", [])) | selection_forbidden
        seed_ids = set(probe.get("seed_memory_ids", expected | selection_forbidden))

        # Selection scope: seed-memory preview only.
        selected = set(probe.get("seed_preview_selected_ids", probe.get("selected_ids", [])))
        s_tp = len(selected & expected)
        s_fp = len(selected & selection_forbidden)
        s_fn = len(expected - selected)

        # Application scope: the actual run's applied ids, restricted to seed ids so
        # that a valid memory learned during the run is never scored as a false
        # positive just because it was absent from the seed-memory preview.
        applied = set(probe.get("run_applied_ids", probe.get("applied_ids", [])))
        learned_ids = set(probe.get("run_created_ids", [])) | set(
            probe.get("run_reinforced_ids", [])
        )
        applied_seed = applied & seed_ids
        # Only ids that the run itself reported learning count as "newly learned".
        # Anything else that is neither a seed id nor a learned id is surfaced
        # separately as an unknown/hallucinated application (never a false
        # positive, since it matches no labelled seed memory).
        newly_learned_applied = applied & learned_ids
        unknown_applied = applied - seed_ids - learned_ids
        forbidden_applied = applied_seed & application_forbidden
        a_tp = len(applied_seed & expected)
        a_fp = len(forbidden_applied)
        a_fn = len(expected - applied_seed)

        app_tp += a_tp
        app_fp += a_fp
        app_fn += a_fn
        sel_tp += s_tp
        sel_fp += s_fp
        sel_fn += s_fn
        details.append(
            {
                "scenario_id": probe["scenario_id"],
                # Scope-explicit view of each event (preferred by new consumers).
                "selection": {
                    "scope": "seed_memory_preview",
                    "selected_ids": sorted(selected),
                    "expected_selected": sorted(expected),
                    "expected_unselected": sorted(selection_forbidden),
                    "true_positives": s_tp,
                    "false_positives": s_fp,
                    "false_negatives": s_fn,
                },
                "application": {
                    "scope": "actual_memory_run",
                    "applied_ids": sorted(applied),
                    "applied_seed_ids": sorted(applied_seed),
                    "newly_learned_applied_ids": sorted(newly_learned_applied),
                    "unknown_applied_ids": sorted(unknown_applied),
                    "forbidden_seed_applied_ids": sorted(forbidden_applied),
                    "true_positives": a_tp,
                    "false_positives": a_fp,
                    "false_negatives": a_fn,
                },
                # Historical flat fields, retained for existing consumers.
                "selected_ids": sorted(selected),
                "applied_ids": sorted(applied),
                "expected_selected": sorted(expected),
                "expected_unselected": sorted(selection_forbidden),
                "application_true_positives": a_tp,
                "application_false_positives": a_fp,
                "application_false_negatives": a_fn,
                "selection_true_positives": s_tp,
                "selection_false_positives": s_fp,
                "selection_false_negatives": s_fn,
            }
        )
    return {
        "scope": dict(RETRIEVAL_SCOPE),
        "probes": details,
        "application": {
            "true_positives": app_tp,
            "false_positives": app_fp,
            "false_negatives": app_fn,
            "precision": _rate(app_tp, app_tp + app_fp),
            "recall": _rate(app_tp, app_tp + app_fn),
        },
        "selection": {
            "true_positives": sel_tp,
            "false_positives": sel_fp,
            "false_negatives": sel_fn,
            "precision": _rate(sel_tp, sel_tp + sel_fp),
            "recall": _rate(sel_tp, sel_tp + sel_fn),
        },
        # Headline aliases: application is the metric that matters for safety.
        "true_positives": app_tp,
        "false_positives": app_fp,
        "false_negatives": app_fn,
        "precision": _rate(app_tp, app_tp + app_fp),
        "recall": _rate(app_tp, app_tp + app_fn),
    }


def retrieval_method_comparison(
    probes: list[dict],
    *,
    floor: float = 0.0,
    limit: int = 5,
) -> dict:
    """Precision/recall of each text-similarity method on the labelled probes.

    Selection here uses **similarity only** (no confidence/recency/feedback
    weighting) so the methods are compared on equal footing: each method ranks
    the scenario's seeded memories by its own score, keeps the top ``limit``
    scoring at or above ``floor``, and is scored against the seed-memory labels
    (``expected_selected`` / ``expected_unselected``).
    """
    method_names: set[str] = set()
    for probe in probes:
        method_names.update(probe.get("method_scores", {}).keys())

    totals: dict[str, dict[str, int]] = {
        method: {"true_positives": 0, "false_positives": 0, "false_negatives": 0}
        for method in sorted(method_names)
    }
    per_probe: list[dict] = []
    for probe in probes:
        expected = set(probe.get("expected_selected", []))
        forbidden = set(probe.get("expected_unselected", []))
        detail = {"scenario_id": probe["scenario_id"], "methods": {}}
        for method, scores in probe.get("method_scores", {}).items():
            ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
            selected = {mid for mid, score in ranked[:limit] if score >= floor}
            tp = len(selected & expected)
            fp = len(selected & forbidden)
            fn = len(expected - selected)
            totals[method]["true_positives"] += tp
            totals[method]["false_positives"] += fp
            totals[method]["false_negatives"] += fn
            detail["methods"][method] = {
                "selected_ids": sorted(selected),
                "true_positives": tp,
                "false_positives": fp,
                "false_negatives": fn,
            }
        per_probe.append(detail)

    methods: dict[str, dict] = {}
    for method, counts in totals.items():
        tp = counts["true_positives"]
        fp = counts["false_positives"]
        fn = counts["false_negatives"]
        precision = _rate(tp, tp + fp)
        recall = _rate(tp, tp + fn)
        f1 = (
            round(2 * precision * recall / (precision + recall), 4)
            if precision and recall and (precision + recall) > 0
            else None
        )
        methods[method] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            **counts,
        }
    return {
        "selection_rule": f"top {limit} by similarity, score >= {floor}",
        "probe_count": len(probes),
        "methods": methods,
        "probes": per_probe,
    }
