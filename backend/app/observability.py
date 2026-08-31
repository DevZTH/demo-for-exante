"""Langfuse setup and privacy controls for the scenario service."""

from __future__ import annotations

import logging
import os
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.settings import Settings


logger = logging.getLogger(__name__)

# These patterns intentionally run only on telemetry attributes immediately before
# they are exported to Langfuse. They never change the prompts or model responses
# used by the application itself.
_EMAIL_PATTERN = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_PHONE_PATTERN = re.compile(
    r"(?<!\w)(?:\+?\d{1,3}[ .-]?)?(?:\(?\d{2,4}\)?[ .-]?){2,4}\d{2,4}(?!\w)"
)
_CARD_PATTERN = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
_CREDENTIAL_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|authorization|bearer|token|password|secret)"
    r"\s*([:=])\s*(?:bearer\s+)?[^\s,;\"']+"
)


def create_langfuse_client(settings: "Settings") -> Any | None:
    """Create the configured Langfuse client, or leave tracing disabled.

    Imports are deliberately local: the settings object has already read
    ``backend/.env`` before Langfuse is initialized.
    """
    if not settings.langfuse_tracing_enabled:
        logger.info("Langfuse tracing is disabled by configuration")
        return None

    public_key = _secret_value(settings.langfuse_public_key)
    secret_key = _secret_value(settings.langfuse_secret_key)
    if not public_key or not secret_key:
        logger.info(
            "Langfuse tracing is not configured; set LANGFUSE_PUBLIC_KEY and "
            "LANGFUSE_SECRET_KEY to enable it"
        )
        return None

    # Langfuse is OpenTelemetry-native. Set a meaningful service name before it
    # builds its tracer provider, while still respecting an operator-provided one.
    os.environ.setdefault("OTEL_SERVICE_NAME", "exante-scenario-trainer")

    from langfuse import Langfuse

    options: dict[str, Any] = {
        "public_key": public_key,
        "secret_key": secret_key,
        "environment": settings.langfuse_environment,
        "mask_otel_spans": redact_sensitive_otel_spans,
    }
    if settings.langfuse_base_url:
        options["base_url"] = settings.langfuse_base_url
    if settings.langfuse_release:
        options["release"] = settings.langfuse_release

    return Langfuse(**options)


def redact_sensitive_otel_spans(*, params: Any) -> Any | None:
    """Mask common PII and credentials in telemetry before Langfuse export."""
    from langfuse.types import MaskOtelSpansResult, OtelSpanPatch

    patches: dict[Any, Any] = {}
    for identifier, span in params.spans.items():
        replacements: dict[str, str] = {}
        for key, value in span.attributes.items():
            if not isinstance(value, str):
                continue
            redacted = _redact(value)
            if redacted != value:
                replacements[key] = redacted

        if replacements:
            replacements["langfuse.masking.applied"] = True
            patches[identifier] = OtelSpanPatch(set_attributes=replacements)

    return MaskOtelSpansResult(span_patches=patches) if patches else None


def _redact(value: str) -> str:
    value = _EMAIL_PATTERN.sub("[REDACTED EMAIL]", value)
    value = _CARD_PATTERN.sub("[REDACTED CARD]", value)
    value = _PHONE_PATTERN.sub("[REDACTED PHONE]", value)
    return _CREDENTIAL_PATTERN.sub(r"\1\2[REDACTED]", value)


def _secret_value(value: object | None) -> str | None:
    if value is None:
        return None
    get_secret_value = getattr(value, "get_secret_value", None)
    if callable(get_secret_value):
        return get_secret_value()
    return str(value)
