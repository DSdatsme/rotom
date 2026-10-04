"""Dashboard read models, SQL views, read API, retention."""

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from sqlalchemy import text

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _llm_call(cb, *, inp=100, out=10, model="gemini-2.5-flash", fail=False):
    rid = uuid.uuid4()
    cb.on_chat_model_start({}, [[HumanMessage("x")]], run_id=rid)
    if fail:
        cb.on_llm_error(TimeoutError("t"), run_id=rid)
        return
    msg = AIMessage(content="y", usage_metadata={"input_tokens": inp, "output_tokens": out, "total_tokens": inp + out},
                    response_metadata={"model_name": model})
    cb.on_llm_end(LLMResult(generations=[[ChatGeneration(message=msg)]]), run_id=rid)


@pytest.fixture()
def seeded(traced):
    from app.observability.llm_tracing import LlmTracingCallback
    from app.observability.sink import record_run
    from app.observability.tracing import span

    cb = LlmTracingCallback("gemini", "gemini-2.5-flash", "classify")
    with record_run("gmail_triage", source="scheduler") as ok:
        with span("triage.classify"):
            _llm_call(cb)
            _llm_call(cb, fail=True)
    with record_run("gmail_triage", source="manual") as bad:
        bad.fail(summary="all accounts failed", error="quota")
    with record_run("reminder_fire", source="scheduler") as deg:
        deg.degrade(summary="not delivered")
    return {"ok": ok.run_id, "bad": bad.run_id, "deg": deg.run_id}


def test_overview_kpis_series_jobs_problems(seeded):
    from app.observability import queries

    o = queries.overview(24)
    k = o["kpis"]
    assert (k["runs"], k["runs_ok"], k["problems"]) == (3, 1, 2)
    assert (k["llm_calls"], k["llm_errors"]) == (2, 1)
    assert k["cost_usd"] > 0
    assert o["bucket"] == "hour" and len(o["buckets"]) in (24, 25)
    assert sum(b["success"] + b["failure"] + b["degraded"] for b in o["runs_series"]) == 3
    jobs = {j["kind"]: j for j in o["jobs"]}
    assert jobs["gmail_triage"]["runs"] == 2 and jobs["gmail_triage"]["problems"] == 1
    assert jobs["gmail_triage"]["last_status"] == "failure"
    assert {p["status"] for p in o["problems"] if p["type"] == "run"} == {"failure", "degraded"}
    assert all(p["trace_id"] for p in o["problems"] if p["type"] == "run")


def test_overview_day_buckets_for_long_windows(seeded):
    from app.observability import queries

    o = queries.overview(24 * 7)
    assert o["bucket"] == "day" and len(o["buckets"]) in (7, 8)


def test_traces_list_types_status_and_aggregates(seeded):
    from app.observability import queries

    res = queries.traces()
    assert len(res["traces"]) == 3
    first_ok = [t for t in res["traces"] if t["run_id"] == int(seeded["ok"])][0]
    assert first_ok["trace_type"] == "run"
    assert first_ok["llm_calls"] == 2
    assert first_ok["error_count"] == 1
    assert first_ok["run_status"] == "success"
    errors = queries.traces(status="error")["traces"]
    assert [t["run_id"] for t in errors] == [int(seeded["bad"])]
    assert queries.traces(trace_type="chat")["traces"] == []
    page = queries.traces(limit=2)
    assert len(page["traces"]) == 2 and page["next_before"]
    rest = queries.traces(limit=2, before=page["next_before"])["traces"]
    assert len(rest) == 1


def test_trace_detail_spans_logs_run(seeded):
    from app.observability import queries
    from app.store.observability import LogEntry, get_obs_session

    t = [x for x in queries.traces()["traces"] if x["run_id"] == int(seeded["ok"])][0]
    with get_obs_session() as s:
        s.add(LogEntry(ts=datetime.now(timezone.utc), level="INFO", logger="t", msg="hi", trace_id=t["trace_id"]))
        s.commit()
    d = queries.trace_detail(t["trace_id"])
    names = [sp["name"] for sp in d["spans"]]
    assert names[0] == "gmail_triage"
    assert "triage.classify" in names
    chat = [sp for sp in d["spans"] if sp["operation"] == "chat"][0]
    assert isinstance(chat["attributes"], dict)
    assert d["logs"][0]["msg"] == "hi"
    assert d["run"]["id"] == int(seeded["ok"])
    assert queries.trace_detail("f" * 32) is None


def test_trace_detail_with_orphan_spans(traced):
    from app.observability import queries
    from app.store.observability import Span, get_obs_session

    now = datetime.now(timezone.utc)
    with get_obs_session() as s:
        s.add(Span(span_id="c" * 16, trace_id="e" * 32, parent_span_id="d" * 16, name="child",
                   start_time=now, end_time=now, duration_ms=1.0))
        s.commit()
    d = queries.trace_detail("e" * 32)
    assert [sp["name"] for sp in d["spans"]] == ["child"]
    assert queries.traces()["traces"] == []  # no root yet → not listed


def test_llm_stats_groups_and_percentiles(seeded):
    from app.observability import queries

    st = queries.llm_stats(7)
    assert st["kpis"]["calls"] == 2 and st["kpis"]["errors"] == 1
    (m,) = st["by_model"]
    assert m["model"] == "gemini-2.5-flash" and m["calls"] == 2 and m["errors"] == 1
    (r,) = st["by_role"]
    assert r["role"] == "classify"
    assert st["recent"][0]["run_kind"] == "gmail_triage"
    assert st["kpis"]["p95_ms"] is not None


def test_views_are_queryable(seeded):
    from app.store.observability import get_obs_session

    with get_obs_session() as s:
        runs = s.execute(text("SELECT kind, llm_calls, cost_usd FROM v_runs ORDER BY run_id")).all()
        assert runs[0][1] == 2 and runs[0][2] > 0
        assert s.execute(text("SELECT COUNT(*) FROM v_traces")).scalar_one() == 3
        assert s.execute(text("SELECT COUNT(*) FROM v_llm_calls WHERE role = 'classify'")).scalar_one() == 2
        assert s.execute(text("SELECT COUNT(*) FROM v_errors WHERE source = 'span'")).scalar_one() >= 2
        s.execute(text("SELECT * FROM v_tool_calls")).all()


def test_prune_removes_old_logs_and_spans(obs_db, monkeypatch):
    from app.config import get_settings
    from app.store.observability import LogEntry, Span, get_obs_session, prune_observability

    old = datetime.now(timezone.utc) - timedelta(days=60)
    now = datetime.now(timezone.utc)
    with get_obs_session() as s:
        s.add(LogEntry(ts=old, level="INFO", logger="t", msg="old"))
        s.add(LogEntry(ts=now, level="INFO", logger="t", msg="new"))
        s.add(Span(span_id="1" * 16, trace_id="1" * 32, name="old", start_time=old, end_time=old, duration_ms=0))
        s.add(Span(span_id="2" * 16, trace_id="2" * 32, name="new", start_time=now, end_time=now, duration_ms=0))
        s.commit()
    monkeypatch.setattr(get_settings(), "log_retention_days", 14)
    monkeypatch.setattr(get_settings(), "trace_retention_days", 30)
    prune_observability()
    with get_obs_session() as s:
        assert [r.msg for r in s.query(LogEntry).all()] == ["new"]
        assert [r.name for r in s.query(Span).all()] == ["new"]


def test_prune_same_day_cutoff_is_exact(obs_db):
    """v1 compared ISO 'T' strings against space-separated stored values."""
    from app.store.observability import LogEntry, _prune_old_logs, get_obs_session

    now = datetime.now(timezone.utc)
    with get_obs_session() as s:
        s.add(LogEntry(ts=now - timedelta(days=1, minutes=1), level="INFO", logger="t", msg="older"))
        s.add(LogEntry(ts=now - timedelta(days=1) + timedelta(minutes=1), level="INFO", logger="t", msg="newer"))
        s.commit()
    from app.store import observability as obs

    _prune_old_logs(obs._engine, retention_days=1)
    with get_obs_session() as s:
        assert [r.msg for r in s.query(LogEntry).all()] == ["newer"]


@pytest.fixture()
def api(session_db, seeded):
    from app.api.routes import create_app

    return TestClient(create_app(api_token=TOKEN))


def test_read_api_endpoints(api, seeded):
    o = api.get("/api/observability/overview?hours=24", headers=AUTH).json()
    assert o["kpis"]["runs"] == 3
    t = api.get("/api/observability/traces?limit=10", headers=AUTH).json()
    assert len(t["traces"]) == 3
    tid = t["traces"][0]["trace_id"]
    assert api.get(f"/api/observability/traces/{tid}", headers=AUTH).json()["trace_id"] == tid
    assert api.get("/api/observability/traces/" + "0" * 32, headers=AUTH).status_code == 404
    assert api.get("/api/observability/llm?days=7", headers=AUTH).json()["kpis"]["calls"] == 2
    assert api.get("/api/observability/overview").status_code == 401


def test_views_and_queries_use_semconv_names(seeded):
    from app.observability import semconv as sc
    from app.store.observability import get_obs_session

    with get_obs_session() as s:
        ddl = dict(s.execute(text("SELECT name, sql FROM sqlite_master WHERE type = 'view'")).all())
    assert sc.ROTOM_LLM_ROLE in ddl["v_llm_calls"] and sc.OP_CHAT in ddl["v_llm_calls"]
    assert sc.TOOL_NAME in ddl["v_tool_calls"] and sc.OP_EXECUTE_TOOL in ddl["v_tool_calls"]
    assert sc.ROTOM_RUN_KIND in ddl["v_traces"] and sc.OP_INVOKE_AGENT in ddl["v_traces"]
