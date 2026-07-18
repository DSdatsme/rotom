import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture()
def obs_db(tmp_path):
    """Point the observability sink at a throwaway SQLite file."""
    from app.store import observability as obs

    engine = create_engine(f"sqlite:///{tmp_path / 'obs.db'}")
    obs.ObsBase.metadata.create_all(engine)
    obs._engine = engine
    obs._SessionFactory = sessionmaker(engine, expire_on_commit=False)
    yield obs
    obs._engine = None
    obs._SessionFactory = None


def test_record_run_is_running_mid_flight_then_success(obs_db):
    from app.observability.sink import record_run, get_query_provider

    with record_run("test_kind") as run:
        run.summary = "did a thing"
        live = get_query_provider().get_run(run.run_id)
        assert live["status"] == "running"

    done = get_query_provider().get_run(run.run_id)
    assert done["status"] == "success"
    assert done["summary"] == "did a thing"
    assert done["finished_at"] is not None


def test_record_run_marks_failure_and_records_error_on_exception(obs_db):
    from app.observability.sink import record_run, get_query_provider

    captured = {}
    with pytest.raises(ValueError):
        with record_run("test_kind") as run:
            captured["id"] = run.run_id
            raise ValueError("boom")

    done = get_query_provider().get_run(captured["id"])
    assert done["status"] == "failure"
    assert "boom" in done["error"]


def test_record_run_fail_without_exception_marks_failure(obs_db):
    from app.observability.sink import record_run, get_query_provider

    with record_run("test_kind") as run:
        run.fail(summary="2 accounts failed")

    done = get_query_provider().get_run(run.run_id)
    assert done["status"] == "failure"
    assert done["summary"] == "2 accounts failed"


def test_record_run_persists_source_and_external_fields(obs_db):
    from app.observability.sink import record_run, get_query_provider

    with record_run(
        "workflow:demo", source="inngest",
        external_id="ing_123", external_url="http://localhost:8288/runs/ing_123",
    ) as run:
        pass

    done = get_query_provider().get_run(run.run_id)
    assert done["source"] == "inngest"
    assert done["external_id"] == "ing_123"
    assert done["external_url"].endswith("ing_123")


def test_record_run_nests_child_under_enclosing_run(obs_db):
    from app.observability.sink import record_run, get_query_provider

    outer_id = None
    inner_id = None
    with record_run("workflow:parent", source="scheduler") as outer:
        outer_id = outer.run_id
        with record_run("gmail_triage", source="scheduler") as inner:
            inner_id = inner.run_id

    qp = get_query_provider()
    parent = qp.get_run(outer_id)
    child = qp.get_run(inner_id)

    # Top-level run has no parent
    assert parent["parent_run_id"] is None
    # Nested run links to the enclosing run, both directions
    assert child["parent_run_id"] == int(outer_id)
    assert child["parent"]["id"] == int(outer_id)
    assert [c["id"] for c in parent["children"]] == [int(inner_id)]


def test_top_level_runs_are_not_nested(obs_db):
    from app.observability.sink import record_run, get_query_provider

    with record_run("a") as r1:
        pass
    with record_run("b") as r2:
        pass

    qp = get_query_provider()
    assert qp.get_run(r1.run_id)["parent_run_id"] is None
    assert qp.get_run(r2.run_id)["parent_run_id"] is None


def test_list_runs_filters_by_source_and_kind(obs_db):
    from app.observability.sink import record_run, get_query_provider

    with record_run("gmail_triage", source="scheduler"):
        pass
    with record_run("gmail_triage", source="manual"):
        pass
    with record_run("draft_generation", source="manual"):
        pass

    qp = get_query_provider()
    assert {r["kind"] for r in qp.list_runs(50, source="manual")} == {"gmail_triage", "draft_generation"}
    assert {r["source"] for r in qp.list_runs(50, kind="gmail_triage")} == {"scheduler", "manual"}
    assert len(qp.list_runs(50, source="scheduler", kind="gmail_triage")) == 1


def test_reaper_marks_stale_running_run_interrupted(obs_db):
    from datetime import datetime, timedelta, timezone
    from app.observability.sqlite_sink import SqliteSink
    from app.observability.events import RunStart
    from app.store.observability import get_obs_session, RunLog, RunStatus

    sink = SqliteSink()
    run_id = sink.start_run(RunStart(kind="gmail_triage", source="scheduler"))

    # Backdate started_at + clear heartbeat so it looks dead.
    with get_obs_session() as s:
        row = s.get(RunLog, int(run_id))
        row.started_at = datetime.now(timezone.utc) - timedelta(minutes=30)
        row.last_heartbeat_at = None
        s.commit()

    assert sink.reap_stale_runs() == 1
    done = sink.get_run(run_id)
    assert done["status"] == RunStatus.INTERRUPTED
    assert done["finished_at"] is not None


def test_reaper_spares_recent_and_inngest_runs(obs_db):
    from datetime import datetime, timedelta, timezone
    from app.observability.sqlite_sink import SqliteSink
    from app.observability.events import RunStart
    from app.store.observability import get_obs_session, RunLog, RunStatus

    sink = SqliteSink()
    fresh = sink.start_run(RunStart(kind="gmail_triage", source="scheduler"))  # just started, heartbeat now
    inngest = sink.start_run(RunStart(kind="workflow:x", source="inngest"))

    # Make the inngest run look ancient — it must STILL be spared.
    with get_obs_session() as s:
        row = s.get(RunLog, int(inngest))
        row.started_at = datetime.now(timezone.utc) - timedelta(hours=2)
        row.last_heartbeat_at = None
        s.commit()

    assert sink.reap_stale_runs() == 0
    assert sink.get_run(fresh)["status"] == RunStatus.RUNNING
    assert sink.get_run(inngest)["status"] == RunStatus.RUNNING


def test_record_run_runs_body_when_sink_is_down(obs_db, monkeypatch):
    """Observability is best-effort: a failing/unavailable sink must NOT stop the
    wrapped work. The body still runs and exceptions from it still propagate."""
    import app.observability.sink as sink_mod

    class _BrokenSink:
        def start_run(self, kind):
            raise RuntimeError("db unavailable")

        def finish_run(self, run_id, result):
            raise RuntimeError("db unavailable")

        def record_usage(self, e):
            raise RuntimeError("db unavailable")

    # get_sink already wraps in CompositeSink (which isolates per-sink errors),
    # but assert the end-to-end contract: body executes, no crash, run_id is None.
    monkeypatch.setattr(sink_mod, "get_sink", lambda: sink_mod.CompositeSink([_BrokenSink()]))

    ran = {"body": False}
    with sink_mod.record_run("test_kind") as run:
        ran["body"] = True
        assert run.run_id is None  # tracking degraded, work continues

    assert ran["body"] is True


def test_record_run_propagates_body_error_even_when_sink_down(obs_db, monkeypatch):
    import app.observability.sink as sink_mod

    class _BrokenSink:
        def start_run(self, kind):
            raise RuntimeError("db unavailable")

        def finish_run(self, run_id, result):
            raise RuntimeError("db unavailable")

    monkeypatch.setattr(sink_mod, "get_sink", lambda: sink_mod.CompositeSink([_BrokenSink()]))

    with pytest.raises(ValueError):
        with sink_mod.record_run("test_kind"):
            raise ValueError("body error")
