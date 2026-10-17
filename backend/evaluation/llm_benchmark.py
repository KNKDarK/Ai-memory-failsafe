"""Real-LLM evaluation benchmark (baseline / naive / validated-memory arms).

Runs the same scenarios as the deterministic benchmark through a configured
LLM provider in three comparable modes:

* **baseline** - no retrieval, no learning; the model plans from scratch.
* **naive**    - the model sees *unfiltered* retrieved memories (research arm
  that isolates what the trust gates contribute; it never bypasses tool
  allowlisting, authorization, or input validation).
* **memory**   - the model sees only memories that passed the retrieval trust
  gates; the deterministic controller still decides what is actually applied.

Honesty rules (differing from the deterministic benchmark):

* Without a *real* provider the run is **skipped** and reported as such -
  no metrics are fabricated.
* If the model endpoint fails for every call, the run is **aborted** and the
  report says so, instead of silently reporting rule-based results.
* Model call counts, errors, token usage, and latency are measured and
  reported; scenarios are simulated (labelled) and never presented as
  real-world tasks.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import re
import statistics
import time
import uuid
from pathlib import Path

from backend.agent.agent import FailureMemoryAgent
from backend.agent.planner import TaskPlanner
from backend.config import Settings, get_settings
from backend.domain import utcnow
from backend.evaluation import metrics as metrics_mod
from backend.evaluation.scenarios import Scenario, build_scenarios
from backend.llm.planner import LLMTaskPlanner
from backend.llm.provider import make_llm_provider
from backend.resources import detect_resources
from backend.services import build_runtime

logger = logging.getLogger("failure_memory.evaluation.llm")

BENCHMARK_VERSION = "llm-benchmark/1"
ARM_MODES = ("baseline", "naive", "memory")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

LIMITATIONS = [
    "Scenarios are simulated with deterministic fault injection; only the "
    "model's planning is real.",
    "Model output is validated (JSON schema + tool allowlist) before it can "
    "influence execution; the deterministic trust gates, not the model, "
    "decide which memories are applied.",
    "Generation settings (temperature, seed) improve reproducibility but "
    "most runtimes are not bit-exact; treat single-run differences of one "
    "scenario as noise.",
    "The sample of scenarios is small; aggregate differences of a few "
    "percentage points are not causal evidence.",
]


def _eval_settings(base: Settings) -> Settings:
    return dataclasses.replace(base, memory_database=":memory:")


class _InstrumentedProvider:
    """Wraps a provider to count calls/errors and collect tokens/latency.

    The benchmark reports these numbers directly, so a run where the model
    silently fell back to the rule-based planner is visible in the report
    (``model_call_errors`` > 0) instead of being presented as model output.
    """

    def __init__(self, inner) -> None:
        self._inner = inner
        self.name = getattr(inner, "name", "unknown")
        self.is_real = bool(getattr(inner, "is_real", False))
        self.calls = 0
        self.errors = 0
        self.error_samples: list[str] = []
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.latencies_ms: list[int] = []

    def complete(self, prompt: str, system: str | None = None) -> str:
        self.calls += 1
        try:
            text = self._inner.complete(prompt, system)
        except Exception as exc:  # noqa: BLE001 - counting every failure
            self._note_error(exc)
            raise
        self._note_success()
        return text

    def complete_json(self, prompt: str, system: str | None = None) -> dict:
        self.calls += 1
        try:
            data = self._inner.complete_json(prompt, system)
        except Exception as exc:  # noqa: BLE001 - counting every failure
            self._note_error(exc)
            raise
        self._note_success()
        return data

    def _note_error(self, exc: Exception) -> None:
        self.errors += 1
        if len(self.error_samples) < 5:
            self.error_samples.append(f"{type(exc).__name__}: {exc}"[:200])

    def _note_success(self) -> None:
        usage = getattr(self._inner, "usage", None)
        if isinstance(usage, dict):
            self.prompt_tokens += int(usage.get("prompt_tokens") or 0)
            self.completion_tokens += int(usage.get("completion_tokens") or 0)
        latency = getattr(self._inner, "last_latency_ms", None)
        if isinstance(latency, int):
            self.latencies_ms.append(latency)

    def record_invalid_output(self, exc: Exception) -> None:
        """Count a delivered-but-unusable model response (schema mismatch)."""
        self.errors += 1
        if len(self.error_samples) < 5:
            self.error_samples.append(f"invalid output: {type(exc).__name__}"[:200])

    def stats(self) -> dict:
        total_latency_ms = sum(self.latencies_ms)
        tokens_per_second = None
        if self.completion_tokens and total_latency_ms:
            tokens_per_second = round(self.completion_tokens / (total_latency_ms / 1000), 2)
        return {
            "model_calls": self.calls,
            "model_call_errors": self.errors,
            "model_error_samples": list(self.error_samples),
            "prompt_tokens": self.prompt_tokens or None,
            "completion_tokens": self.completion_tokens or None,
            "avg_latency_ms": (
                round(total_latency_ms / len(self.latencies_ms), 1) if self.latencies_ms else None
            ),
            "max_latency_ms": max(self.latencies_ms) if self.latencies_ms else None,
            "tokens_per_second": tokens_per_second,
        }


class LLMBenchmark:
    """Benchmark that uses a real LLM for planning decisions."""

    def __init__(self, settings: Settings | None = None, provider=None) -> None:
        self.settings = settings or get_settings()
        self.provider = provider if provider is not None else make_llm_provider(self.settings)
        self._is_real = bool(getattr(self.provider, "is_real", False))
        self._instrumented = _InstrumentedProvider(self.provider)
        self._run_id = uuid.uuid4().hex[:12]
        self._output_dir = Path(self.settings.llm_benchmark_output_dir)

    # ------------------------------------------------------------------ #
    def _make_planner(self) -> TaskPlanner:
        if self._is_real:
            return LLMTaskPlanner(self._instrumented)
        return TaskPlanner()

    def _run_mode(self, scenario: Scenario, mode: str, repetition: int) -> dict:
        """Run one scenario in one mode on an isolated in-memory store."""
        runtime = build_runtime(_eval_settings(self.settings))
        try:
            for memory in scenario.seed_memories:
                runtime.store.save(memory)
            agent = FailureMemoryAgent(
                runtime.store,
                runtime.settings,
                analyzer=runtime.analyzer,
                planner=self._make_planner(),
                executor=runtime.executor,
                retriever=runtime.retriever,
            )
            started = time.perf_counter()
            run = agent.run_task(
                scenario.task,
                scenario.environment.clone(),
                mode=mode,
                max_attempts=scenario.max_attempts,
            )
            wall_clock_ms = round((time.perf_counter() - started) * 1000, 3)
            row = metrics_mod.collect_run_metrics(run, scenario, mode=mode)
            row["wall_clock_ms"] = wall_clock_ms
            row["repetition"] = repetition
            return row
        finally:
            runtime.store.close()

    def _probe(self, scenario: Scenario, memory_row: dict) -> dict | None:
        """Build one retrieval-relevance probe (seed preview vs actual run)."""
        if not scenario.seed_memories:
            return None
        runtime = build_runtime(_eval_settings(self.settings))
        try:
            for memory in scenario.seed_memories:
                runtime.store.save(memory)
            results = runtime.agent().preview_retrieval(scenario.task, scenario.environment.clone())
            selected = [r.memory.id for r in results if r.selected]
        finally:
            runtime.store.close()
        return {
            "scenario_id": scenario.id,
            "seed_memory_ids": [m.id for m in scenario.seed_memories],
            "seed_preview_selected_ids": selected,
            "expected_selected": list(scenario.expect_retrieval_of),
            "expected_unselected": list(scenario.expect_no_retrieval_of),
            "run_applied_ids": list(memory_row["applied_ids"]),
            "run_created_ids": list(memory_row["memories_created"]),
            "run_reinforced_ids": list(memory_row["memories_reinforced"]),
            "harmful_memory_ids": list(scenario.harmful_memory_ids),
        }

    @staticmethod
    def _hardware() -> dict:
        snapshot = detect_resources()
        return {
            "cpu_count": snapshot.cpu_count,
            "memory_total_bytes": snapshot.memory_total_bytes,
            "memory_available_bytes": snapshot.memory_available_bytes,
            "gpu_available": snapshot.gpu_available,
            "gpu_name": snapshot.gpu_name,
        }

    def _model_info(self) -> dict:
        describe = getattr(self.provider, "describe", None)
        if callable(describe):
            try:
                info = describe()
                if isinstance(info, dict):
                    return info
            except Exception:  # noqa: BLE001 - metadata is best-effort only
                pass
        return {"provider": getattr(self.provider, "name", "unknown")}

    # ------------------------------------------------------------------ #
    def _base_report(self, status: str) -> dict:
        return {
            "schema_version": 2,
            "benchmark_version": BENCHMARK_VERSION,
            "run_id": self._run_id,
            "generated_at": utcnow().isoformat(),
            "status": status,
            "scenarios_simulated": True,
            "model_real": self._is_real,
            # Kept for compatibility with earlier consumers:
            "llm_enabled": self._is_real,
            "deterministic_fallback": not self._is_real,
            "llm_provider": getattr(self.provider, "name", "unknown"),
            "llm_model": self.settings.llm_model,
            "model_info": self._model_info(),
            "settings": {
                "llm_provider": self.settings.llm_provider,
                "llm_model": self.settings.llm_model,
                "llm_base_url": self.settings.llm_base_url,
                "llm_timeout_seconds": self.settings.llm_timeout_seconds,
                "llm_max_tokens": self.settings.llm_max_tokens,
                "llm_temperature": self.settings.llm_temperature,
                "llm_seed": self.settings.llm_seed,
                "llm_context_length": self.settings.llm_context_length,
                "llm_disable_thinking": self.settings.llm_disable_thinking,
                "embedding_provider": self.settings.embedding_provider,
                "retrieval_limit": self.settings.retrieval_limit,
                "retrieval_min_score": self.settings.retrieval_min_score,
                "retrieval_min_similarity": self.settings.retrieval_min_similarity,
                "min_confidence_to_apply": self.settings.min_confidence_to_apply,
                "benchmark_output_dir": str(self._output_dir),
            },
        }

    def _skipped_report(self, error: str) -> dict:
        report = self._base_report("skipped")
        report.update(
            {
                "error": error,
                "scenario_count": 0,
                "modes": [],
                "repetitions": 0,
                "scenarios": [],
                "aggregate": None,
                "arms": None,
                "comparison": None,
                "retrieval_relevance": None,
                "repetition_variance": None,
                "model_stats": self._instrumented.stats(),
                "methodology": {"modes": list(ARM_MODES)},
                "limitations": LIMITATIONS,
            }
        )
        return report

    @staticmethod
    def _variance(rows: dict[str, list[dict]], repetitions: int) -> dict | None:
        if repetitions < 2:
            return None
        result: dict[str, dict] = {}
        for mode, mode_rows in rows.items():
            by_rep: dict[int, list[bool]] = {}
            for row in mode_rows:
                by_rep.setdefault(row["repetition"], []).append(bool(row["success"]))
            rates = [
                sum(1 for v in values if v) / len(values)
                for _, values in sorted(by_rep.items())
                if values
            ]
            result[mode] = {
                "success_rate_by_repetition": [round(rate, 4) for rate in rates],
                "success_rate_std": round(statistics.pstdev(rates), 4) if len(rates) > 1 else 0.0,
            }
        return result

    # ------------------------------------------------------------------ #
    def run(
        self,
        scenario_ids: list[str] | None = None,
        repetitions: int = 1,
        modes: list[str] | None = None,
    ) -> dict:
        """Run the LLM benchmark; the report always states what really happened."""
        selected_modes = [m for m in (modes or ARM_MODES) if m in ARM_MODES] or list(ARM_MODES)
        repetitions = max(1, int(repetitions))

        if not self._is_real:
            logger.warning("No real LLM provider configured; benchmark run is skipped")
            report = self._skipped_report(
                "no real LLM provider is configured; set LLM_PROVIDER "
                "('llama.cpp', 'ollama', or 'openai') and a reachable endpoint. "
                "No metrics were produced - nothing is fabricated without a model."
            )
            report["modes"] = selected_modes
            return report

        scenarios = build_scenarios()
        if scenario_ids:
            wanted = set(scenario_ids)
            scenarios = [s for s in scenarios if s.id in wanted]
        if not scenarios:
            report = self._skipped_report("no scenarios matched the requested ids")
            report["modes"] = selected_modes
            return report

        rows: dict[str, list[dict]] = {mode: [] for mode in selected_modes}
        comparison_rows: list[dict] = []
        probes: list[dict] = []
        error: str | None = None

        hardware_start = self._hardware()
        total_start = time.perf_counter()

        for scenario in scenarios:
            scenario_rows: dict[str, dict] = {}
            for repetition in range(1, repetitions + 1):
                for mode in selected_modes:
                    row = self._run_mode(scenario, mode, repetition)
                    rows[mode].append(row)
                    if repetition == 1:
                        scenario_rows[mode] = row
            memory_row = scenario_rows.get("memory")
            if memory_row is not None:
                probe = self._probe(scenario, memory_row)
                if probe is not None:
                    probes.append(probe)
            entry = {
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
                "prevention_evidence": (memory_row or {}).get("prevention_evidence"),
                # All repetitions per mode, for variance inspection and traces.
                "repetition_results": {
                    mode: [r for r in rows[mode] if r["scenario_id"] == scenario.id]
                    for mode in selected_modes
                },
            }
            for mode in selected_modes:
                entry[mode] = scenario_rows.get(mode)
            comparison_rows.append(entry)

            stats = self._instrumented
            if stats.errors and not stats.latencies_ms:
                # Every model call so far failed: abort instead of reporting
                # rule-based behaviour as if it were model behaviour.
                first = stats.error_samples[0] if stats.error_samples else "unknown error"
                error = (
                    f"the model endpoint failed for all {stats.errors} call(s); "
                    f"first failure: {first}"
                )
                logger.error("LLM benchmark aborted: %s", error)
                break

        total_duration = time.perf_counter() - total_start
        hardware_end = self._hardware()

        if error is not None:
            report = self._base_report("aborted")
            report.update(
                {
                    "error": error,
                    "scenario_count": len(scenarios),
                    "modes": selected_modes,
                    "repetitions": repetitions,
                    "scenarios": comparison_rows,
                    "aggregate": None,
                    "arms": None,
                    "comparison": None,
                    "retrieval_relevance": None,
                    "repetition_variance": None,
                    "model_stats": self._instrumented.stats(),
                    "hardware": {"start": hardware_start, "end": hardware_end},
                    "timing": {"total_duration_seconds": round(total_duration, 2)},
                    "methodology": {"modes": {m: _MODE_DOC[m] for m in selected_modes}},
                    "limitations": LIMITATIONS,
                }
            )
            return report

        aggregates = {mode: metrics_mod.aggregate(rows[mode], mode) for mode in selected_modes}
        arms = metrics_mod.arm_comparison(aggregates)
        comparison = None
        if "baseline" in selected_modes and "memory" in selected_modes:
            comparison = metrics_mod.compare(
                aggregates["baseline"],
                aggregates["memory"],
                rows["baseline"] + rows["memory"],
            )
        relevance = metrics_mod.retrieval_relevance(probes)

        report = self._base_report("completed")
        report.update(
            {
                "scenario_count": len(scenarios),
                "modes": selected_modes,
                "repetitions": repetitions,
                "scenarios": comparison_rows,
                "aggregate": aggregates,
                "arms": arms,
                "comparison": comparison,
                "retrieval_relevance": relevance,
                "repetition_variance": self._variance(rows, repetitions),
                "model_stats": self._instrumented.stats(),
                "hardware": {"start": hardware_start, "end": hardware_end},
                "timing": {
                    "total_duration_seconds": round(total_duration, 2),
                    "avg_scenario_duration_seconds": round(
                        total_duration / max(len(scenarios), 1), 2
                    ),
                },
                "methodology": {
                    "modes": {m: _MODE_DOC[m] for m in selected_modes},
                    "same_conditions": (
                        "Every mode reuses the identical task, environment clone, "
                        "attempt budget, model, and generation settings; only the "
                        "memory context shown to the model and the validation "
                        "gates differ."
                    ),
                    "prevention_definition": (
                        "An attempt after the first succeeds with at least one "
                        "retrieved memory applied by the controller."
                    ),
                    "memory_application_policy": (
                        "The model may only suggest memories; the deterministic "
                        "trust gates decide which are applied "
                        "(llm_suggested_ids vs applied_ids in each row)."
                    ),
                },
                "limitations": LIMITATIONS,
            }
        )
        return report

    # ------------------------------------------------------------------ #
    def save_report(self, report: dict) -> Path:
        """Persist under the report's own run id; never overwrite an existing file."""
        self._output_dir.mkdir(parents=True, exist_ok=True)
        run_id = str(report.get("run_id") or self._run_id)
        if not _RUN_ID_RE.match(run_id):  # pragma: no cover - defensive
            run_id = self._run_id
        path = self._output_dir / f"llm_benchmark_{run_id}.json"
        counter = 1
        while path.exists():  # pragma: no cover - 12-hex ids collide rarely
            path = self._output_dir / f"llm_benchmark_{run_id}_{counter}.json"
            counter += 1
        path.write_text(json.dumps(report, indent=2))
        logger.info("LLM benchmark report saved to %s", path)
        return path


_MODE_DOC = {
    "baseline": "no retrieval, no learning; the model plans from scratch",
    "naive": "the model sees unfiltered retrieved memories (research arm)",
    "memory": "the model sees gate-passing memories; the controller applies them",
}


def _reports_dir(settings: Settings) -> Path:
    return Path(settings.llm_benchmark_output_dir)


def list_reports(settings: Settings | None = None) -> list[dict]:
    """Summaries of saved reports, newest first."""
    settings = settings or get_settings()
    entries: list[dict] = []
    for path in _reports_dir(settings).glob("llm_benchmark_*.json"):
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        entries.append(
            {
                "run_id": data.get("run_id", path.stem),
                "generated_at": data.get("generated_at"),
                "status": data.get("status"),
                "model_real": data.get("model_real", False),
                "llm_model": data.get("llm_model"),
                "scenario_count": data.get("scenario_count", 0),
                "filename": path.name,
            }
        )
    entries.sort(key=lambda item: item.get("generated_at") or "", reverse=True)
    return entries


def load_report(settings: Settings | None, run_id: str) -> dict | None:
    """Load one saved report by run id (None when absent)."""
    settings = settings or get_settings()
    if not _RUN_ID_RE.match(run_id):
        return None
    path = _reports_dir(settings) / f"llm_benchmark_{run_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def run_llm_benchmark(
    settings: Settings | None = None,
    scenario_ids: list[str] | None = None,
    repetitions: int = 1,
    modes: list[str] | None = None,
    save: bool = True,
) -> dict:
    """Run the LLM benchmark and (unless skipped) persist the report."""
    benchmark = LLMBenchmark(settings)
    report = benchmark.run(scenario_ids, repetitions=repetitions, modes=modes)
    if save and report.get("status") in {"completed", "aborted"}:
        report["report_path"] = str(benchmark.save_report(report))
    return report
