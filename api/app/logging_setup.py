import json
import logging
import threading
from datetime import datetime, timezone
from app.observability.sink import current_run_id, current_run_kind

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, timezone.utc).isoformat()

        log_obj = {
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }

        if hasattr(record, "run_id") and record.run_id is not None:
            log_obj["run_id"] = record.run_id

        if record.exc_info:
            log_obj["exc_info"] = self.formatException(record.exc_info)

        std_attrs = {
            "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
            "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
            "created", "msecs", "relativeCreated", "thread", "threadName", "processName",
            "process", "taskName", "run_id", "message"
        }
        for k, v in record.__dict__.items():
            if k not in std_attrs:
                try:
                    json.dumps(v)
                    log_obj[k] = v
                except TypeError:
                    log_obj[k] = str(v)

        return json.dumps(log_obj)

class RunContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = current_run_id.get()
        record.kind = current_run_kind.get()
        return True

class JsonMemoryHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.setFormatter(JsonFormatter())
        self.records = []

    def emit(self, record):
        try:
            msg = self.format(record)
            self.records.append(msg)
        except Exception:
            self.handleError(record)

    def text(self) -> str:
        return "\n".join(self.records)

class RunCaptureFilter(logging.Filter):
    def __init__(self, run_id: str):
        super().__init__()
        self.run_id = run_id

    def filter(self, record: logging.LogRecord) -> bool:
        return getattr(record, "run_id", None) == self.run_id

def _attach_buffer(run_id: str):
    handler = JsonMemoryHandler()
    handler.addFilter(RunContextFilter())
    handler.addFilter(RunCaptureFilter(run_id))
    logging.getLogger().addHandler(handler)
    return handler

def _detach(handler):
    logging.getLogger().removeHandler(handler)


# ---------------------------------------------------------------------------
# Feature A: DbLogHandler — buffered, reentrancy-safe DB log persistence
# ---------------------------------------------------------------------------
# Design: we buffer records in-memory and flush every FLUSH_EVERY inserts or
# when a threading.Timer fires (FLUSH_INTERVAL_SEC). This keeps individual
# log statements fast while still persisting everything.
# A reentrancy guard (_writing flag + ignoring sqlalchemy loggers) prevents
# DB-write log messages from re-entering the handler and causing log storms.

_DB_FLUSH_EVERY = 20          # flush after this many buffered records
_DB_FLUSH_INTERVAL_SEC = 5.0  # also flush at least this often

class DbLogHandler(logging.Handler):
    """Persist log records to the LogEntry table in observability.db.

    Reentrancy-safe: ignores records from loggers whose names start with
    'sqlalchemy' to prevent DB INSERT logs from re-entering the handler.
    All exceptions in emit() are silently swallowed via self.handleError().
    """

    # Loggers that must be suppressed to avoid infinite reentrancy
    _BLOCKED_PREFIXES = ("sqlalchemy",)

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self._buffer: list = []
        self._writing = False
        self._timer: threading.Timer | None = None
        self._closed = False

    def _is_reentrancy_risk(self, record: logging.LogRecord) -> bool:
        name = record.name or ""
        return any(name.startswith(p) for p in self._BLOCKED_PREFIXES)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if self._closed:
                return
            if self._is_reentrancy_risk(record):
                return
            # Stamp run_id/kind if RunContextFilter hasn't already done it
            if not hasattr(record, "run_id"):
                record.run_id = current_run_id.get()
            if not hasattr(record, "kind"):
                record.kind = current_run_kind.get()

            with self._lock:
                if self._writing:
                    # Re-entrancy from our own flush path — drop to avoid storm
                    return
                self._buffer.append(record)
                should_flush = len(self._buffer) >= _DB_FLUSH_EVERY

            if should_flush:
                self._flush()
            elif self._timer is None:
                # Start a timer to ensure we flush within the interval
                self._arm_timer()
        except Exception:
            self.handleError(record)

    def _arm_timer(self):
        with self._lock:
            if self._timer is None and not self._closed:
                t = threading.Timer(_DB_FLUSH_INTERVAL_SEC, self._flush)
                t.daemon = True
                t.start()
                self._timer = t

    def _flush(self):
        with self._lock:
            if self._writing:
                return
            if not self._buffer:
                self._timer = None
                return
            records, self._buffer = self._buffer, []
            self._writing = True
            self._timer = None

        try:
            self._persist(records)
        except Exception:
            pass  # Never let flush kill the app
        finally:
            with self._lock:
                self._writing = False

    def _persist(self, records: list) -> None:
        """Write a batch of records to the DB."""
        import json as _json
        from datetime import datetime, timezone
        from app.store.observability import get_obs_session, LogEntry

        std_attrs = {
            "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
            "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
            "created", "msecs", "relativeCreated", "thread", "threadName", "processName",
            "process", "taskName", "run_id", "message", "kind",
        }

        entries = []
        for record in records:
            try:
                ts = datetime.fromtimestamp(record.created, timezone.utc)
                msg = record.getMessage()
                if record.exc_info:
                    formatter = logging.Formatter()
                    exc_text = formatter.formatException(record.exc_info)
                    msg = f"{msg}\n{exc_text}" if exc_text else msg

                run_id_val = getattr(record, "run_id", None)
                run_id_int: int | None = None
                if run_id_val is not None:
                    try:
                        run_id_int = int(run_id_val)
                    except (TypeError, ValueError):
                        pass

                # Capture any extra structured fields
                extra: dict = {}
                for k, v in record.__dict__.items():
                    if k not in std_attrs and not k.startswith("_"):
                        try:
                            _json.dumps(v)
                            extra[k] = v
                        except TypeError:
                            extra[k] = str(v)

                # Run kind, stamped on the record by RunContextFilter (excluded
                # from `extra` via std_attrs). Only meaningful inside a run.
                kind_raw = getattr(record, "kind", None)
                kind_val: str | None = str(kind_raw) if kind_raw else None

                entries.append(LogEntry(
                    ts=ts,
                    level=record.levelname[:16],
                    logger=(record.name or "")[:128],
                    msg=msg,
                    run_id=run_id_int,
                    kind=kind_val,
                    extra=_json.dumps(extra),
                ))
            except Exception:
                pass  # Skip a bad record, don't abort the batch

        if not entries:
            return

        try:
            with get_obs_session() as session:
                session.add_all(entries)
                session.commit()
        except Exception:
            pass  # DB write failure: log is lost, but app continues

    def close(self):
        """Final flush on shutdown."""
        self._closed = True
        if self._timer is not None:
            try:
                self._timer.cancel()
            except Exception:
                pass
        # Flush remaining buffer synchronously
        with self._lock:
            records, self._buffer = self._buffer, []
            self._writing = True
        try:
            if records:
                self._persist(records)
        except Exception:
            pass
        finally:
            with self._lock:
                self._writing = False
        super().close()


_db_log_handler: DbLogHandler | None = None


def setup_logging():
    global _db_log_handler
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    root_logger.setLevel(logging.INFO)

    # Prevent SQLAlchemy INFO/DEBUG from causing reentrancy in DbLogHandler
    # (SQLAlchemy logs SQL statements at INFO level when echo=True, and various
    # internal messages; keeping it at WARNING is safe for production use)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    # Stdout JSON handler (existing)
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RunContextFilter())
    root_logger.addHandler(handler)

    # Feature A: DB persistence handler
    _db_log_handler = DbLogHandler()
    _db_log_handler.addFilter(RunContextFilter())
    root_logger.addHandler(_db_log_handler)
