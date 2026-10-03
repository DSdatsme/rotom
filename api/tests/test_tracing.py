"""Tracing core: span export, record_run spans, context propagation, content capture."""

import asyncio
import json

import pytest

from tests.conftest import span_rows


def test_span_helper_exports_row(traced):
    from app.observability.tracing import span

    with span("unit.work", attributes={"rotom.count": 3}):
        pass
    (row,) = span_rows(name="unit.work")
    assert row.status == "UNSET"
    assert row.parent_span_id is None
    assert len(row.trace_id) == 32 and len(row.span_id) == 16
    assert json.loads(row.attributes)["rotom.count"] == 3
    assert row.duration_ms >= 0


def test_span_records_exception_as_error(traced):
    from app.observability.tracing import span

    with pytest.raises(ValueError):
        with span("unit.fail"):
            raise ValueError("nope")
    (row,) = span_rows(name="unit.fail")
    assert row.status == "ERROR"
    events = json.loads(row.events)
    assert events[0]["name"] == "exception"
    assert "nope" in events[0]["attributes"]["exception.message"]


def test_record_run_creates_root_span_and_links_trace_id(traced):
    from app.observability.sink import get_query_provider, record_run

    with record_run("gmail_triage", source="scheduler") as run:
        run.summary = "3 fetched"
    (root,) = span_rows(name="gmail_triage")
    detail = get_query_provider().get_run(run.run_id)
    assert detail["trace_id"] == root.trace_id
    assert root.run_id == int(run.run_id)
    attrs = json.loads(root.attributes)
    assert attrs["rotom.run.kind"] == "gmail_triage"
    assert attrs["rotom.run.source"] == "scheduler"
    assert attrs["rotom.run.status"] == "success"
    assert attrs["rotom.run.summary"] == "3 fetched"


def test_spans_inside_run_carry_run_id_and_nest(traced):
    from app.observability.sink import record_run
    from app.observability.tracing import span

    with record_run("k") as run:
        with span("inner.step"):
            pass
    (root,) = span_rows(name="k")
    (inner,) = span_rows(name="inner.step")
    assert inner.parent_span_id == root.span_id
    assert inner.trace_id == root.trace_id
    assert inner.run_id == int(run.run_id)


def test_nested_record_run_is_child_span(traced):
    from app.observability.sink import record_run

    with record_run("outer"):
        with record_run("inner"):
            pass
    (outer,) = span_rows(name="outer")
    (inner,) = span_rows(name="inner")
    assert inner.parent_span_id == outer.span_id


def test_failed_run_span_is_error(traced):
    from app.observability.sink import record_run

    with record_run("k") as run:
        run.fail(summary="2 accounts failed", error="quota")
    (root,) = span_rows(name="k")
    assert root.status == "ERROR"
    assert json.loads(root.attributes)["rotom.run.status"] == "failure"


def test_degraded_run_span_is_ok_with_status_attr(traced):
    from app.observability.sink import record_run

    with record_run("k") as run:
        run.degrade(summary="digest not sent")
    (root,) = span_rows(name="k")
    assert root.status != "ERROR"
    assert json.loads(root.attributes)["rotom.run.status"] == "degraded"


def test_record_run_without_tracing_still_works(obs_db):
    from app.observability.sink import get_query_provider, record_run

    with record_run("k") as run:
        pass
    detail = get_query_provider().get_run(run.run_id)
    assert detail["status"] == "success"
    assert detail["trace_id"] is None


async def test_to_thread_keeps_span_parent(traced):
    from app.observability.tracing import span

    def work():
        with span("thread.child"):
            pass

    with span("async.parent"):
        await asyncio.to_thread(work)
    (parent,) = span_rows(name="async.parent")
    (child,) = span_rows(name="thread.child")
    assert child.parent_span_id == parent.span_id


def test_set_content_truncates_and_redacts(traced, monkeypatch):
    from app.config import get_settings
    from app.observability.tracing import set_content, span

    monkeypatch.setattr(get_settings(), "obs_content_max_chars", 20)
    token = "1234567890:AAAbbbCCCdddEEEfffGGGhhhIIIjjjKKKlll0"
    with span("c") as s:
        set_content(s, "gen_ai.input.messages", [{"role": "user", "content": f"bot{token} " + "x" * 100}])
    (row,) = span_rows(name="c")
    raw = json.loads(row.attributes)["gen_ai.input.messages"]
    msgs = json.loads(raw)
    assert "1234567890:AAA" not in raw  # redacted BEFORE truncation — no partial token survives
    assert msgs[0]["content"].startswith("bot[REDACTED]")
    assert "…[+" in msgs[0]["content"]


def test_set_content_disabled(traced, monkeypatch):
    from app.config import get_settings
    from app.observability.tracing import set_content, span

    monkeypatch.setattr(get_settings(), "obs_capture_content", False)
    with span("c") as s:
        set_content(s, "gen_ai.input.messages", "secret prompt")
    (row,) = span_rows(name="c")
    assert "gen_ai.input.messages" not in json.loads(row.attributes)


def test_semconv_version_recorded(traced):
    from sqlalchemy import text

    from app.observability.semconv import SEMCONV_VERSION

    with traced._engine.connect() as conn:
        assert traced._meta_get(conn, "genai.semconv_version") == SEMCONV_VERSION


def test_log_lines_inside_run_carry_trace_id(traced):
    import logging

    from app.logging_setup import DbLogHandler
    from app.observability.sink import record_run
    from app.store.observability import LogEntry, get_obs_session

    handler = DbLogHandler()
    log = logging.getLogger("app.test.tracing")
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    try:
        with record_run("k"):
            log.info("inside")
        handler._flush()
    finally:
        log.removeHandler(handler)
        handler.close()
    (root,) = span_rows(name="k")
    with get_obs_session() as s:
        row = s.query(LogEntry).filter(LogEntry.msg == "inside").one()
    assert row.trace_id == root.trace_id
