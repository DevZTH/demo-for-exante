"""Optional Langfuse adapter; the evaluation engine itself has no SDK dependency."""

from __future__ import annotations

import logging
from contextlib import AbstractContextManager, contextmanager
from importlib import import_module
from typing import Any, Protocol

from pydantic import BaseModel

from evals.models.schemas import (
    EvalResult,
    EvalTestCase,
    LLMCallResult,
    ModelConfig,
)

logger = logging.getLogger(__name__)


class CallObservation(Protocol):
    def finish(self, result: LLMCallResult) -> None: ...

    def fail(self, error: BaseException) -> None: ...


class CaseObservation(Protocol):
    def model_call(
        self,
        *,
        name: str,
        model: ModelConfig,
        input_data: Any,
        metadata: dict[str, Any] | None = None,
    ) -> AbstractContextManager[CallObservation]: ...

    def finish(self, result: EvalResult) -> None: ...


class EvalObserver(Protocol):
    def case(
        self,
        *,
        case: EvalTestCase,
        dataset: str,
        eval_run_id: str,
        run_index: int,
        client_model: str,
        judge_model: str | None,
        prompt_version: str,
        judge_prompt_version: str,
    ) -> AbstractContextManager[CaseObservation]: ...

    def flush(self) -> None: ...


class NullCallObservation:
    def finish(self, result: LLMCallResult) -> None:
        del result

    def fail(self, error: BaseException) -> None:
        del error


class NullCaseObservation:
    @contextmanager
    def model_call(
        self,
        *,
        name: str,
        model: ModelConfig,
        input_data: Any,
        metadata: dict[str, Any] | None = None,
    ):
        del name, model, input_data, metadata
        yield NullCallObservation()

    def finish(self, result: EvalResult) -> None:
        del result


class NullEvalObserver:
    @contextmanager
    def case(
        self,
        *,
        case: EvalTestCase,
        dataset: str,
        eval_run_id: str,
        run_index: int,
        client_model: str,
        judge_model: str | None,
        prompt_version: str,
        judge_prompt_version: str,
    ):
        del (
            case,
            dataset,
            eval_run_id,
            run_index,
            client_model,
            judge_model,
            prompt_version,
            judge_prompt_version,
        )
        yield NullCaseObservation()

    def flush(self) -> None:
        return None


class ResilientEvalObserver:
    """Prevent an optional telemetry backend from changing benchmark results."""

    def __init__(self, inner: EvalObserver) -> None:
        self.inner = inner

    @contextmanager
    def case(self, **kwargs: Any):
        try:
            manager = self.inner.case(**kwargs)
            observation = manager.__enter__()
        except Exception:
            logger.warning(
                "Unable to start Langfuse case trace; using no-op tracing",
                exc_info=True,
            )
            yield NullCaseObservation()
            return

        try:
            yield _ResilientCaseObservation(observation)
        except BaseException as exc:
            try:
                manager.__exit__(type(exc), exc, exc.__traceback__)
            except Exception:
                logger.warning("Unable to close failed Langfuse trace", exc_info=True)
            raise
        else:
            try:
                manager.__exit__(None, None, None)
            except Exception:
                logger.warning("Unable to close Langfuse case trace", exc_info=True)

    def flush(self) -> None:
        try:
            self.inner.flush()
        except Exception:
            logger.warning("Unable to flush evaluation telemetry", exc_info=True)


class _ResilientCaseObservation:
    def __init__(self, inner: CaseObservation) -> None:
        self.inner = inner

    @contextmanager
    def model_call(self, **kwargs: Any):
        try:
            manager = self.inner.model_call(**kwargs)
            observation = manager.__enter__()
        except Exception:
            logger.warning(
                "Unable to start Langfuse model observation; using no-op tracing",
                exc_info=True,
            )
            yield NullCallObservation()
            return

        safe = _ResilientCallObservation(observation)
        try:
            yield safe
        except BaseException as exc:
            try:
                manager.__exit__(type(exc), exc, exc.__traceback__)
            except Exception:
                logger.warning(
                    "Unable to close failed Langfuse model observation",
                    exc_info=True,
                )
            raise
        else:
            try:
                manager.__exit__(None, None, None)
            except Exception:
                logger.warning(
                    "Unable to close Langfuse model observation",
                    exc_info=True,
                )

    def finish(self, result: EvalResult) -> None:
        try:
            self.inner.finish(result)
        except Exception:
            logger.warning("Unable to finalize Langfuse case trace", exc_info=True)


class _ResilientCallObservation:
    def __init__(self, inner: CallObservation) -> None:
        self.inner = inner

    def finish(self, result: LLMCallResult) -> None:
        try:
            self.inner.finish(result)
        except Exception:
            logger.warning("Unable to update Langfuse generation", exc_info=True)

    def fail(self, error: BaseException) -> None:
        try:
            self.inner.fail(error)
        except Exception:
            logger.warning("Unable to mark Langfuse generation failed", exc_info=True)


class LangfuseEvalObserver:
    """One trace per testcase execution, with nested client/judge generations."""

    def __init__(self, client: Any) -> None:
        self.client = client

    @contextmanager
    def case(
        self,
        *,
        case: EvalTestCase,
        dataset: str,
        eval_run_id: str,
        run_index: int,
        client_model: str,
        judge_model: str | None,
        prompt_version: str,
        judge_prompt_version: str,
    ):
        from langfuse import propagate_attributes

        with (
            propagate_attributes(
                trace_name="llm-roleplay-evaluation",
                tags=["evaluation", dataset, case.category, *case.tags],
                version=prompt_version,
                metadata={
                    "testcase_id": case.id,
                    "dataset": dataset,
                    "eval_run_id": eval_run_id,
                },
            ),
            self.client.start_as_current_observation(
                as_type="span",
                name="evaluate-roleplay-client",
                input={
                    "testcase": case.model_dump(mode="json"),
                    "run_index": run_index,
                },
                metadata={
                    "dataset": dataset,
                    "eval_run_id": eval_run_id,
                    "client_model": client_model,
                    "judge_model": judge_model,
                    "prompt_version": prompt_version,
                    "judge_prompt_version": judge_prompt_version,
                },
            ) as root,
        ):
            yield _LangfuseCaseObservation(self.client, root)

    def flush(self) -> None:
        try:
            self.client.flush()
        except Exception:
            logger.warning("Unable to flush Langfuse evaluation traces", exc_info=True)


class _LangfuseCaseObservation:
    def __init__(self, client: Any, root: Any) -> None:
        self.client = client
        self.root = root

    @contextmanager
    def model_call(
        self,
        *,
        name: str,
        model: ModelConfig,
        input_data: Any,
        metadata: dict[str, Any] | None = None,
    ):
        with self.client.start_as_current_observation(
            as_type="generation",
            name=name,
            model=model.name,
            input=_jsonable(input_data),
            model_parameters={
                "temperature": model.temperature,
                "seed": model.seed,
            },
            metadata=metadata or {},
        ) as generation:
            call = _LangfuseCallObservation(generation)
            try:
                yield call
            except BaseException as exc:
                call.fail(exc)
                raise

    def finish(self, result: EvalResult) -> None:
        scores = {
            item.name: {
                "score": item.score,
                "passed": item.passed,
                "reason": item.reason,
            }
            for item in result.evaluator_results
        }
        self.root.update(
            output={
                "response": (
                    result.response.model_dump(mode="json")
                    if result.response is not None
                    else result.raw_response
                ),
                "scores": scores,
                "passed": result.passed,
                "error": result.error,
            }
        )
        for evaluator in result.evaluator_results:
            if evaluator.score is not None:
                self.root.score_trace(
                    name=evaluator.name,
                    value=float(evaluator.score),
                    data_type="NUMERIC",
                    comment=evaluator.reason,
                )
            self.root.score_trace(
                name=f"{evaluator.name}.passed",
                value=1.0 if evaluator.passed else 0.0,
                data_type="BOOLEAN",
                comment=evaluator.reason,
            )
        self.root.score_trace(
            name="evaluation.passed",
            value=1.0 if result.passed else 0.0,
            data_type="BOOLEAN",
            comment=result.error,
        )


class _LangfuseCallObservation:
    def __init__(self, observation: Any) -> None:
        self.observation = observation

    def finish(self, result: LLMCallResult) -> None:
        usage_details = {
            key: value
            for key, value in {
                "input_tokens": result.usage.input_tokens,
                "output_tokens": result.usage.output_tokens,
                "total_tokens": result.usage.total_tokens,
            }.items()
            if value is not None
        }
        update: dict[str, Any] = {
            "output": _jsonable(result.content),
            "metadata": result.metadata,
        }
        if usage_details:
            update["usage_details"] = usage_details
        if result.usage.estimated_cost is not None:
            update["cost_details"] = {
                "total": result.usage.estimated_cost,
            }
        self.observation.update(**update)

    def fail(self, error: BaseException) -> None:
        self.observation.update(
            level="ERROR",
            status_message=str(error),
            metadata={"error_type": type(error).__name__},
        )


def create_eval_observer(enabled: bool = True) -> EvalObserver:
    """Reuse production credential loading and privacy masking when configured."""
    if not enabled:
        return NullEvalObserver()
    try:
        observability_module = import_module("backend.app.observability")
        settings_module = import_module("backend.settings")
        client = observability_module.create_langfuse_client(settings_module.Settings())
    except Exception:
        logger.warning(
            "Langfuse evaluation tracing could not be initialized; continuing without it",
            exc_info=True,
        )
        return NullEvalObserver()
    return (
        ResilientEvalObserver(LangfuseEvalObserver(client))
        if client is not None
        else NullEvalObserver()
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


__all__ = [
    "CallObservation",
    "CaseObservation",
    "EvalObserver",
    "LangfuseEvalObserver",
    "NullEvalObserver",
    "ResilientEvalObserver",
    "create_eval_observer",
]
