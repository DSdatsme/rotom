"""Central log schema: fields, redaction, context stamping, DB persistence."""

import json
import logging

import pytest

FAKE_BOT_TOKEN = "1234567890:AAAbbbCCCdddEEEfffGGGhhhIIIjjjKKKlll0"


def _record(msg="hello %s", args=("world",), level=logging.INFO, name="app.test", **extra):
    r = logging.LogRecord(name, level, "/x/app/test.py", 42, msg, args, None)
    for k, v in extra.items():
        setattr(r, k, v)
    return r


def test_to_event_has_ordered_core_fields():
    from app.observability.log_schema import CORE_FIELDS, to_event

    event = to_event(_record())
    assert tuple(event)[: len(CORE_FIELDS)] == CORE_FIELDS
    assert event["msg"] == "hello world"
    assert event["level"] == "INFO"
    assert event["filename"] == "test.py"
    assert event["lineno"] == 42


def test_extra_fields_follow_core_fields():
    from app.observability.log_schema import to_event

    event = to_event(_record(account="personal", count=3))
    assert event["account"] == "personal"
    assert event["count"] == 3


def test_redacts_telegram_token_in_httpx_style_message():
    from app.observability.log_schema import to_event

    msg = f'HTTP Request: POST https://api.telegram.org/bot{FAKE_BOT_TOKEN}/getUpdates "HTTP/1.1 200 OK"'
    event = to_event(_record(msg=msg, args=()))
    assert FAKE_BOT_TOKEN not in event["msg"]
    assert "[REDACTED]" in event["msg"]


def test_redacts_configured_secret_values(monkeypatch):
    from app.observability import redact as R
    from app.observability.log_schema import to_event

    monkeypatch.setenv("SOME_SERVICE_TOKEN", "plain-secret-value-123456")
    R.secret_values.cache_clear()
    try:
        event = to_event(_record(msg="using plain-secret-value-123456 now", args=()))
    finally:
        R.secret_values.cache_clear()
    assert "plain-secret-value-123456" not in event["msg"]


def test_redacts_exc_info_and_extras():
    from app.observability.log_schema import to_event

    try:
        raise RuntimeError(f"boom at https://api.telegram.org/bot{FAKE_BOT_TOKEN}/send")
    except RuntimeError:
        import sys
        rec = _record(msg="failed", args=(), url=f"https://x/bot{FAKE_BOT_TOKEN}/y")
        rec.exc_info = sys.exc_info()
    event = to_event(rec)
    assert FAKE_BOT_TOKEN not in event["exc_info"]
    assert "RuntimeError" in event["exc_info"]
    assert FAKE_BOT_TOKEN not in event["url"]


def test_redact_patterns_cover_common_token_shapes():
    from app.observability.redact import redact

    for secret in (
        "Bearer abcdefghijklmnop1234",
        "AIza" + "A" * 35,
        "sk-ant-" + "a" * 30,
        "gsk_" + "a" * 30,
        "ghp_" + "a" * 36,
    ):
        assert secret not in redact(f"x {secret} y")
    assert redact("nothing secret here 12:30:00") == "nothing secret here 12:30:00"


def test_render_drops_null_fields_and_is_json():
    from app.observability.log_schema import render, to_event

    line = render(to_event(_record()))
    parsed = json.loads(line)
    assert "trace_id" not in parsed  # no active span → dropped
    assert parsed["msg"] == "hello world"


def test_context_filter_stamps_trace_and_run_ids():
    from opentelemetry.sdk.trace import TracerProvider

    from app.observability.log_schema import ContextFilter, to_event
    from app.observability.sink import current_run_id

    tracer = TracerProvider().get_tracer("t")
    token = current_run_id.set("7")
    try:
        with tracer.start_as_current_span("x") as sp:
            rec = _record()
            ContextFilter().filter(rec)
            expected = format(sp.get_span_context().trace_id, "032x")
    finally:
        current_run_id.reset(token)
    event = to_event(rec)
    assert event["trace_id"] == expected
    assert len(event["span_id"]) == 16
    assert event["run_id"] == "7"


def test_db_handler_persists_trace_columns_exc_and_extra(obs_db):
    from opentelemetry.sdk.trace import TracerProvider

    from app.logging_setup import DbLogHandler
    from app.store.observability import LogEntry, get_obs_session

    handler = DbLogHandler()
    tracer = TracerProvider().get_tracer("t")
    with tracer.start_as_current_span("x"):
        try:
            raise ValueError("bad")
        except ValueError:
            import sys
            rec = _record(msg="oops", args=(), level=logging.ERROR, account="work")
            rec.exc_info = sys.exc_info()
            handler.handle(rec)  # handle() runs filters (ContextFilter) like a real logger
    handler._flush()
    with get_obs_session() as s:
        row = s.query(LogEntry).one()
    assert row.msg == "oops"
    assert row.trace_id and len(row.trace_id) == 32
    assert "ValueError" in row.exc_info
    extra = json.loads(row.extra)
    assert extra["account"] == "work"
    assert extra["lineno"] == 42
    handler.close()


def test_setup_logging_applies_noise_policy(obs_db):
    from app import logging_setup

    root = logging.getLogger()
    saved = (root.handlers[:], root.level)
    try:
        logging_setup.setup_logging()
        assert logging.getLogger("httpx").level == logging.WARNING
        assert logging.getLogger("uvicorn.access").level == logging.WARNING
        assert any(isinstance(h, logging_setup.DbLogHandler) for h in root.handlers)
    finally:
        for h in root.handlers[:]:
            root.removeHandler(h)
            h.close()
        root.handlers[:] = saved[0]
        root.setLevel(saved[1])
        logging_setup._db_log_handler = None


def test_get_run_renders_logs_from_log_entry(obs_db):
    from datetime import datetime, timezone

    from app.observability.events import RunStart
    from app.observability.sqlite_sink import SqliteSink
    from app.store.observability import LogEntry, get_obs_session

    sink = SqliteSink()
    run_id = sink.start_run(RunStart(kind="k"))
    with get_obs_session() as s:
        s.add(LogEntry(ts=datetime.now(timezone.utc), level="INFO", logger="app.x",
                       msg="step one", run_id=int(run_id), extra='{"lineno": 3}'))
        s.add(LogEntry(ts=datetime.now(timezone.utc), level="ERROR", logger="app.x",
                       msg="step two", run_id=int(run_id), exc_info="Traceback: boom"))
        s.commit()
    lines = [json.loads(l) for l in sink.get_run(run_id)["logs"].splitlines()]
    assert [l["msg"] for l in lines] == ["step one", "step two"]
    assert lines[0]["lineno"] == 3
    assert lines[1]["exc_info"] == "Traceback: boom"


def test_scrub_migration_masks_existing_rows(obs_db, monkeypatch):
    from datetime import datetime, timezone

    from sqlalchemy import text

    from app.observability import redact as R
    from app.store.observability import LogEntry, _migrate, get_obs_session

    monkeypatch.setenv("LEAKY_BOT_TOKEN", FAKE_BOT_TOKEN)
    R.secret_values.cache_clear()
    try:
        with get_obs_session() as s:
            s.add(LogEntry(ts=datetime.now(timezone.utc), level="INFO", logger="httpx",
                           msg=f"GET https://api.telegram.org/bot{FAKE_BOT_TOKEN}/getMe"))
            s.commit()
        with obs_db._engine.begin() as conn:
            conn.execute(text("DELETE FROM obs_meta WHERE key = 'scrub.secrets.v1'"))
        _migrate(obs_db._engine)
        with get_obs_session() as s:
            assert FAKE_BOT_TOKEN not in s.query(LogEntry).one().msg
    finally:
        R.secret_values.cache_clear()


def test_list_logs_filters_by_trace_id(obs_db):
    from datetime import datetime, timezone

    from app.observability.sqlite_sink import SqliteSink
    from app.store.observability import LogEntry, get_obs_session

    with get_obs_session() as s:
        s.add(LogEntry(ts=datetime.now(timezone.utc), level="INFO", logger="t", msg="a", trace_id="a" * 32))
        s.add(LogEntry(ts=datetime.now(timezone.utc), level="INFO", logger="t", msg="b", trace_id="b" * 32))
        s.commit()
    res = SqliteSink().list_logs(trace_id="a" * 32)
    assert [r["msg"] for r in res["logs"]] == ["a"]
    assert res["logs"][0]["trace_id"] == "a" * 32
