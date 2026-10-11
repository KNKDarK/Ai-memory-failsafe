"""Evaluation harness: scenarios, metrics, and the baseline-vs-memory report."""

from __future__ import annotations

import json

import pytest

from backend.agent.environment import SimulatedEnvironment
from backend.agent.models import TaskRun
from backend.config import Settings
from backend.evaluation import metrics
from backend.evaluation.benchmark import (
    Benchmark,
    _retrieval_mode,
    format_markdown,
    main,
    run_scenario_detail,
    write_report,
)
from backend.evaluation.scenarios import Scenario, build_scenarios, get_scenario


@pytest.fixture(scope="module")
def report() -> dict:
    return Benchmark(Settings(memory_database=":memory:")).run()


def test_scenarios_are_well_formed() -> None:
    scenarios = build_scenarios()
    ids = [scenario.id for scenario in scenarios]
    assert len(ids) == len(set(ids))
    assert {scenario.category for scenario in scenarios} == {"fixable", "restraint", "detection"}
    for scenario in scenarios:
        assert scenario.simulated is True
        assert scenario.task.strip()
        assert scenario.max_attempts >= 1


def test_report_structure(report: dict) -> None:
    assert report["simulated"] is True
    assert report["retrieval_mode"] == "hashing_embedding"
    assert report["scenario_count"] == len(build_scenarios())
    for key in (
        "aggregate",
        "arms",
        "comparison",
        "retrieval_relevance",
        "retrieval_method_comparison",
        "lifecycle",
        "methodology",
        "limitations",
        "scenarios",
    ):
        assert key in report
    assert "baseline" in report["aggregate"]
    assert "naive" in report["aggregate"]
    assert "memory" in report["aggregate"]


def test_naive_arm_is_less_safe_than_validated_memory(report: dict) -> None:
    arms = report["arms"]
    assert set(arms) == {"baseline", "naive", "memory"}
    assert arms["memory"]["harmful_memory_applications"] == 0
    assert (
        arms["naive"]["harmful_memory_applications"]
        >= arms["memory"]["harmful_memory_applications"]
    )
    baseline_rate = report["aggregate"]["baseline"]["success_rate"]
    assert report["aggregate"]["naive"]["success_rate"] >= baseline_rate


def test_retrieval_method_comparison_covers_every_method(report: dict) -> None:
    comparison = report["retrieval_method_comparison"]
    assert set(comparison["methods"]) == {"tfidf", "bm25", "embedding", "hybrid"}
    for stats in comparison["methods"].values():
        assert 0.0 <= stats["precision"] <= 1.0
        assert 0.0 <= stats["recall"] <= 1.0


def test_lifecycle_section_is_measured(report: dict) -> None:
    lifecycle = report["lifecycle"]
    assert lifecycle["unique_memories"] >= 1
    assert set(lifecycle["at_run"]["counts"]) == {"fresh", "stale", "obsolete", "expired"}
    assert lifecycle["projected"]["horizon_days"] > 0
    assert lifecycle["projected"]["expired"] >= lifecycle["at_run"]["expired"]


def test_expectations_are_met_for_every_scenario(report: dict) -> None:
    assert report["scenarios_expectations_met"] == report["scenario_count"]


def test_memory_improves_success_without_harm(report: dict) -> None:
    baseline = report["aggregate"]["baseline"]
    memory = report["aggregate"]["memory"]
    assert baseline["success_rate"] < memory["success_rate"]
    assert memory["harmful_memory_applications"] == 0
    assert report["comparison"]["prevention_effectiveness"] == 1.0
    expected_fixable = _expected_scenario_count("fixable")
    assert report["comparison"]["fixable_scenarios"] == expected_fixable
    assert report["comparison"]["fixable_scenarios_prevented"] == expected_fixable


def test_fixable_scenarios_need_memory_to_succeed(report: dict) -> None:
    fixable = [row for row in report["scenarios"] if row["category"] == "fixable"]
    assert len(fixable) == _expected_scenario_count("fixable")
    for row in fixable:
        assert row["baseline"]["success"] is False
        assert row["memory"]["success"] is True
        assert row["memory"]["prevented_failure"] is True


def test_detection_scenarios_fail_honestly_in_both_modes(report: dict) -> None:
    detection = [row for row in report["scenarios"] if row["category"] == "detection"]
    assert len(detection) == _expected_scenario_count("detection")
    for row in detection:
        assert row["baseline"]["success"] is False
        assert row["memory"]["success"] is False
        assert row["memory"]["prevented_failure"] is False


def test_applied_memory_does_not_fabricate_success(report: dict) -> None:
    """A relevant memory can be selected *and* applied yet still fail to prevent a
    permanent fault. That must be scored as an honest continued failure, never as
    a prevention or a success, and applying it must not be penalised."""
    scenario_id = "memory_applied_without_prevention"
    row = next(r for r in report["scenarios"] if r["scenario_id"] == scenario_id)
    assert row["category"] == "detection"
    assert row["baseline"]["success"] is False
    assert row["memory"]["success"] is False
    assert row["memory"]["prevented_failure"] is False
    assert row["memory"]["applied_ids"], "the relevant memory should still be applied"
    assert row["memory"]["harmful_applied_ids"] == []

    probe = next(
        p for p in report["retrieval_relevance"]["probes"] if p["scenario_id"] == scenario_id
    )
    assert probe["selection"]["selected_ids"] == ["mem_permanent_timeout"]
    assert probe["application"]["applied_seed_ids"] == ["mem_permanent_timeout"]
    assert probe["application"]["false_positives"] == 0
    assert probe["application"]["unknown_applied_ids"] == []


def _expected_scenario_count(category: str) -> int:
    return sum(1 for scenario in build_scenarios() if scenario.category == category)


def test_retrieval_relevance_separates_application_from_selection(report: dict) -> None:
    relevance = report["retrieval_relevance"]
    # No harmful memory was ever applied.
    assert relevance["application"]["false_positives"] == 0
    assert relevance["application"]["precision"] == 1.0
    # Selection is allowed to surface a relevant-but-untrustworthy memory.
    assert relevance["selection"]["precision"] <= relevance["application"]["precision"]


def test_retrieval_relevance_declares_scope(report: dict) -> None:
    """The two events are named explicitly so they are not read as one retrieval."""
    scope = report["retrieval_relevance"]["scope"]
    assert "seed_memory_preview" in scope["selection_event"]
    assert "actual_memory_run" in scope["application_event"]


def test_retrieval_relevance_ignores_new_memories_but_flags_harmful_seed() -> None:
    """A memory learned during the run must never be a false positive, but an
    applied harmful *seed* memory must be."""
    probes = [
        {
            "scenario_id": "synthetic",
            "seed_memory_ids": ["seed_good", "seed_bad"],
            "seed_preview_selected_ids": ["seed_good"],
            "expected_selected": ["seed_good"],
            "expected_unselected": [],
            "harmful_memory_ids": ["seed_bad"],
            "run_applied_ids": ["seed_good", "learnt_new"],
            "run_created_ids": ["learnt_new"],
        }
    ]
    result = metrics.retrieval_relevance(probes)
    assert result["application"]["true_positives"] == 1
    assert result["application"]["false_positives"] == 0
    assert result["selection"]["false_positives"] == 0

    probe = result["probes"][0]
    assert probe["selection"]["scope"] == "seed_memory_preview"
    assert probe["application"]["scope"] == "actual_memory_run"
    assert probe["application"]["applied_seed_ids"] == ["seed_good"]
    assert probe["application"]["newly_learned_applied_ids"] == ["learnt_new"]
    assert probe["application"]["unknown_applied_ids"] == []
    assert probe["application"]["forbidden_seed_applied_ids"] == []

    # Now the harmful seed memory *is* applied: it must count as a false positive.
    probes[0]["run_applied_ids"] = ["seed_bad", "learnt_new"]
    result = metrics.retrieval_relevance(probes)
    assert result["application"]["false_positives"] == 1
    assert result["application"]["precision"] == 0.0
    assert result["probes"][0]["application"]["forbidden_seed_applied_ids"] == ["seed_bad"]
    # The newly learned memory is still not a false positive.
    assert result["probes"][0]["application"]["newly_learned_applied_ids"] == ["learnt_new"]


def test_incorrect_memory_is_never_selected_or_applied() -> None:
    """Regression: a reviewer-marked-incorrect seed memory must never be surfaced
    or applied, while a newly learned valid memory may be applied and enable
    success."""
    scenario = get_scenario("incorrect_memory")
    assert scenario is not None
    incorrect_ids = set(scenario.harmful_memory_ids)
    assert incorrect_ids, "the scenario must label the incorrect seed memory as harmful"

    detail = run_scenario_detail(Settings(memory_database=":memory:"), scenario)

    # Selection: the incorrect seed memory is never surfaced by the seed preview.
    selected = {result.memory.id for result in detail.probe if result.selected}
    assert selected.isdisjoint(incorrect_ids)

    # Application: it is never applied in any attempt, in either mode.
    for run in (detail.baseline_run, detail.memory_run):
        assert set(run.memory_ids_applied).isdisjoint(incorrect_ids)
        for attempt in run.attempts:
            assert set(attempt.applied_memory_ids).isdisjoint(incorrect_ids)

    # A newly learned, valid memory may be applied and enable success.
    learned = set(detail.memory_run.memory_ids_created) | set(
        detail.memory_run.memory_ids_reinforced
    )
    applied = set(detail.memory_run.memory_ids_applied)
    assert learned, "the agent should learn a memory from the injected failure"
    assert applied, "the learned memory should be applied on the retry"
    assert applied <= learned, "only newly learned memories may be applied here"
    assert detail.memory_run.final_success is True
    assert detail.memory_run.prevented_failure is True


def test_incorrect_memory_probe_scores_new_memory_separately(report: dict) -> None:
    """The report must not present the seed preview and the run's applied ids as
    the same event, nor count the newly learned memory as a false positive."""
    probe = next(
        p for p in report["retrieval_relevance"]["probes"] if p["scenario_id"] == "incorrect_memory"
    )
    assert probe["selection"]["scope"] == "seed_memory_preview"
    assert probe["application"]["scope"] == "actual_memory_run"

    # The incorrect seed memory is neither surfaced nor applied.
    assert "mem_incorrect" not in probe["selection"]["selected_ids"]
    assert "mem_incorrect" not in probe["application"]["applied_ids"]
    assert probe["application"]["applied_seed_ids"] == []
    assert probe["application"]["forbidden_seed_applied_ids"] == []
    assert probe["application"]["false_positives"] == 0

    # The newly learned memory is applied and reported separately, not as a FP.
    assert probe["application"]["newly_learned_applied_ids"]
    assert probe["application"]["newly_learned_applied_ids"] == probe["application"]["applied_ids"]
    assert probe["application"]["unknown_applied_ids"] == []


def test_conflicting_memories_regression(report: dict) -> None:
    """Regression: a harmful conflicting memory must never be applied, while the
    trusted one is. The scenario deliberately allows the wrong candidate to be
    *surfaced* (it is resolved by contradiction suppression), so surfacing it is
    not penalised either - but applying it would be."""
    scenario = get_scenario("conflicting_memories")
    assert scenario is not None
    trusted = "mem_right_conflict"
    harmful = "mem_wrong_conflict"
    assert trusted in scenario.expect_retrieval_of
    assert harmful in scenario.harmful_memory_ids
    # The scenario intentionally does not forbid surfacing the conflicting candidate.
    assert harmful not in scenario.expect_no_retrieval_of

    probe = next(
        p
        for p in report["retrieval_relevance"]["probes"]
        if p["scenario_id"] == "conflicting_memories"
    )
    # Selection: the trusted memory is surfaced; surfacing the wrong candidate is
    # not a false positive (so a selection FP count of 0 is expected here).
    assert trusted in probe["selection"]["selected_ids"]
    assert probe["selection"]["false_positives"] == 0

    # Application: only the trusted seed memory is applied; the harmful id is not
    # a false positive because it was never applied.
    assert probe["application"]["applied_seed_ids"] == [trusted]
    assert probe["application"]["newly_learned_applied_ids"] == []
    assert probe["application"]["unknown_applied_ids"] == []
    assert probe["application"]["forbidden_seed_applied_ids"] == []
    assert probe["application"]["false_positives"] == 0
    assert probe["application"]["true_positives"] == 1

    # The real run resolves the conflict and never applies the harmful memory.
    row = next(r for r in report["scenarios"] if r["scenario_id"] == "conflicting_memories")
    assert harmful not in row["memory"]["applied_ids"]
    assert row["memory"]["harmful_applied_ids"] == []
    assert row["memory"]["success"] is True


def test_markdown_report_is_labelled_and_complete(report: dict) -> None:
    markdown = format_markdown(report)
    assert "# AI Agent Failure Memory" in markdown
    assert "Baseline vs memory-enabled" in markdown
    assert "Evaluation arms" in markdown
    assert "Retrieval relevance" in markdown
    assert "Retrieval method comparison" in markdown
    assert "Memory lifecycle" in markdown
    assert "Limitations" in markdown
    assert "simulated" in markdown.lower()
    assert "hashing_embedding" in markdown


def test_write_report_creates_file(report: dict, tmp_path) -> None:
    target = tmp_path / "nested" / "report.json"
    write_report(report, target)
    assert target.exists()
    assert json.loads(target.read_text())["scenario_count"] == report["scenario_count"]


def test_run_scenario_detail_returns_both_modes() -> None:
    scenario = get_scenario("missing_config_deploy")
    assert scenario is not None
    detail = run_scenario_detail(Settings(memory_database=":memory:"), scenario)
    assert detail.baseline_run.final_success is False
    assert detail.memory_run.final_success is True
    assert detail.memory_run.prevented_failure is True
    assert detail.memory_stats_after["total_memories"] >= 1


def test_metrics_rate_handles_empty_denominator() -> None:
    assert metrics._rate(0, 0) is None  # noqa: SLF001
    assert metrics._rate(1, 2) == 0.5


def test_expectation_met_flags_success_mismatch_and_harmful_application() -> None:
    """Both failure conditions of the expectation check are load-bearing: a run
    that disagrees with the label, or one that applied a harmful memory, must be
    marked unmet even when the success flag happens to match."""
    scenario = Scenario(
        id="unit",
        name="unit",
        category="detection",
        task="do a thing",
        environment=SimulatedEnvironment(id="unit"),
        expected_memory_success=False,
        harmful_memory_ids=["mem_bad"],
    )

    # Matches the label: met.
    expected = TaskRun(run_id="r0", task="do a thing")
    assert metrics._expectation_met(expected, scenario, "memory") is True  # noqa: SLF001

    # Success disagrees with the label: unmet.
    mismatch = TaskRun(run_id="r1", task="do a thing", final_success=True)
    assert metrics._expectation_met(mismatch, scenario, "memory") is False  # noqa: SLF001

    # A harmful memory was applied: unmet even though success matches.
    harmful = TaskRun(run_id="r2", task="do a thing", memory_ids_applied=["mem_bad"])
    assert metrics._expectation_met(harmful, scenario, "memory") is False  # noqa: SLF001


def test_aggregate_helpers_handle_empty_inputs() -> None:
    assert metrics._mean([]) is None  # noqa: SLF001
    comparison = metrics.compare({}, {}, [])
    assert comparison["success_rate_delta"] is None
    assert comparison["avg_attempts_delta"] is None
    assert comparison["prevention_effectiveness"] is None


def test_hallucinated_memory_id_is_surfaced_but_not_a_false_positive() -> None:
    """An applied id that is neither a labelled seed memory nor a memory the run
    reported learning is surfaced as an unknown application. It is not silently
    mistaken for a learned memory, and it is not counted as a false positive
    because it matches no labelled seed memory."""
    probes = [
        {
            "scenario_id": "hallucination",
            "seed_memory_ids": ["seed_good", "seed_bad"],
            "seed_preview_selected_ids": ["seed_good"],
            "expected_selected": ["seed_good"],
            "expected_unselected": [],
            "harmful_memory_ids": ["seed_bad"],
            # The run reports no learned memories, yet claims to apply a ghost id.
            "run_applied_ids": ["seed_good", "ghost_memory"],
            "run_created_ids": [],
            "run_reinforced_ids": [],
        }
    ]
    result = metrics.retrieval_relevance(probes)
    application = result["probes"][0]["application"]

    assert application["applied_seed_ids"] == ["seed_good"]
    assert application["newly_learned_applied_ids"] == []
    assert application["unknown_applied_ids"] == ["ghost_memory"]
    # The ghost id is not a false positive: it is not a labelled seed memory.
    assert application["false_positives"] == 0
    assert result["application"]["precision"] == 1.0


def test_retrieval_mode_reports_embedding_provider() -> None:
    """The report must name the actual retrieval path, including the lexical
    fallback and a neural provider, not just the default hashing path."""

    class _FakeEmbedder:
        def __init__(self, name: str) -> None:
            self.name = name

    class _FakeRuntime:
        def __init__(self, embedder: object | None) -> None:
            self.embedder = embedder

    assert _retrieval_mode(_FakeRuntime(None)) == "tfidf_fallback"
    assert _retrieval_mode(_FakeRuntime(_FakeEmbedder("openai-3-small"))) == "neural_embedding"
    assert _retrieval_mode(_FakeRuntime(_FakeEmbedder("hashing"))) == "hashing_embedding"


def test_benchmark_main_cli_writes_and_prints(tmp_path, capsys) -> None:
    target = tmp_path / "report.json"
    exit_code = main(["--scenarios", "missing_dependency_build", "--output", str(target)])
    assert exit_code == 0
    assert target.exists()

    payload = json.loads(target.read_text())
    assert payload["scenario_count"] == 1
    assert payload["scenarios"][0]["scenario_id"] == "missing_dependency_build"

    captured = capsys.readouterr()
    assert "Baseline vs memory-enabled" in captured.out
    assert "JSON report written to" in captured.out


def test_benchmark_main_cli_json_only(tmp_path, capsys) -> None:
    target = tmp_path / "report.json"
    exit_code = main(
        ["--scenarios", "permanent_api_failure", "--output", str(target), "--json-only"]
    )
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["scenario_count"] == 1
