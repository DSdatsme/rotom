"""Tests for Feature A (LogEntry/list_logs) and Feature B (latency_ms)."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture()
def obs_db(tmp_path):
    """Fresh observability DB per test with migrations applied."""
    from app.store import observability as obs

    engine = create_engine(f"sqlite:///{tmp_path / 'obs.db'}")
    obs.ObsBase.metadata.create_all(engine)
    obs._migrate(engine)
    obs._engine = engine
    obs._SessionFactory = sessionmaker(engine, expire_on_commit=False)
    yield obs
    obs._engine = None
    obs._SessionFactory = None


# ---------------------------------------------------------------------------
# Feature A: LogEntry model + list_logs
# ---------------------------------------------------------------------------

def test_log_entry_can_be_persisted(obs_db):
    from app.store.observability import LogEntry, get_obs_session
    from datetime import datetime, timezone

    with get_obs_session() as s:
        entry = LogEntry(
            ts=datetime.now(timezone.utc),
            level="INFO",
            logger="app.foo",
            msg="hello world",
        )
        s.add(entry)
        s.commit()
        assert entry.id is not None


def test_list_logs_returns_newest_first(obs_db):
    from app.observability.sqlite_sink import SqliteSink
    from app.store.observability import LogEntry, get_obs_session
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    with get_obs_session() as s:
        for i in range(3):
            s.add(LogEntry(
                ts=now + timedelta(seconds=i),
                level="INFO",
                logger="test",
                msg=f"msg {i}",
            ))
        s.commit()

    sink = SqliteSink()
    result = sink.list_logs(limit=10)
    logs = result["logs"]
    assert len(logs) == 3
    # newest first
    assert logs[0]["msg"] == "msg 2"
    assert logs[2]["msg"] == "msg 0"


def test_list_logs_level_filter(obs_db):
    from app.observability.sqlite_sink import SqliteSink
    from app.store.observability import LogEntry, get_obs_session
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    with get_obs_session() as s:
        for level in ("INFO", "WARNING", "ERROR"):
            s.add(LogEntry(ts=now, level=level, logger="t", msg=f"{level} msg"))
        s.commit()

    sink = SqliteSink()
    result = sink.list_logs(level="ERROR")
    assert len(result["logs"]) == 1
    assert result["logs"][0]["level"] == "ERROR"


def test_list_logs_level_filter_comma_separated(obs_db):
    from app.observability.sqlite_sink import SqliteSink
    from app.store.observability import LogEntry, get_obs_session
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    with get_obs_session() as s:
        for level in ("INFO", "WARNING", "ERROR", "DEBUG"):
            s.add(LogEntry(ts=now, level=level, logger="t", msg=f"{level} msg"))
        s.commit()

    sink = SqliteSink()
    result = sink.list_logs(level="WARNING,ERROR")
    levels = {r["level"] for r in result["logs"]}
    assert levels == {"WARNING", "ERROR"}


def test_list_logs_text_search(obs_db):
    from app.observability.sqlite_sink import SqliteSink
    from app.store.observability import LogEntry, get_obs_session
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    with get_obs_session() as s:
        s.add(LogEntry(ts=now, level="INFO", logger="t", msg="needle in haystack"))
        s.add(LogEntry(ts=now, level="INFO", logger="t", msg="nothing special here"))
        s.commit()

    sink = SqliteSink()
    result = sink.list_logs(q="needle")
    assert len(result["logs"]) == 1
    assert "needle" in result["logs"][0]["msg"]


def test_list_logs_run_id_filter(obs_db):
    from app.observability.sqlite_sink import SqliteSink
    from app.store.observability import LogEntry, get_obs_session
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    with get_obs_session() as s:
        s.add(LogEntry(ts=now, level="INFO", logger="t", msg="with run", run_id=42))
        s.add(LogEntry(ts=now, level="INFO", logger="t", msg="no run"))
        s.commit()

    sink = SqliteSink()
    result = sink.list_logs(run_id=42)
    assert len(result["logs"]) == 1
    assert result["logs"][0]["run_id"] == 42


def test_list_logs_cursor_pagination(obs_db):
    from app.observability.sqlite_sink import SqliteSink
    from app.store.observability import LogEntry, get_obs_session
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    with get_obs_session() as s:
        for i in range(10):
            s.add(LogEntry(ts=now + timedelta(seconds=i), level="INFO", logger="t", msg=f"msg {i}"))
        s.commit()

    sink = SqliteSink()
    # Page 1: get 5
    page1 = sink.list_logs(limit=5)
    assert len(page1["logs"]) == 5
    assert page1["next_before_id"] is not None

    # Page 2: use the cursor
    page2 = sink.list_logs(limit=5, before_id=page1["next_before_id"])
    assert len(page2["logs"]) == 5
    assert page2["next_before_id"] is None  # no more rows

    # Ensure no overlap
    ids1 = {r["id"] for r in page1["logs"]}
    ids2 = {r["id"] for r in page2["logs"]}
    assert ids1.isdisjoint(ids2)


def test_list_logs_since_until_filter(obs_db):
    from app.observability.sqlite_sink import SqliteSink
    from app.store.observability import LogEntry, get_obs_session
    from datetime import datetime, timezone, timedelta

    base = datetime(2024, 1, 10, 12, 0, 0, tzinfo=timezone.utc)
    with get_obs_session() as s:
        for i in range(5):
            s.add(LogEntry(ts=base + timedelta(hours=i), level="INFO", logger="t", msg=f"h{i}"))
        s.commit()

    sink = SqliteSink()
    result = sink.list_logs(
        since=(base + timedelta(hours=1)).isoformat(),
        until=(base + timedelta(hours=3)).isoformat(),
    )
    assert len(result["logs"]) == 3  # hours 1, 2, 3


def test_list_logs_kind_filter(obs_db):
    from app.observability.sqlite_sink import SqliteSink
    from app.store.observability import LogEntry, get_obs_session
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    with get_obs_session() as s:
        s.add(LogEntry(ts=now, level="INFO", logger="t", msg="m1", kind="triage"))
        s.add(LogEntry(ts=now, level="INFO", logger="t", msg="m2", kind="draft"))
        s.commit()

    sink = SqliteSink()
    result = sink.list_logs(kind="triage")
    assert len(result["logs"]) == 1
    assert result["logs"][0]["kind"] == "triage"


def test_list_logs_no_next_before_id_when_all_fit(obs_db):
    from app.observability.sqlite_sink import SqliteSink
    from app.store.observability import LogEntry, get_obs_session
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    with get_obs_session() as s:
        for i in range(3):
            s.add(LogEntry(ts=now, level="INFO", logger="t", msg=f"m{i}"))
        s.commit()

    sink = SqliteSink()
    result = sink.list_logs(limit=10)
    assert result["next_before_id"] is None


# ---------------------------------------------------------------------------
# Feature B: latency_ms on LLMUsage + UsageEvent
# ---------------------------------------------------------------------------

def test_usage_event_carries_latency(obs_db):
    from app.observability.events import UsageEvent
    from datetime import datetime, timezone

    e = UsageEvent(
        provider="test",
        model="m",
        role="draft",
        input_tokens=10,
        output_tokens=5,
        run_id=None,
        ts=datetime.now(timezone.utc),
        latency_ms=320,
    )
    assert e.latency_ms == 320


def test_usage_event_latency_defaults_to_none(obs_db):
    from app.observability.events import UsageEvent
    from datetime import datetime, timezone

    e = UsageEvent(
        provider="test",
        model="m",
        role="draft",
        input_tokens=10,
        output_tokens=5,
        run_id=None,
        ts=datetime.now(timezone.utc),
    )
    assert e.latency_ms is None


def test_sqlite_sink_persists_latency(obs_db):
    from app.observability.sqlite_sink import SqliteSink
    from app.observability.events import UsageEvent
    from app.store.observability import LLMUsage, get_obs_session
    from datetime import datetime, timezone

    sink = SqliteSink()
    e = UsageEvent(
        provider="test",
        model="test-model",
        role="draft",
        input_tokens=100,
        output_tokens=50,
        run_id=None,
        ts=datetime.now(timezone.utc),
        latency_ms=450,
    )
    sink.record_usage(e)

    with get_obs_session() as s:
        row = s.query(LLMUsage).first()
        assert row.latency_ms == 450


def test_sqlite_sink_latency_none_is_stored_as_null(obs_db):
    from app.observability.sqlite_sink import SqliteSink
    from app.observability.events import UsageEvent
    from app.store.observability import LLMUsage, get_obs_session
    from datetime import datetime, timezone

    sink = SqliteSink()
    e = UsageEvent(
        provider="test",
        model="test-model",
        role="draft",
        input_tokens=10,
        output_tokens=5,
        run_id=None,
        ts=datetime.now(timezone.utc),
        latency_ms=None,
    )
    sink.record_usage(e)

    with get_obs_session() as s:
        row = s.query(LLMUsage).first()
        assert row.latency_ms is None


def test_get_run_includes_avg_latency_in_metrics(obs_db):
    from app.observability.sqlite_sink import SqliteSink
    from app.observability.events import UsageEvent, RunStart
    from datetime import datetime, timezone

    sink = SqliteSink()
    run_id = sink.start_run(RunStart(kind="test"))

    # Add two usages with different latencies for same model
    for lat in (100, 200):
        sink.record_usage(UsageEvent(
            provider="test", model="m1", role="draft",
            input_tokens=10, output_tokens=5,
            run_id=run_id, ts=datetime.now(timezone.utc),
            latency_ms=lat,
        ))

    result = sink.get_run(run_id)
    assert result is not None
    metric = result["metrics"][0]
    assert metric["avg_latency_ms"] == 150  # (100+200)/2


def test_usage_by_model_day_includes_avg_latency(obs_db):
    from app.observability.sqlite_sink import SqliteSink
    from app.observability.events import UsageEvent
    from datetime import datetime, timezone

    sink = SqliteSink()
    for lat in (200, 400):
        sink.record_usage(UsageEvent(
            provider="test", model="m1", role="draft",
            input_tokens=10, output_tokens=5,
            run_id=None, ts=datetime.now(timezone.utc),
            latency_ms=lat,
        ))

    results = sink.usage_by_model_day(days=1)
    assert len(results) == 1
    assert results[0]["avg_latency_ms"] == 300


# ---------------------------------------------------------------------------
# Feature A: DbLogHandler robustness
# ---------------------------------------------------------------------------

def test_db_log_handler_does_not_persist_sqlalchemy_logs(obs_db):
    """SQLAlchemy logs must not re-enter the handler."""
    import logging
    from app.logging_setup import DbLogHandler
    from app.store.observability import LogEntry, get_obs_session

    handler = DbLogHandler()
    handler.addFilter(lambda r: True)

    # Emit a sqlalchemy.engine record — it should be silently dropped
    record = logging.LogRecord(
        name="sqlalchemy.engine",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="SELECT 1",
        args=(),
        exc_info=None,
    )
    handler.emit(record)
    # Wait for potential async flush
    import time
    time.sleep(0.1)
    handler.close()

    with get_obs_session() as s:
        count = s.query(LogEntry).count()
    assert count == 0  # Nothing was persisted


def test_db_log_handler_persists_normal_records(obs_db):
    """Normal log records should be buffered and flushed to DB."""
    import logging
    from app.logging_setup import DbLogHandler
    from app.store.observability import LogEntry, get_obs_session

    handler = DbLogHandler()

    record = logging.LogRecord(
        name="app.test",
        level=logging.WARNING,
        pathname="",
        lineno=0,
        msg="test warning",
        args=(),
        exc_info=None,
    )
    handler.emit(record)
    # Force flush
    handler._flush()

    with get_obs_session() as s:
        entries = s.query(LogEntry).filter(LogEntry.msg == "test warning").all()
    assert len(entries) == 1
    assert entries[0].level == "WARNING"


def test_db_log_handler_batch_flush(obs_db):
    """Records should all end up in DB after a flush."""
    import logging
    from app.logging_setup import DbLogHandler
    from app.store.observability import LogEntry, get_obs_session

    handler = DbLogHandler()

    for i in range(5):
        record = logging.LogRecord(
            name="app.test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=f"batch msg {i}",
            args=(),
            exc_info=None,
        )
        # Manually add to buffer to avoid auto-flush triggering at _DB_FLUSH_EVERY
        with handler._lock:
            handler._buffer.append(record)

    handler._flush()

    with get_obs_session() as s:
        count = s.query(LogEntry).filter(LogEntry.logger == "app.test").count()
    assert count == 5


# ---------------------------------------------------------------------------
# Feature A: log retention
# ---------------------------------------------------------------------------

def test_prune_old_logs(obs_db):
    from app.store.observability import LogEntry, get_obs_session, _prune_old_logs
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    with get_obs_session() as s:
        # Old log (15 days ago)
        s.add(LogEntry(ts=now - timedelta(days=15), level="INFO", logger="t", msg="old"))
        # Recent log
        s.add(LogEntry(ts=now - timedelta(hours=1), level="INFO", logger="t", msg="recent"))
        s.commit()

    from app.store.observability import _engine
    _prune_old_logs(_engine, retention_days=14)

    with get_obs_session() as s:
        remaining = s.query(LogEntry).all()
    assert len(remaining) == 1
    assert remaining[0].msg == "recent"


def test_prune_with_zero_retention_keeps_all(obs_db):
    from app.store.observability import LogEntry, get_obs_session, _prune_old_logs
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    with get_obs_session() as s:
        s.add(LogEntry(ts=now - timedelta(days=100), level="INFO", logger="t", msg="ancient"))
        s.commit()

    from app.store.observability import _engine
    _prune_old_logs(_engine, retention_days=0)

    with get_obs_session() as s:
        count = s.query(LogEntry).count()
    assert count == 1


# ---------------------------------------------------------------------------
# Feature B: UsageCallback latency tracking
# ---------------------------------------------------------------------------

def test_usage_callback_tracks_latency(obs_db):
    """UsageCallback.on_llm_start + on_llm_end should produce a latency_ms > 0."""
    import uuid
    from unittest.mock import MagicMock, patch
    from app.llm.provider import UsageCallback
    from app.observability.events import UsageEvent

    captured: list[UsageEvent] = []

    cb = UsageCallback(provider="test", model="m", role="draft")
    lc_run_id = uuid.uuid4()

    # Simulate start
    cb.on_llm_start({}, [], run_id=lc_run_id)

    import time
    time.sleep(0.01)  # ensure some time passes

    # Build a minimal LLMResult
    from langchain_core.outputs import LLMResult
    result = LLMResult(generations=[], llm_output={})

    with patch("app.llm.provider.get_sink") as mock_sink:
        sink_instance = MagicMock()
        mock_sink.return_value = sink_instance
        cb.on_llm_end(result, run_id=lc_run_id)

    call_args = sink_instance.record_usage.call_args
    assert call_args is not None
    event: UsageEvent = call_args[0][0]
    assert event.latency_ms is not None
    assert event.latency_ms >= 10  # at least 10ms since we slept 10ms


def test_usage_callback_latency_none_without_start(obs_db):
    """If on_llm_start was never called, latency_ms should be None."""
    import uuid
    from unittest.mock import MagicMock, patch
    from app.llm.provider import UsageCallback
    from app.observability.events import UsageEvent
    from langchain_core.outputs import LLMResult

    cb = UsageCallback(provider="test", model="m", role="draft")

    result = LLMResult(generations=[], llm_output={})
    with patch("app.llm.provider.get_sink") as mock_sink:
        sink_instance = MagicMock()
        mock_sink.return_value = sink_instance
        cb.on_llm_end(result, run_id=uuid.uuid4())

    event: UsageEvent = sink_instance.record_usage.call_args[0][0]
    assert event.latency_ms is None
