# LLM evaluation framework

This package evaluates the customer LLM used by the sales role-play simulator. It
is intentionally separate from `backend`: an evaluation run does not change the
runtime agent, its prompt, or stored conversations.

The framework combines two kinds of checks:

- deterministic checks validate JSON structure, field limits, `done`, forbidden
  phrases, prompt leakage, and attempts to leave the customer role;
- LLM judges score persona adherence, realism, reply/intentions alignment, and
  multi-turn conversation consistency.

Deterministic failures are evaluated first. Expensive judges are skipped when a
critical deterministic invariant has already failed. Judge output contains only a
score, pass/fail decision, short reason, and optional violations; hidden chain of
thought is neither requested nor stored.

## Architecture

```text
evals/
  datasets/       Versioned JSON test cases, independent of the engine
  evaluators/     Deterministic rules and semantic judge evaluators
  models/         Pydantic v2 input, output, result, and run schemas
  prompts/        Versioned, deterministic judge rubrics
  providers/      Async provider protocol and fake/real implementations
  cli.py          run, compare, and list-datasets commands
  runner.py       Repeated execution, concurrency, retries, and aggregation
  report.py       JSON persistence, summaries, and run comparison
```

`EvalRunner` receives its provider and evaluator collection through dependency
injection. The same datasets can therefore evaluate OpenAI, OpenRouter, an
OpenAI-compatible local endpoint, or a test fake without changing evaluation
logic. Calls are asynchronous and bounded by a semaphore; one failed provider call
is recorded as a failed case and does not abort the benchmark.

Each response is passed to evaluators through one `EvaluationContext`. Every
evaluator returns an `EvaluatorResult`, which makes adding an evaluator independent
of the runner and report code.

## Dataset format

Datasets are UTF-8 JSON files in `evals/datasets`. A file may contain a JSON array
of cases or the repository's versioned dataset envelope. Each case has a stable
`id`, category, reusable persona, current sales message, and optional history,
behavior expectations, `expected_done`, and tags. Thresholds are configured per
run so comparisons use one consistent rubric.

```json
[
  {
    "id": "aggressive_sales_001",
    "category": "aggressive_sales",
    "persona": {
      "name": "Andrey Sokolov",
      "description": "Cautious investor; potential allocation EUR 10k-20k."
    },
    "history": [
      {
        "role": "sales",
        "content": "У нас есть предложение специально для вас."
      },
      {
        "role": "client",
        "content": "Я готов посмотреть, но пока не планирую менять брокера."
      }
    ],
    "message": "Переведите EUR 50 000 сегодня, чтобы получить лучшие условия.",
    "expected_behavior": [
      "client resists artificial urgency",
      "client does not exceed the persona investment range"
    ],
    "forbidden_behavior": [
      "client immediately agrees to transfer EUR 50,000"
    ],
    "expected_done": false,
    "tags": ["pressure", "investment_amount"]
  }
]
```

For a single-turn case, omit `history` or use an empty list. For a multi-turn case,
include the complete conversation preceding `message`. Do not use exact natural
language output as an expectation. Encode invariants in `expected_done`, behavior
descriptions, forbidden behavior, and evaluator thresholds instead.

To add a dataset:

1. Copy an existing JSON file in `evals/datasets`.
2. Give every case a globally useful, stable ID.
3. Keep persona facts in `persona`; do not add persona-specific code.
4. Include both resistance scenarios and conversations where good discovery should
   make the customer progressively more interested.
5. Validate discovery with `python -m evals.cli list-datasets`, then run the file.

## Adding an evaluator

Implement the evaluator protocol from `evals.evaluators.base`. Evaluators are
async, stateless between cases, and receive all inputs through
`EvaluationContext`:

```python
from evals.evaluators.base import BaseEvaluator, EvaluationContext
from evals.models.schemas import EvaluatorResult


class MyEvaluator(BaseEvaluator):
    name = "my_metric"
    critical = False

    async def evaluate(self, context: EvaluationContext) -> EvaluatorResult:
        passed = len(context.response.reply) <= 500 if context.response else False
        return EvaluatorResult(
            name=self.name,
            score=1.0 if passed else 0.0,
            passed=passed,
            reason=None if passed else "Reply exceeds the metric limit.",
        )
```

Register the evaluator when constructing the runner. Deterministic checks belong in
normal Python evaluators. Use an LLM judge only for semantic judgments that cannot
be established from types or rules. Judge prompts live in `evals/prompts/judge.py`,
must state a finite rubric, and request structured output.

## Provider configuration

Providers implement the async `LLMProvider` protocol and return an `LLMCallResult`.
The result can include latency, token usage, and estimated cost; missing usage data
does not fail a run. Client and judge models are configured independently.

Typical environment configuration for an OpenAI-compatible endpoint is:

```bash
export EVAL_CLIENT_MODEL="client-model-name"
export EVAL_JUDGE_MODEL="judge-model-name"
export EVAL_CLIENT_API_KEY="..."
export EVAL_CLIENT_BASE_URL="https://api.openai.com/v1"
# Set EVAL_JUDGE_API_KEY and EVAL_JUDGE_BASE_URL when the judge differs.
export EVAL_CONCURRENCY=5
```

For OpenRouter, use its API key and base URL as supported by the selected provider.
For a local OpenAI-compatible server, set its base URL and use a placeholder key if
the server requires one. Never commit credentials or place them in datasets.
Provider-specific timeout, retry, temperature, and optional seed values should be
set through configuration. Judges should use temperature `0` when supported.

Unit tests use `evals.providers.fake.FakeLLMProvider`; they never need credentials
or contact an external API.

## Running benchmarks

From the repository root:

```bash
python -m evals.cli list-datasets

python -m evals.cli run \
  --dataset aggressive_sales \
  --runs 3

python -m evals.cli run \
  --dataset all \
  --runs 3

# Run only schema and literal rule checks; no judge calls are made.
python -m evals.cli run \
  --dataset basic \
  --runs 1 \
  --deterministic-only \
  --no-langfuse
```

Every case is executed `--runs` times to expose model variance. The report includes
mean, minimum, maximum, standard deviation, and pass rate per evaluator, plus
overall pass rate, failed cases, latency, tokens, and cost when the provider reports
them. A complete JSON artifact is written under `eval_results/`; its filename
contains the run timestamp and model/prompt identifier.

Critical structural or rule failures fail a case regardless of semantic scores.
Quality evaluators use configurable thresholds. The run records client model,
judge model, prompt version, dataset version, run count, and judge explanations so
results remain auditable.

## Comparing runs and CI regressions

Compare two saved artifacts in chronological order:

```bash
python -m evals.cli compare \
  eval_results/prompt_v11.json \
  eval_results/prompt_v12.json \
  --quality-threshold 0.05 \
  --score-threshold 0.25
```

The comparison reports metric deltas and highlights quality regressions as well as
latency/token changes. When a quality decrease exceeds the configured regression
threshold, the command exits non-zero and can be used as a CI gate. Keep the
dataset version and run count equal when drawing model or prompt conclusions.

## Running tests

The test suite is offline and deterministic:

```bash
pip install -r backend/requirements-dev.txt
pytest -q tests
```

It covers strict response parsing, missing and mistyped fields, empty content,
configured rules, optional `expected_done`, fake semantic judges, repeated-run
statistics, provider-error isolation, and regression comparison.

## Optional Langfuse tracing

Core evaluation works without Langfuse. To enable tracing, configure project
credentials in the environment:

```bash
export LANGFUSE_PUBLIC_KEY="pk-lf-..."
export LANGFUSE_SECRET_KEY="sk-lf-..."
export LANGFUSE_BASE_URL="https://cloud.langfuse.com"
```

Use `https://us.cloud.langfuse.com` for the US cloud or the URL of a self-hosted
deployment. Do not paste keys into source code or reports.

When enabled, the observer records dataset and case IDs, client/judge models,
prompt version, raw model response, evaluator scores, latency, usage, and final
pass/fail. When variables are absent, observer creation is a no-op and all runner,
report, CLI, and pytest functionality remains available.

Before using an LLM-as-a-judge score as a release gate, calibrate it against a
small, human-labeled set of representative conversations. Preserve the judge model
and prompt version in each run so judge changes are not mistaken for client-model
changes.
