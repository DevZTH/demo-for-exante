"""Command-line entry point for benchmarks and regression comparison."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from evals.config import EvalSettings
from evals.dataset import DatasetError, list_datasets, load_dataset
from evals.observability import create_eval_observer
from evals.providers.llm import OpenAICompatibleProvider
from evals.report import compare_runs, render_comparison, render_run, save_run
from evals.runner import EvalRunner, default_evaluators

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m evals.cli",
        description="Evaluate structured role-play LLM clients",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logs")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="Run an evaluation dataset")
    run.add_argument("--dataset", required=True, help="Dataset name, path, or 'all'")
    run.add_argument("--runs", type=_positive_int, default=1, help="Runs per testcase")
    run.add_argument("--client-model", help="Override CLIENT_MODEL/EVAL_CLIENT_MODEL")
    run.add_argument("--judge-model", help="Override JUDGE_MODEL/EVAL_JUDGE_MODEL")
    run.add_argument("--prompt-version", help="Version label stored in the report")
    run.add_argument("--dataset-version", help="Override dataset version")
    run.add_argument("--system-prompt", type=Path, help="Path to client system prompt")
    run.add_argument("--output-dir", type=Path, help="Directory for JSON reports")
    run.add_argument(
        "--concurrency", type=_positive_int, help="Maximum concurrent cases"
    )
    run.add_argument(
        "--timeout", type=_positive_float, help="Per-call timeout in seconds"
    )
    run.add_argument(
        "--retries", type=_nonnegative_int, help="Retries after provider error"
    )
    run.add_argument("--seed", type=int, help="Provider seed, when supported")
    run.add_argument(
        "--deterministic-only",
        action="store_true",
        help="Skip all LLM-as-a-judge evaluators",
    )
    run.add_argument(
        "--no-langfuse",
        action="store_true",
        help="Disable optional Langfuse export for this run",
    )
    run.add_argument(
        "--allow-failures",
        action="store_true",
        help="Return exit code 0 even when testcases fail",
    )
    run.set_defaults(handler=_handle_run)

    compare = subparsers.add_parser("compare", help="Compare two saved EvalRun files")
    compare.add_argument("old", type=Path)
    compare.add_argument("new", type=Path)
    compare.add_argument(
        "--quality-threshold",
        type=_nonnegative_float,
        help="Allowed absolute pass-rate drop (0.05 means 5 percentage points)",
    )
    compare.add_argument(
        "--score-threshold",
        type=_nonnegative_float,
        help="Allowed judge mean-score drop",
    )
    compare.add_argument(
        "--latency-threshold-percent",
        type=_nonnegative_float,
        help="Latency increase marked as a regression",
    )
    compare.set_defaults(handler=_handle_compare)

    listing = subparsers.add_parser("list-datasets", help="List bundled JSON datasets")
    listing.add_argument("--datasets-dir", type=Path)
    listing.set_defaults(handler=_handle_list_datasets)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        return int(args.handler(args))
    except (DatasetError, OSError, ValueError) as exc:
        parser.error(str(exc))
    return 2


def _handle_run(args: argparse.Namespace) -> int:
    settings = EvalSettings()
    updates = {
        key: value
        for key, value in {
            "client_model": args.client_model,
            "judge_model": args.judge_model,
            "prompt_version": args.prompt_version,
            "system_prompt_path": args.system_prompt,
            "output_dir": args.output_dir,
            "concurrency": args.concurrency,
            "timeout_seconds": args.timeout,
            "retries": args.retries,
            "seed": args.seed,
        }.items()
        if value is not None
    }
    settings = settings.model_copy(update=updates)

    dataset = load_dataset(
        args.dataset,
        directory=settings.datasets_dir,
        default_version=args.dataset_version or settings.dataset_version,
    )
    system_prompt = settings.system_prompt_path.read_text(encoding="utf-8")
    provider = OpenAICompatibleProvider()
    judge_model = None if args.deterministic_only else settings.judge_config()
    runner = EvalRunner(
        provider,
        default_evaluators(include_judges=not args.deterministic_only),
        client_model=settings.client_config(),
        judge_model=judge_model,
        limits=settings.response_limits(),
        rules=settings.rule_config(),
        thresholds=settings.thresholds(),
        concurrency=settings.concurrency,
        observer=create_eval_observer(
            settings.langfuse_enabled and not args.no_langfuse
        ),
    )
    run = asyncio.run(
        runner.run(
            dataset.cases,
            runs_per_case=args.runs,
            system_prompt=system_prompt,
            dataset_name=dataset.name,
            prompt_version=settings.prompt_version,
            dataset_version=args.dataset_version or dataset.version,
            judge_prompt_version=settings.judge_prompt_version,
        )
    )
    path = save_run(run, settings.output_dir)
    sys.stdout.write(render_run(run) + "\n\n")
    sys.stdout.write(f"JSON report: {path.resolve()}\n")
    return 0 if args.allow_failures or run.overall_pass_rate == 1.0 else 1


def _handle_compare(args: argparse.Namespace) -> int:
    settings = EvalSettings()
    comparison = compare_runs(
        args.old,
        args.new,
        quality_threshold=(
            args.quality_threshold
            if args.quality_threshold is not None
            else settings.quality_regression_threshold
        ),
        score_threshold=(
            args.score_threshold
            if args.score_threshold is not None
            else settings.score_regression_threshold
        ),
        latency_threshold_percent=(
            args.latency_threshold_percent
            if args.latency_threshold_percent is not None
            else settings.latency_regression_threshold_percent
        ),
    )
    sys.stdout.write(render_comparison(comparison) + "\n")
    return 1 if comparison.has_quality_regression else 0


def _handle_list_datasets(args: argparse.Namespace) -> int:
    settings = EvalSettings()
    directory = args.datasets_dir or settings.datasets_dir
    datasets = list_datasets(directory)
    if not datasets:
        sys.stdout.write("No datasets found.\n")
        return 0
    width = max(len(name) for name, _ in datasets)
    for name, count in datasets:
        sys.stdout.write(f"{name:<{width}}  {count:>3} cases\n")
    sys.stdout.write(
        f"{'all':<{width}}  {sum(count for _, count in datasets):>3} cases\n"
    )
    return 0


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def _nonnegative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
