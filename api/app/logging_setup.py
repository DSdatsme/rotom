"""Logging wiring: handlers + noise policy.

The log *format* lives in app/observability/log_schema.py — edit that file to change
what a log line contains. This module only decides where lines go and which loggers
are too noisy to keep at INFO.
"""

import json
import logging
import threading
from datetime import datetime, timezone

from app.observability.log_schema import ContextFilter, JsonFormatter, to_event

# Third-party loggers capped at a level. httpx logs every request URL at INFO and
# Telegram's URLs embed the bot token; uvicorn.access and APScheduler job chatter are
# replaced by HTTP/run spans + metrics. sqlalchemy must stay ≥WARNING so its own INFO
# statements can't re-enter DbLogHandler.
NOISE_LEVELS: dict[str, int] = {
    "httpx": logging.WARNING,
    "httpcore": logging.WARNING,
    "uvicorn.access": logging.WARNING,
    "apscheduler.executors.default": logging.WARNING,
    "apscheduler.scheduler": logging.WARNING,
    "sqlalchemy": logging.WARNING,
}

# Event keys stored in dedicated log_entry columns; every other key goes to `extra`.
_LOG_ENTRY_COLUMNS = ("level", "logger", "msg", "run_id", "kind", "trace_id", "span_id", "exc_info")

_DB_FLUSH_EVERY = 20          # flush after this many buffered records
_DB_FLUSH_INTERVAL_SEC = 5.0  # …and at least this often
_FLUSH_WAIT_SEC = 2.0         # explicit flushes wait this long for an in-progress one


def _as_int(value) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


class DbLogHandler(logging.Handler):
    """Persist log records to `log_entry` (observability.db), buffered.

    Reentrancy-safe: ignores `sqlalchemy*` loggers and drops records the flushing thread
    emits during its own flush (other threads' records are kept for the next flush).
    One flush runs at a time. Never raises into the logging call.
    """

    _BLOCKED_PREFIXES = ("sqlalchemy",)

    def __init__(self):
        super().__init__()
        self.addFilter(ContextFilter())
        self._lock = threading.Lock()        # guards _buffer / _timer
        self._flush_lock = threading.Lock()  # serializes flushes
        self._local = threading.local()      # .flushing: this thread is inside _persist
        self._buffer: list = []
        self._timer: threading.Timer | None = None
        self._closed = False

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if self._closed or (record.name or "").startswith(self._BLOCKED_PREFIXES):
                return
            if getattr(self._local, "flushing", False):
                return  # re-entrancy from this thread's own flush — drop to avoid a storm
            with self._lock:
                self._buffer.append(record)
                should_flush = len(self._buffer) >= _DB_FLUSH_EVERY
            if should_flush:
                self._flush()
            elif self._timer is None:
                self._arm_timer()
        except Exception:
            self.handleError(record)

    def _arm_timer(self):
        with self._lock:
            if self._timer is None and not self._closed:
                t = threading.Timer(_DB_FLUSH_INTERVAL_SEC, self._on_timer)
                t.daemon = True
                t.start()
                self._timer = t

    def _on_timer(self):
        with self._lock:
            self._timer = None
        self._flush()

    def _flush(self, wait: float | None = None) -> None:
        """Persist the buffer. If another flush is running, `wait=None` (timer/size path)
        leaves the records for a re-armed timer; `wait=N` waits up to N s for it first."""
        try:
            acquired = (self._flush_lock.acquire(blocking=False) if wait is None
                        else self._flush_lock.acquire(timeout=wait))
        except Exception:
            return
        if not acquired:
            self._arm_timer()
            return
        try:
            with self._lock:
                records, self._buffer = self._buffer, []
            if records:
                self._local.flushing = True
                try:
                    self._persist(records)
                finally:
                    self._local.flushing = False
        except Exception:
            pass  # never let a flush kill the app
        finally:
            self._flush_lock.release()

    def _persist(self, records: list) -> None:
        from app.store.observability import LogEntry, get_obs_session

        entries = []
        for record in records:
            try:
                event = to_event(record)
                event.pop("ts", None)
                cols = {c: event.pop(c, None) for c in _LOG_ENTRY_COLUMNS}
                entries.append(LogEntry(
                    ts=datetime.fromtimestamp(record.created, timezone.utc),
                    level=(cols["level"] or "")[:16],
                    logger=(cols["logger"] or "")[:128],
                    msg=cols["msg"] or "",
                    run_id=_as_int(cols["run_id"]),
                    kind=str(cols["kind"]) if cols["kind"] else None,
                    trace_id=cols["trace_id"],
                    span_id=cols["span_id"],
                    exc_info=cols["exc_info"],
                    extra=json.dumps(event, default=str),
                ))
            except Exception:
                pass  # skip a bad record, keep the batch
        if not entries:
            return
        try:
            with get_obs_session() as session:
                session.add_all(entries)
                session.commit()
        except Exception:
            pass  # DB unavailable: the lines are still on stdout

    def close(self):
        self._closed = True
        if self._timer is not None:
            try:
                self._timer.cancel()
            except Exception:
                pass
        self._flush(wait=_FLUSH_WAIT_SEC)
        super().close()


_db_log_handler: DbLogHandler | None = None


def flush_db_logs() -> None:
    """Persist buffered records now (e.g. so a just-finished run's logs are queryable),
    waiting briefly for an in-progress flush rather than skipping."""
    if _db_log_handler is not None:
        _db_log_handler._flush(wait=_FLUSH_WAIT_SEC)


def setup_logging() -> None:
    global _db_log_handler
    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)
    root.setLevel(logging.INFO)
    for name, level in NOISE_LEVELS.items():
        logging.getLogger(name).setLevel(level)

    stdout = logging.StreamHandler()
    stdout.setFormatter(JsonFormatter())
    stdout.addFilter(ContextFilter())
    root.addHandler(stdout)

    _db_log_handler = DbLogHandler()
    root.addHandler(_db_log_handler)

    from app.config import get_settings

    if get_settings().metrics_enabled:
        from app.observability.metrics import LogCountHandler

        root.addHandler(LogCountHandler())
