"""THE log format — the single source of truth for every log line rotom emits.

stdout (JSON lines) and the `log_entry` table (and through it the dashboard's Logs
explorer, run detail and trace view) all build records with `to_event()`. To add,
rename or drop a field, or change redaction, edit this file only.

Run/trace context is stamped onto the record by `ContextFilter` at emit time, in the
emitting thread, so handlers that buffer and write later (DbLogHandler) keep the right ids.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any

from opentelemetry import trace

from app.observability.redact import redact, redact_obj
from app.observability.sink import current_run_id, current_run_kind

# Ordered core fields; anything passed via `extra={...}` follows them.
CORE_FIELDS = (
    "ts", "level", "logger", "msg", "filename", "lineno",
    "run_id", "kind", "trace_id", "span_id", "exc_info",
)

# LogRecord internals that are never emitted as extra fields.
_RECORD_INTERNALS = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename", "module",
    "exc_info", "exc_text", "stack_info", "lineno", "funcName", "created", "msecs",
    "relativeCreated", "thread", "threadName", "processName", "process", "taskName",
    "message", "asctime", "color_message", "run_id", "kind", "trace_id", "span_id",
})

_exc_formatter = logging.Formatter()


class ContextFilter(logging.Filter):
    """Stamp run + trace context onto a record once, in the thread that emitted it."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "trace_id"):
            record.run_id = current_run_id.get()
            record.kind = current_run_kind.get()
            ctx = trace.get_current_span().get_span_context()
            record.trace_id = format(ctx.trace_id, "032x") if ctx.is_valid else None
            record.span_id = format(ctx.span_id, "016x") if ctx.is_valid else None
        return True


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return redact(str(value))


def to_event(record: logging.LogRecord) -> dict[str, Any]:
    """LogRecord → ordered, redacted, JSON-safe event dict."""
    exc = None
    if record.exc_info:
        exc = redact(_exc_formatter.formatException(record.exc_info))
    elif record.exc_text:
        exc = redact(record.exc_text)
    event: dict[str, Any] = {
        "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
        "level": record.levelname,
        "logger": record.name,
        "msg": redact(record.getMessage()),
        "filename": record.filename,
        "lineno": record.lineno,
        "run_id": getattr(record, "run_id", None),
        "kind": getattr(record, "kind", None),
        "trace_id": getattr(record, "trace_id", None),
        "span_id": getattr(record, "span_id", None),
        "exc_info": exc,
    }
    for key, value in record.__dict__.items():
        if key in _RECORD_INTERNALS or key.startswith("_") or key in event:
            continue
        event[key] = _json_safe(redact_obj(value))
    return event


def render(event: dict[str, Any]) -> str:
    """One JSON line; null fields are dropped to keep stdout readable."""
    return json.dumps({k: v for k, v in event.items() if v is not None}, default=str)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return render(to_event(record))
