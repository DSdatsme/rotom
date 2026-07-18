import contextvars
import logging
import threading
from contextlib import contextmanager
from typing import Protocol, Any

from app.config import get_settings
from app.observability.events import UsageEvent, RunResult, RunStart

logger = logging.getLogger(__name__)

current_run_id = contextvars.ContextVar("current_run_id", default=None)
# The kind of the currently-open run (gmail_triage, reminder_fire, …) so logs
# emitted inside a run can be tagged with it, not just the run id.
current_run_kind = contextvars.ContextVar("current_run_kind", default=None)

# How often an open run bumps its heartbeat (seconds). Short runs finish before
# the first tick and never touch it; only long runs heartbeat, so the reaper can
# tell a genuinely-long run from a dead one.
HEARTBEAT_INTERVAL = 60

class ObservabilitySink(Protocol):
    def record_usage(self, e: UsageEvent) -> None: ...
    def start_run(self, run: RunStart) -> str | None: ...
    def finish_run(self, run_id: str, result: RunResult) -> None: ...
    def heartbeat(self, run_id: str) -> None: ...

class QueryProvider(Protocol):
    def list_runs(
        self, limit: int, *, source: str | None = None, kind: str | None = None
    ) -> list[dict[str, Any]]: ...
    def get_run(self, run_id: str) -> dict[str, Any] | None: ...
    def usage_by_model_day(self, days: int) -> list[dict[str, Any]]: ...
    def list_logs(
        self,
        *,
        level: str | None = None,
        kind: str | None = None,
        run_id: int | None = None,
        q: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 100,
        before_id: int | None = None,
    ) -> dict[str, Any]: ...

class CompositeSink:
    def __init__(self, sinks: list[ObservabilitySink]):
        self.sinks = sinks
        
    def record_usage(self, e: UsageEvent) -> None:
        for s in self.sinks:
            try:
                s.record_usage(e)
            except Exception as ex:
                logger.warning(f"Sink {s.__class__.__name__} failed to record usage: {ex}")

    def start_run(self, run: RunStart) -> str | None:
        run_id = None
        for s in self.sinks:
            try:
                r = s.start_run(run)
                if run_id is None:
                    run_id = r
            except Exception as ex:
                logger.warning(f"Sink {s.__class__.__name__} failed to start run: {ex}")
        return run_id

    def finish_run(self, run_id: str, result: RunResult) -> None:
        for s in self.sinks:
            try:
                s.finish_run(run_id, result)
            except Exception as ex:
                logger.warning(f"Sink {s.__class__.__name__} failed to finish run: {ex}")

    def heartbeat(self, run_id: str) -> None:
        for s in self.sinks:
            try:
                hb = getattr(s, "heartbeat", None)
                if hb is not None:
                    hb(run_id)
            except Exception as ex:
                logger.warning(f"Sink {s.__class__.__name__} failed to heartbeat: {ex}")

def get_sink() -> ObservabilitySink:
    settings = get_settings()
    backends = [b.strip() for b in settings.observability_backends.split(",") if b.strip()]

    sinks = []
    if "sqlite" in backends:
        from app.observability.sqlite_sink import SqliteSink
        sinks.append(SqliteSink())

    # Always wrap in CompositeSink — even a single sink — so every sink call is
    # exception-isolated. Observability must never take down the work it observes:
    # a failing/unavailable backend degrades to a stdout warning, not a crash.
    return CompositeSink(sinks)

def get_query_provider() -> QueryProvider:
    settings = get_settings()
    backends = [b.strip() for b in settings.observability_backends.split(",") if b.strip()]
    if "sqlite" in backends:
        from app.observability.sqlite_sink import SqliteSink
        return SqliteSink()
    raise NotImplementedError("No query provider found")


class RunContext:
    """Handle yielded by record_run so the body can set a summary or flag failure."""

    def __init__(self, run_id: str | None):
        self.run_id = run_id
        self.summary = ""
        self.error = ""
        self._failed = False
        self._degraded = False

    def fail(self, *, summary: str = "", error: str = "") -> None:
        """Mark the run as failed without raising (e.g. hard degraded-state runs)."""
        self._failed = True
        if summary:
            self.summary = summary
        if error:
            self.error = error

    def degrade(self, *, summary: str = "", error: str = "") -> None:
        """Mark the run as degraded: core work succeeded but a non-critical part
        (delivery, an account fetch) didn't. Surfaced as a warning, not a failure."""
        self._degraded = True
        if summary:
            self.summary = summary
        if error:
            self.error = error


@contextmanager
def record_run(
    kind: str,
    *,
    source: str = "system",
    external_id: str | None = None,
    external_url: str | None = None,
):
    """Track one unit of work as a RunLog.

    `kind` = *what ran* (gmail_triage, draft_generation, …); `source` = *how it was
    initiated* (scheduler | manual | chat | inngest | system). The enclosing run id
    (if any) is captured as `parent_run_id` BEFORE this run's id is set, so runs
    nested inside other runs link parent→child automatically — zero caller changes.

    Opens the run as `running`, propagates the run id (for log capture + LLM
    usage attribution), and finalizes status/summary/error/logs on exit:
    FAILURE if the body raises or calls run.fail(), SUCCESS otherwise.
    Exceptions raised by the *body* are recorded and re-raised — the caller
    decides how to surface them.

    Observability is best-effort and never breaks the work it observes: if the
    sink/DB is unavailable or failing, run tracking degrades to a stdout warning
    and the wrapped body still executes (with `run_id = None`, so logs/usage
    simply aren't attributed to a run).
    """
    # Lazy imports: logging_setup imports current_run_id from this module.
    from app.store.observability import RunStatus
    from app.logging_setup import _attach_buffer, _detach

    sink = get_sink()

    # Capture the enclosing run as our parent BEFORE we overwrite current_run_id.
    parent = current_run_id.get()

    run_id: str | None = None
    try:
        run_id = sink.start_run(RunStart(
            kind=kind,
            source=source,
            external_id=external_id,
            external_url=external_url,
            parent_run_id=parent,
        ))
    except Exception as ex:  # pragma: no cover - defensive
        logger.warning(f"observability: failed to start run {kind!r}: {ex}")

    handler = None
    if run_id is not None:
        try:
            handler = _attach_buffer(run_id)
        except Exception as ex:  # pragma: no cover - defensive
            logger.warning(f"observability: failed to attach log buffer for run {run_id}: {ex}")

    token = current_run_id.set(run_id)
    kind_token = current_run_kind.set(kind)
    ctx = RunContext(run_id)

    # Heartbeat: bump last_heartbeat_at on a daemon thread while the run is open,
    # so the reaper can distinguish a genuinely-long run from a dead one. Stopped
    # and joined on exit. Skipped entirely when run tracking is unavailable.
    stop_beat = threading.Event()
    beat_thread = None
    if run_id is not None:
        def _beat() -> None:
            while not stop_beat.wait(HEARTBEAT_INTERVAL):
                try:
                    sink.heartbeat(run_id)
                except Exception:  # pragma: no cover - defensive
                    pass
        beat_thread = threading.Thread(target=_beat, name=f"run-heartbeat-{run_id}", daemon=True)
        beat_thread.start()

    def _captured_logs() -> str:
        if handler is None:
            return ""
        try:
            return handler.text()
        except Exception:  # pragma: no cover - defensive
            return ""

    def _finish(status: str, *, summary: str, error: str) -> None:
        if run_id is None:
            return
        try:
            sink.finish_run(run_id, RunResult(
                status, summary=summary, error=error, logs=_captured_logs(),
            ))
        except Exception as ex:  # pragma: no cover - defensive
            logger.warning(f"observability: failed to finish run {run_id}: {ex}")

    try:
        yield ctx
    except Exception as exc:
        _finish(RunStatus.FAILURE, summary=ctx.summary or "Failed", error=ctx.error or str(exc))
        raise
    else:
        if ctx._failed:
            status = RunStatus.FAILURE
        elif ctx._degraded:
            status = RunStatus.DEGRADED
        else:
            status = RunStatus.SUCCESS
        _finish(status, summary=ctx.summary, error=ctx.error)
    finally:
        stop_beat.set()
        if beat_thread is not None:
            beat_thread.join(timeout=2)
        current_run_id.reset(token)
        current_run_kind.reset(kind_token)
        if handler is not None:
            try:
                _detach(handler)
            except Exception:  # pragma: no cover - defensive
                pass
