"""End-to-end agent lifecycle: task -> fail -> analyse -> learn -> prevent."""

from __future__ import annotations

import pytest

from backend.agent.agent import FailureMemoryAgent
from backend.agent.environment import SimulatedEnvironment, default_environment
from backend.config import Settings
from backend.domain import MemoryStatus
from backend.memory.models import FailureMemory, RetrievalResult
from backend.memory.store import MemoryStore
from backend.services import Runtime
from backend.tests.factories import build_env, deploy_env, make_memory


def _permanent_api_env() -> SimulatedEnvironment:
    return SimulatedEnvironment(
        id="permanent-api",
        services={"billing_api": {"required_env": []}},
        faults={"api_modes": {"billing_api": "permanent_failure"}},
    )


def test_baseline_repeats_the_failure_and_learns_nothing(runtime: Runtime) -> None:
    run = runtime.agent().run_task(
        "Build the project", build_env(), mode="baseline", max_attempts=2
    )
    assert run.final_success is False
    assert run.attempts_used == 2
    assert run.memory_ids_created == []
    assert run.retrieved_memory_ids == []
    assert runtime.store.count() == 0


def test_memory_mode_learns_then_prevents_within_one_run(runtime: Runtime) -> None:
    run = runtime.agent().run_task("Build the project", build_env(), mode="memory", max_attempts=2)

    assert run.final_success is True
    assert run.attempts_used == 2
    assert run.memory_ids_created, "a memory should be learned on attempt 1"
    assert run.memory_ids_applied, "the learned memory should be applied on attempt 2"
    assert run.prevented_failure is True
    assert "succeeded after applying memory" in run.prevention_evidence
    assert runtime.store.count() == 1

    second_attempt = run.attempts[1]
    assert any(rec.applied for rec in second_attempt.recommendations)


def test_transient_api_recovers_with_memory(runtime: Runtime) -> None:
    env = SimulatedEnvironment(
        id="transient",
        services={"billing_api": {"required_env": []}},
        faults={"api_modes": {"billing_api": "transient"}},
    )
    baseline = runtime.agent().run_task(
        "Fetch data from the billing api", env.clone(), mode="baseline", max_attempts=2
    )
    memory = runtime.agent().run_task(
        "Fetch data from the billing api", env.clone(), mode="memory", max_attempts=2
    )
    assert baseline.final_success is False
    assert memory.final_success is True
    assert memory.prevented_failure is True


def test_missing_config_deploy_is_prevented_by_loading_from_secret_store(runtime: Runtime) -> None:
    run = runtime.agent().run_task(
        "Deploy the application", deploy_env(), mode="memory", max_attempts=2
    )
    assert run.final_success is True
    assert run.prevented_failure is True
    # The applied prevention actually loaded the missing variable.
    assert any(step.tool == "load_config" for step in run.attempts[1].plan.steps)


def test_unfixable_failure_is_not_fabricated_into_success(runtime: Runtime) -> None:
    for mode in ("baseline", "memory"):
        run = runtime.agent().run_task(
            "Fetch data from the billing api",
            _permanent_api_env(),
            mode=mode,
            max_attempts=2,
        )
        assert run.final_success is False
        assert run.prevented_failure is False
        assert run.final_outcome.value in {"tool_failure", "invalid_output", "task_failure"}


def test_second_run_uses_memory_on_the_first_attempt(runtime: Runtime) -> None:
    first = runtime.agent().run_task(
        "Build the project", build_env(), mode="memory", max_attempts=2
    )
    assert first.final_success is True

    second = runtime.agent().run_task(
        "Build the project", build_env(), mode="memory", max_attempts=2
    )
    assert second.final_success is True
    assert second.attempts_used == 1
    assert second.memory_ids_applied  # reused the earlier lesson
    memory = runtime.store.get(second.memory_ids_applied[0])
    assert memory is not None
    assert memory.success_count >= 1


def test_incorrect_memory_is_never_applied(runtime: Runtime) -> None:
    bad = make_memory(
        id="bad",
        task="Build the project",
        task_type="build_project",
        action="run_build",
        root_cause="misdiagnosed",
        prevention="Delete the source and rebuild.",
        prevention_actions=["install_dependency:definitely-wrong"],
        confidence=0.95,
        status=MemoryStatus.INCORRECT,
    )
    runtime.store.save(bad)

    run = runtime.agent().run_task("Build the project", build_env(), mode="memory", max_attempts=2)
    assert "bad" not in run.memory_ids_applied
    assert "bad" not in run.retrieved_memory_ids
    assert run.final_success is True


def test_naive_mode_applies_memories_that_validated_mode_blocks(runtime: Runtime) -> None:
    bad = make_memory(
        id="bad",
        task="Build the project",
        task_type="build_project",
        action="run_build",
        root_cause="misdiagnosed",
        prevention="Delete the source and rebuild.",
        prevention_actions=["install_dependency:definitely-wrong"],
        confidence=0.95,
        status=MemoryStatus.INCORRECT,
    )
    runtime.store.save(bad)

    naive = runtime.agent().run_task("Build the project", build_env(), mode="naive", max_attempts=2)
    validated = runtime.agent().run_task(
        "Build the project", build_env(), mode="memory", max_attempts=2
    )

    # The naive arm applies the untrusted memory; validated mode refuses it.
    assert "bad" in naive.memory_ids_applied
    assert "bad" not in validated.memory_ids_applied


def test_irrelevant_memory_is_not_applied(runtime: Runtime) -> None:
    unrelated: FailureMemory = make_memory(
        id="unrelated",
        task="Compile a Rust crate",
        task_type="build_project",
        action="cargo_build",
        root_cause="missing system linker",
        prevention="Install build-essential.",
        prevention_actions=["install_dependency:build-essential"],
        confidence=0.9,
    )
    runtime.store.save(unrelated)

    run = runtime.agent().run_task(
        "Deploy the application", deploy_env(), mode="memory", max_attempts=1
    )
    assert "unrelated" not in run.memory_ids_applied
    assert "unrelated" not in run.retrieved_memory_ids


def test_max_attempts_is_respected(runtime: Runtime) -> None:
    run = runtime.agent().run_task(
        "Fetch data from the billing api",
        _permanent_api_env(),
        mode="memory",
        max_attempts=3,
    )
    assert run.attempts_used == 3


def test_empty_task_is_rejected(runtime: Runtime) -> None:
    with pytest.raises(ValueError):
        runtime.agent().run_task("   ", default_environment())


def test_preview_retrieval_does_not_execute(runtime: Runtime) -> None:
    runtime.store.save(
        make_memory(
            id="m",
            task="Deploy the application",
            task_type="deploy_service",
            action="deploy",
        )
    )
    env = deploy_env()
    results = runtime.agent().preview_retrieval("Deploy the application", env)
    assert [r.memory.id for r in results if r.selected] == ["m"]
    # No execution happened: the environment was not mutated.
    assert env.has_flag("config_valid") is False


def test_agent_construction_falls_back_to_environment_settings(store: MemoryStore) -> None:
    """Constructing an agent without settings, or with something that is not a
    Settings object, must resolve to environment-derived settings."""
    default_agent = FailureMemoryAgent(store)
    assert isinstance(default_agent.settings, Settings)

    fixed_agent = FailureMemoryAgent(store, object())
    assert isinstance(fixed_agent.settings, Settings)


def test_run_task_and_preview_use_default_environment(runtime: Runtime) -> None:
    """When no environment is supplied the agent uses the benign default one."""
    agent = runtime.agent()

    run = agent.run_task("Build the project")
    assert run.final_success is True
    assert run.environment_id == default_environment().id

    results = agent.preview_retrieval("Build the project")
    assert isinstance(results, list)


def test_preview_retrieval_rejects_empty_task(runtime: Runtime) -> None:
    with pytest.raises(ValueError):
        runtime.agent().preview_retrieval("   ")


def test_agent_without_retriever_retrieves_nothing(runtime: Runtime) -> None:
    agent = FailureMemoryAgent(runtime.store, runtime.settings)
    run = agent.run_task("Build the project", build_env(), mode="memory", max_attempts=2)
    assert run.retrieved_memory_ids == []
    assert run.memory_ids_applied == []


def test_analyze_delegates_to_the_analyzer(runtime: Runtime) -> None:
    agent = runtime.agent()
    run = agent.run_task("Build the project", build_env(), mode="baseline", max_attempts=1)
    analysis = agent.analyze(run.attempts[0])
    assert analysis.task
    assert analysis.failure_category is not None


def test_recommendations_block_inactive_and_irrelevant_memories(runtime: Runtime) -> None:
    """Both guard rails are load-bearing: an inactive memory and an irrelevant
    memory must each be marked not-applicable with an explanatory reason."""
    agent = runtime.agent()
    plan = agent.planner.plan("Deploy the application", default_environment())

    inactive = make_memory(id="inactive", confidence=0.95, status=MemoryStatus.OUTDATED)
    irrelevant = make_memory(
        id="irrelevant",
        task="Compile a Rust crate",
        task_type="build_project",
        action="cargo_build",
        confidence=0.95,
    )
    retrieved = [
        RetrievalResult(memory=inactive, selected=True, similarity=0.9),
        RetrievalResult(memory=irrelevant, selected=True, similarity=0.1),
    ]

    recommendations = agent._build_recommendations(retrieved, plan.task_type, plan)  # noqa: SLF001
    by_id = {rec.memory_id: rec for rec in recommendations}

    assert by_id["inactive"].applicable is False
    assert "status" in by_id["inactive"].reason
    assert by_id["irrelevant"].applicable is False
    assert "not relevant" in by_id["irrelevant"].reason


def test_dependency_check_task_is_planned_instead_of_routed_to_api(runtime: Runtime) -> None:
    env = SimulatedEnvironment(
        id="dep-check",
        registry={"requests": "2.31.0"},
        packages={},
        services={"billing_api": {"required_env": []}},
    )

    run = runtime.agent().run_task(
        "Check if the 'requests' library is installed, and if not, install it and run a test.",
        env,
        mode="baseline",
        max_attempts=1,
    )

    assert run.task_type == "dependency_check"
    tools = [trace.step.tool for trace in run.attempts[0].traces]
    assert tools == ["check_dependency", "install_dependency", "run_tests"]
    # The dependency is installable, so the task succeeds without an API call.
    assert run.final_success is True
    assert all(trace.step.tool != "call_api" for trace in run.attempts[0].traces)


def test_dependency_check_fails_when_package_is_not_in_the_registry(runtime: Runtime) -> None:
    env = SimulatedEnvironment(id="dep-missing", registry={}, packages={})

    run = runtime.agent().run_task(
        "Check if the 'requests' library is installed, and if not, install it and run a test.",
        env,
        mode="baseline",
        max_attempts=1,
    )

    assert run.task_type == "dependency_check"
    assert run.final_success is False
    failed = [trace for trace in run.attempts[0].traces if not trace.result.ok]
    assert failed, "the install step should fail"
    assert failed[0].step.tool == "install_dependency"
    assert failed[0].result.error_code == "missing_dependency"
