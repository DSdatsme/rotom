"""SqliteSpanExporter: finished OTel spans → the `span` table in observability.db.

Hot GenAI attributes are promoted to real columns so common SQL needs no JSON; the full
attribute map and span events are kept as JSON. Runs behind BatchSpanProcessor (prod)
or SimpleSpanProcessor (tests). Never raises: a failed batch is dropped with a warning.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Sequence

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from app.observability import semconv as sc
from app.observability.redact import redact

logger = logging.getLogger(__name__)


def _dt(ns: int | None) -> datetime | None:
    return datetime.fromtimestamp(ns / 1e9, timezone.utc) if ns else None


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def span_to_row(s: ReadableSpan) -> dict[str, Any]:
    ctx = s.context
    attrs = dict(s.attributes or {})
    start, end = s.start_time or 0, s.end_time or s.start_time or 0
    events = [
        {"name": e.name, "ts": _dt(e.timestamp).isoformat() if e.timestamp else None,
         "attributes": dict(e.attributes or {})}
        for e in s.events
    ]
    return {
        "span_id": format(ctx.span_id, "016x"),
        "trace_id": format(ctx.trace_id, "032x"),
        "parent_span_id": format(s.parent.span_id, "016x") if s.parent else None,
        "name": (s.name or "")[:256],
        "span_kind": s.kind.name,
        "start_time": _dt(start),
        "end_time": _dt(end),
        "duration_ms": (end - start) / 1e6,
        "status": s.status.status_code.name,
        "status_message": redact(s.status.description or ""),
        "run_id": _int(attrs.get(sc.ROTOM_RUN_ID)),
        "operation": attrs.get(sc.OPERATION_NAME),
        "provider": attrs.get(sc.PROVIDER_NAME),
        "model": attrs.get(sc.RESPONSE_MODEL) or attrs.get(sc.REQUEST_MODEL),
        "input_tokens": _int(attrs.get(sc.USAGE_INPUT_TOKENS)),
        "output_tokens": _int(attrs.get(sc.USAGE_OUTPUT_TOKENS)),
        "cache_read_tokens": _int(attrs.get(sc.USAGE_CACHE_READ_INPUT_TOKENS)),
        "reasoning_tokens": _int(attrs.get(sc.USAGE_REASONING_OUTPUT_TOKENS)),
        "cost_usd": _float(attrs.get(sc.ROTOM_COST_USD)),
        "attributes": redact(json.dumps(attrs, default=str, ensure_ascii=False)),
        "events": redact(json.dumps(events, default=str, ensure_ascii=False)),
    }


class SqliteSpanExporter(SpanExporter):
    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        from sqlalchemy import insert

        from app.store.observability import Span, get_obs_session

        try:
            rows = [span_to_row(s) for s in spans]
            if rows:
                with get_obs_session() as session:
                    session.execute(insert(Span).prefix_with("OR IGNORE"), rows)
                    session.commit()
            return SpanExportResult.SUCCESS
        except Exception:
            logger.warning("span export failed; dropped %d span(s)", len(spans), exc_info=True)
            return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True
