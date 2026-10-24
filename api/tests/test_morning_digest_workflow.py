"""morning_digest: cron, failure recording, and skipping the LLM when Telegram is off.
No Inngest server, no LLM, no network."""

from app.config import get_settings
from app.store.observability import RunLog, RunStatus, get_obs_session
from app.workflows import morning_digest as wf


def _rows():
    with get_obs_session() as s:
        return s.query(RunLog).filter(RunLog.kind == "morning_digest").all()


def test_cron_fires_at_local_time():
    crons = [t.cron for t in wf.morning_digest._triggers if hasattr(t, "cron")]
    assert crons == [f"TZ={get_settings().timezone} 30 8 * * *"]


async def test_failure_handler_records_a_failed_morning_digest_run(obs_db):
    class Ctx:
        run_id = "failure-handler-run"
        event = type("Event", (), {"data": {"run_id": "r-1", "error": {"message": "boom"}}})()

    await wf.morning_digest._opts.on_failure(Ctx())

    (row,) = _rows()
    assert (row.status, row.external_id) == (RunStatus.FAILURE, "r-1")


def test_telegram_off_skips_the_fetch_and_the_llm_call(obs_db, monkeypatch):
    import inngest
    from inngest.experimental import mocked

    async def no_calls(*args, **kwargs):
        raise AssertionError("no fetch or LLM call when Telegram is off")

    monkeypatch.setattr(get_settings(), "telegram_enabled", False)
    monkeypatch.setattr(wf, "run_script", no_calls)
    monkeypatch.setattr(wf, "llm", no_calls)

    res = mocked.trigger(wf.morning_digest, inngest.Event(name="workflows/morning-digest.requested"),
                         mocked.Inngest(app_id="test"))

    assert res.output == "skipped: telegram off"
    (row,) = _rows()
    assert (row.status, row.external_id) == (RunStatus.DEGRADED, "test")


def test_workflow_registered():
    from app.workflows.registry import WORKFLOW_FUNCTIONS
    assert wf.morning_digest in WORKFLOW_FUNCTIONS
