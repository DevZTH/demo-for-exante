"""Statistics, JSON persistence, human-readable reports, and run comparison."""

from __future__ import annotations

import math
import re
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Literal

from evals.models.schemas import (
    ComparisonMetric,
    EvalResult,
    EvalRun,
    MetricStats,
    RunComparison,
    TokenUsage,
    load_eval_run,
)


def calculate_evaluator_stats(results: list[EvalResult]) -> dict[str, MetricStats]:
    grouped: dict[str, list] = defaultdict(list)
    for result in results:
        for evaluator in result.evaluator_results:
            grouped[evaluator.name].append(evaluator)

    output: dict[str, MetricStats] = {}
    for name, evaluator_results in sorted(grouped.items()):
        scores = [item.score for item in evaluator_results if item.score is not None]
        output[name] = MetricStats(
            count=len(evaluator_results),
            mean=statistics.fmean(scores) if scores else None,
            minimum=min(scores) if scores else None,
            maximum=max(scores) if scores else None,
            std_dev=statistics.pstdev(scores)
            if len(scores) > 1
            else (0.0 if scores else None),
            pass_rate=sum(item.passed for item in evaluator_results)
            / len(evaluator_results),
        )
    return output


def aggregate_usage(results: list[EvalResult]) -> TokenUsage:
    return TokenUsage(
        input_tokens=_sum_optional(item.usage.input_tokens for item in results),
        output_tokens=_sum_optional(item.usage.output_tokens for item in results),
        total_tokens=_sum_optional(item.usage.total_tokens for item in results),
        estimated_cost=_sum_optional_float(
            item.usage.estimated_cost for item in results
        ),
    )


def finalize_run(run: EvalRun) -> EvalRun:
    """Return a copy with all derived metrics recalculated from raw results."""
    result_count = len(run.results)
    return run.model_copy(
        update={
            "evaluator_stats": calculate_evaluator_stats(run.results),
            "overall_pass_rate": (
                sum(item.passed for item in run.results) / result_count
                if result_count
                else 0.0
            ),
            "total_latency_seconds": sum(
                item.latency_seconds or 0.0 for item in run.results
            ),
            "usage": aggregate_usage(run.results),
        }
    )


def save_run(run: EvalRun, output_dir: Path, filename: str | None = None) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    if filename is None:
        timestamp = run.timestamp.strftime("%Y-%m-%dT%H%M%SZ")
        model = _safe_filename(run.client_model)
        prompt = _safe_filename(run.prompt_version)
        filename = f"{timestamp}_{model}_{prompt}.json"
    path = output_dir / filename
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(run.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(path)
    return path


def compare_runs(
    old: EvalRun | str | Path,
    new: EvalRun | str | Path,
    *,
    quality_threshold: float = 0.05,
    score_threshold: float = 0.25,
    latency_threshold_percent: float = 15.0,
) -> RunComparison:
    if quality_threshold < 0 or score_threshold < 0 or latency_threshold_percent < 0:
        raise ValueError("comparison thresholds must be non-negative")
    old_run = load_eval_run(old) if isinstance(old, (str, Path)) else old
    new_run = load_eval_run(new) if isinstance(new, (str, Path)) else new
    metrics: list[ComparisonMetric] = []
    regressions: list[str] = []
    has_quality_regression = False

    overall = _comparison_metric(
        "overall", old_run.overall_pass_rate, new_run.overall_pass_rate, "rate"
    )
    if overall.delta is not None and overall.delta < -quality_threshold:
        overall.regression = True
        has_quality_regression = True
        regressions.append(
            f"Overall pass rate decreased by {abs(overall.delta) * 100:.1f} percentage points"
        )
    metrics.append(overall)

    evaluator_names = sorted(
        set(old_run.evaluator_stats) | set(new_run.evaluator_stats)
    )
    for name in evaluator_names:
        old_stats = old_run.evaluator_stats.get(name)
        new_stats = new_run.evaluator_stats.get(name)
        if old_stats is None or new_stats is None:
            continue

        if old_stats.mean is not None or new_stats.mean is not None:
            metric = _comparison_metric(name, old_stats.mean, new_stats.mean, "score")
            if metric.delta is not None and metric.delta < -score_threshold:
                metric.regression = True
                has_quality_regression = True
                regressions.append(
                    f"{name} mean score decreased by {abs(metric.delta):.2f}"
                )
            metrics.append(metric)

        pass_metric = _comparison_metric(
            f"{name}.pass_rate",
            old_stats.pass_rate,
            new_stats.pass_rate,
            "rate",
        )
        if pass_metric.delta is not None and pass_metric.delta < -quality_threshold:
            pass_metric.regression = True
            has_quality_regression = True
            regressions.append(
                f"{name} pass rate decreased by "
                f"{abs(pass_metric.delta) * 100:.1f} percentage points"
            )
        metrics.append(pass_metric)

    old_latency = _average_latency(old_run)
    new_latency = _average_latency(new_run)
    latency = _comparison_metric(
        "latency_per_result", old_latency, new_latency, "seconds"
    )
    if (
        old_latency is not None
        and old_latency > 0
        and new_latency is not None
        and ((new_latency - old_latency) / old_latency * 100)
        > latency_threshold_percent
    ):
        latency.regression = True
        increase = (new_latency - old_latency) / old_latency * 100
        regressions.append(f"Average latency increased by {increase:.1f}%")
    metrics.append(latency)

    metrics.append(
        _comparison_metric(
            "tokens_per_result",
            _average_tokens(old_run),
            _average_tokens(new_run),
            "tokens",
        )
    )
    metrics.append(
        _comparison_metric(
            "estimated_cost",
            old_run.usage.estimated_cost,
            new_run.usage.estimated_cost,
            "cost",
        )
    )

    return RunComparison(
        old_run_id=old_run.run_id,
        new_run_id=new_run.run_id,
        metrics=metrics,
        regressions=regressions,
        has_quality_regression=has_quality_regression,
    )


def render_run(run: EvalRun) -> str:
    result_count = len(run.results)
    case_count = len({item.case_id for item in run.results})
    lines = [
        f"Model: {run.client_model}",
        f"Judge: {run.judge_model or 'disabled'}",
        f"Prompt version: {run.prompt_version}",
        f"Dataset: {run.dataset} ({run.dataset_version})",
        "",
        f"Tests: {case_count}",
        f"Runs per test: {run.runs_per_case}",
        f"Executions: {result_count}",
        f"Overall pass rate: {run.overall_pass_rate:.1%}",
        f"Total latency: {run.total_latency_seconds:.2f}s",
        "",
        "Evaluator metrics:",
    ]
    for name, stats in sorted(run.evaluator_stats.items()):
        score = (
            f"mean={stats.mean:.2f}, min={stats.minimum:.2f}, "
            f"max={stats.maximum:.2f}, std={stats.std_dev:.2f}, "
            if stats.mean is not None
            else ""
        )
        lines.append(f"  {name}: {score}pass rate={stats.pass_rate:.1%}")

    failed = [item for item in run.results if not item.passed]
    if failed:
        lines.extend(["", f"FAILED ({len(failed)}):"])
        for result in failed:
            lines.append(f"  {result.case_id} [run {result.run_index}]")
            sales_message = result.metadata.get("sales_message")
            if isinstance(sales_message, str):
                lines.append(f"    Sales: {sales_message}")
            if result.response is not None:
                lines.append(f"    Client: {result.response.reply}")
            reasons = [
                f"{item.name}"
                + (f" ({item.score:g})" if item.score is not None else "")
                + f": {item.reason or 'failed'}"
                for item in result.evaluator_results
                if not item.passed
            ]
            if result.error:
                reasons.append(result.error)
            for reason in reasons:
                lines.append(f"    {reason}")

    usage_parts = [
        f"input={run.usage.input_tokens}"
        if run.usage.input_tokens is not None
        else None,
        f"output={run.usage.output_tokens}"
        if run.usage.output_tokens is not None
        else None,
        f"total={run.usage.total_tokens}"
        if run.usage.total_tokens is not None
        else None,
    ]
    known_usage = [item for item in usage_parts if item is not None]
    if known_usage:
        lines.extend(["", "Tokens: " + ", ".join(known_usage)])
    if run.usage.estimated_cost is not None:
        lines.append(f"Estimated cost: ${run.usage.estimated_cost:.6f}")
    return "\n".join(lines)


def render_comparison(comparison: RunComparison) -> str:
    lines = [
        f"Comparison: {comparison.old_run_id} -> {comparison.new_run_id}",
        "",
        f"{'metric':30} {'old':>12} {'new':>12} {'delta':>12}",
    ]
    for metric in comparison.metrics:
        lines.append(
            f"{metric.name:30} "
            f"{_format_value(metric.old, metric.unit):>12} "
            f"{_format_value(metric.new, metric.unit):>12} "
            f"{_format_delta(metric.delta, metric.unit):>12}"
            + ("  REGRESSION" if metric.regression else "")
        )
    if comparison.regressions:
        lines.extend(["", "REGRESSIONS:"])
        lines.extend(f"  {item}" for item in comparison.regressions)
    return "\n".join(lines)


def _comparison_metric(
    name: str,
    old: float | None,
    new: float | None,
    unit: Literal["rate", "score", "seconds", "tokens", "cost"],
) -> ComparisonMetric:
    delta = new - old if old is not None and new is not None else None
    return ComparisonMetric(name=name, old=old, new=new, delta=delta, unit=unit)


def _average_latency(run: EvalRun) -> float | None:
    return run.total_latency_seconds / len(run.results) if run.results else None


def _average_tokens(run: EvalRun) -> float | None:
    if run.usage.total_tokens is None or not run.results:
        return None
    return run.usage.total_tokens / len(run.results)


def _sum_optional(values) -> int | None:
    known = [value for value in values if value is not None]
    return sum(known) if known else None


def _sum_optional_float(values) -> float | None:
    known = [value for value in values if value is not None]
    return math.fsum(known) if known else None


def _safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-._") or "unknown"


def _format_value(value: float | None, unit: str) -> str:
    if value is None:
        return "n/a"
    if unit == "rate":
        return f"{value:.1%}"
    if unit == "score":
        return f"{value:.2f}"
    if unit == "seconds":
        return f"{value:.2f}s"
    if unit == "tokens":
        return f"{value:.0f}"
    if unit == "cost":
        return f"${value:.4f}"
    return str(value)


def _format_delta(value: float | None, unit: str) -> str:
    if value is None:
        return "n/a"
    prefix = "+" if value > 0 else ""
    if unit == "rate":
        return f"{prefix}{value * 100:.1f}pp"
    if unit == "score":
        return f"{prefix}{value:.2f}"
    if unit == "seconds":
        return f"{prefix}{value:.2f}s"
    if unit == "tokens":
        return f"{prefix}{value:.0f}"
    if unit == "cost":
        return f"{prefix}${value:.4f}"
    return f"{prefix}{value}"


__all__ = [
    "aggregate_usage",
    "calculate_evaluator_stats",
    "compare_runs",
    "finalize_run",
    "render_comparison",
    "render_run",
    "save_run",
]
