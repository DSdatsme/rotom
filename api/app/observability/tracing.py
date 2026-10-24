"""OpenTelemetry wiring: rotom's TracerProvider → SqliteSpanExporter → `span` table.

rotom owns its provider (it is NOT installed as the OTel global) so tests can re-init
freely; the OTel *context* is global regardless, so `trace.get_current_span()` (used for
log correlation) sees every span started here. Until `init_tracing()` runs, `get_tracer()`
is a no-op tracer and all instrumentation is inert.

Always call `get_tracer()` at use time — never cache a tracer at import.
"""

import json
import logging
from contextlib import contextmanager
from typing import Any, Iterator

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter

from app.observability import semconv as sc
from app.observability.redact import redact

logger = logging.getLogger(__name__)

_provider: TracerProvider | None = None
_NOOP = trace.NoOpTracer()


class RunAttributionProcessor(SpanProcessor):
    """Stamp `rotom.run.id` on every span started inside a run (via the run ContextVar)."""

    def on_start(self, span, parent_context=None) -> None:
        try:
            from app.observability.sink import current_run_id

            run_id = current_run_id.get()
            if run_id is not None and sc.ROTOM_RUN_ID not in (span.attributes or {}):
                span.set_attribute(sc.ROTOM_RUN_ID, int(run_id))
        except Exception:  # pragma: no cover - defensive: never raise into the traced work
            pass


def init_tracing(*, exporter: SpanExporter | None = None, simple: bool = False) -> None:
    """Install rotom's TracerProvider. Idempotent; `simple=True` exports synchronously (tests)."""
    global _provider
    if _provider is not None:
        return
    from app.observability.span_exporter import SqliteSpanExporter

    provider = TracerProvider(resource=Resource.create({"service.name": "rotom"}))
    provider.add_span_processor(RunAttributionProcessor())
    exp = exporter or SqliteSpanExporter()
    provider.add_span_processor(
        SimpleSpanProcessor(exp) if simple else BatchSpanProcessor(exp, schedule_delay_millis=2000)
    )
    from app.config import get_settings

    if get_settings().metrics_enabled:
        from app.observability.metrics import MetricsSpanProcessor

        provider.add_span_processor(MetricsSpanProcessor())
    _provider = provider


def shutdown_tracing() -> None:
    """Flush pending spans and drop the provider (process exit / test teardown)."""
    global _provider
    if _provider is not None:
        try:
            _provider.shutdown()
        except Exception:  # pragma: no cover - defensive
            logger.warning("tracing shutdown failed", exc_info=True)
        _provider = None


def get_tracer() -> trace.Tracer:
    return _provider.get_tracer("rotom") if _provider is not None else _NOOP


@contextmanager
def span(
    name: str,
    *,
    kind: trace.SpanKind = trace.SpanKind.INTERNAL,
    attributes: dict[str, Any] | None = None,
) -> Iterator[trace.Span]:
    """A current span for a unit of work; exceptions are recorded and mark it ERROR."""
    with get_tracer().start_as_current_span(name, kind=kind, attributes=attributes or {}) as s:
        yield s


def trace_id_of(s: trace.Span) -> str | None:
    ctx = s.get_span_context()
    return format(ctx.trace_id, "032x") if ctx.is_valid else None


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[:limit]}…[+{len(text) - limit} chars]"


def _clip(value: Any, limit: int) -> Any:
    if isinstance(value, str):
        return _truncate(redact(value), limit)  # redact first: truncation could split a secret
    if isinstance(value, dict):
        return {k: _clip(v, limit) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clip(v, limit) for v in value]
    return value


def set_content(s: trace.Span, key: str, value: Any) -> None:
    """Attach captured content (prompt/response/tool payload): per-string truncated,
    JSON-encoded, secret-redacted. No-op when capture is off or the span isn't recording."""
    try:
        from app.config import get_settings

        settings = get_settings()
        if not settings.obs_capture_content or not s.is_recording():
            return
        clipped = _clip(value, settings.obs_content_max_chars)
        encoded = clipped if isinstance(clipped, str) else json.dumps(clipped, default=str, ensure_ascii=False)
        s.set_attribute(key, redact(encoded))
    except Exception:  # pragma: no cover - defensive
        logger.warning("content capture failed for %s", key, exc_info=True)
