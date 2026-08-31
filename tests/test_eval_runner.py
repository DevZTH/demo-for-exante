from __future__ import annotations

import asyncio

import pytest
from conftest import response_json

from evals.cli import main as cli_main
from evals.evaluators.persona import PersonaEvaluator
from evals.evaluators.rules import RulesEvaluator
from evals.evaluators.structure import StructureEvaluator
from evals.models.schemas import (
    EvalResult,
    EvalRun,
    EvalTestCase,
    MetricStats,
    ModelConfig,
)
from evals.providers.fake import FakeLLMProvider
from evals.providers.llm import ProviderError
from evals.report import compare_runs, save_run
from evals.runner import EvalRunner


def make_runner(provider: FakeLLMProvider) -> EvalRunner:
    return EvalRunner(
        provider,
        [StructureEvaluator(), RulesEvaluator()],
        client_model=ModelConfig(name="fake-client", provider="fake"),
        concurrency=2,
    )


def test_eval_runner(sample_case: EvalTestCase) -> None:
    provider = FakeLLMProvider(client_responses=[response_json()])
    runner = make_runner(provider)

    run = asyncio.run(
        runner.run(
            [sample_case],
            runs_per_case=1,
            system_prompt="Act as the supplied customer persona.",
            dataset_name="unit",
        )
    )

    assert len(run.results) == 1
    assert run.results[0].case_id == sample_case.id
    assert run.results[0].passed is True
    assert run.overall_pass_rate == pytest.approx(1.0)
    assert run.evaluator_stats["structure"].pass_rate == pytest.approx(1.0)
    assert run.evaluator_stats["rules"].pass_rate == pytest.approx(1.0)


def test_multiple_runs_statistics(sample_case: EvalTestCase) -> None:
    outputs = [
        response_json(done=False),
        response_json(done=False),
        response_json(done=True),
        response_json(done=False),
    ]
    provider = FakeLLMProvider(client_responses=outputs)
    runner = make_runner(provider)

    run = asyncio.run(
        runner.run(
            [sample_case],
            runs_per_case=4,
            system_prompt="Act as the supplied customer persona.",
            dataset_name="unit",
        )
    )

    assert len(run.results) == 4
    assert run.overall_pass_rate == pytest.approx(0.75)
    rules = run.evaluator_stats["rules"]
    assert rules.count == 4
    assert rules.minimum == pytest.approx(0.0)
    assert rules.maximum == pytest.approx(1.0)
    assert rules.mean == pytest.approx(0.75)
    assert rules.pass_rate == pytest.approx(0.75)
    assert rules.std_dev is not None and rules.std_dev > 0


def test_provider_error_is_isolated(sample_case: EvalTestCase) -> None:
    provider = FakeLLMProvider(
        client_responses=[ProviderError("temporary failure"), response_json()]
    )
    runner = EvalRunner(
        provider,
        [StructureEvaluator(), RulesEvaluator()],
        client_model=ModelConfig(
            name="fake-client",
            provider="fake",
            max_retries=0,
        ),
        concurrency=1,
    )

    run = asyncio.run(
        runner.run(
            [sample_case],
            runs_per_case=2,
            system_prompt="Act as the supplied customer persona.",
            dataset_name="unit",
        )
    )

    assert len(run.results) == 2
    assert sum(result.error is not None for result in run.results) == 1
    assert sum(result.passed for result in run.results) == 1
    assert run.overall_pass_rate == pytest.approx(0.5)


def test_provider_retry_recovers(sample_case: EvalTestCase) -> None:
    provider = FakeLLMProvider(
        client_responses=[ProviderError("temporary failure"), response_json()]
    )
    runner = EvalRunner(
        provider,
        [StructureEvaluator(), RulesEvaluator()],
        client_model=ModelConfig(
            name="fake-client",
            provider="fake",
            max_retries=1,
        ),
        concurrency=1,
    )

    run = asyncio.run(
        runner.run(
            [sample_case],
            system_prompt="Act as the supplied customer persona.",
            dataset_name="unit",
        )
    )

    assert run.results[0].passed is True
    assert run.results[0].metadata["client_attempts"] == 2
    assert provider.client_calls == 2


def test_judge_is_skipped_after_structural_failure(
    sample_case: EvalTestCase,
) -> None:
    provider = FakeLLMProvider(client_responses=["not JSON"])
    runner = EvalRunner(
        provider,
        [StructureEvaluator(), PersonaEvaluator()],
        client_model=ModelConfig(name="fake-client", provider="fake"),
        judge_model=ModelConfig(name="fake-judge", provider="fake"),
    )

    run = asyncio.run(
        runner.run(
            [sample_case],
            system_prompt="Act as the supplied customer persona.",
            dataset_name="unit",
        )
    )

    assert run.results[0].passed is False
    assert [result.name for result in run.results[0].evaluator_results] == ["structure"]
    assert dict(provider.judge_calls) == {}


def test_observer_failure_does_not_break_evaluation(sample_case: EvalTestCase) -> None:
    class FailingObserver:
        def case(self, **_):
            raise RuntimeError("telemetry unavailable")

        def flush(self) -> None:
            raise RuntimeError("telemetry unavailable")

    provider = FakeLLMProvider(client_responses=[response_json()])
    runner = EvalRunner(
        provider,
        [StructureEvaluator(), RulesEvaluator()],
        client_model=ModelConfig(name="fake-client", provider="fake"),
        observer=FailingObserver(),
    )

    run = asyncio.run(
        runner.run(
            [sample_case],
            system_prompt="Act as the supplied customer persona.",
            dataset_name="unit",
        )
    )

    assert run.results[0].passed is True


def make_run(
    run_id: str,
    *,
    overall_pass_rate: float,
    persona_mean: float,
    latency: float,
) -> EvalRun:
    results = [
        EvalResult(
            case_id=f"case_{index}",
            category="unit",
            run_index=1,
            passed=True,
        )
        for index in range(3)
    ]
    return EvalRun(
        run_id=run_id,
        client_model="fake-client",
        judge_model="fake-judge",
        prompt_version=run_id,
        judge_prompt_version="judge-v1",
        dataset="unit",
        dataset_version="1.0",
        runs_per_case=3,
        results=results,
        overall_pass_rate=overall_pass_rate,
        total_latency_seconds=latency,
        evaluator_stats={
            "persona": MetricStats(
                count=3,
                mean=persona_mean,
                minimum=persona_mean,
                maximum=persona_mean,
                std_dev=0,
                pass_rate=overall_pass_rate,
            )
        },
    )


def test_regression_comparison() -> None:
    old = make_run(
        "old",
        overall_pass_rate=0.90,
        persona_mean=4.5,
        latency=3.0,
    )
    new = make_run(
        "new",
        overall_pass_rate=0.75,
        persona_mean=3.8,
        latency=4.0,
    )

    comparison = compare_runs(
        old,
        new,
        quality_threshold=0.05,
        score_threshold=0.25,
        latency_threshold_percent=15,
    )

    assert comparison.has_quality_regression is True
    assert comparison.regressions
    metrics = {metric.name: metric for metric in comparison.metrics}
    assert metrics["overall"].delta == pytest.approx(-0.15)
    assert metrics["persona"].delta == pytest.approx(-0.7)
    assert metrics["latency_per_result"].regression is True


def test_cli_lists_datasets(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = cli_main(["list-datasets"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "basic" in output
    assert "all" in output


def test_compare_cli_returns_nonzero_for_quality_regression(
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    old_path = save_run(
        make_run("old", overall_pass_rate=0.90, persona_mean=4.5, latency=3.0),
        tmp_path,
        "old.json",
    )
    new_path = save_run(
        make_run("new", overall_pass_rate=0.75, persona_mean=3.8, latency=4.0),
        tmp_path,
        "new.json",
    )

    exit_code = cli_main(["compare", str(old_path), str(new_path)])

    assert exit_code == 1
    assert "REGRESSION" in capsys.readouterr().out
