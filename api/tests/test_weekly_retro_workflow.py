"""weekly_retro: the window, the step body (compile → send as one run), cron and
registration. Telegram is faked; no Inngest server."""

from datetime import datetime, timedelta, timezone

import pytest

from app.config import get_settings
from app.store.observability import RunLog, RunStatus, get_obs_session
from app.workflows import lib
from app.workflows import weekly_retro as wf


@pytest.fixture()
def sent(monkeypatch):
    messages: list[str] = []

    async def fake_notify(text: str) -> None:
        messages.append(text)

    monkeypatch.setattr(lib, "notify", fake_notify)
    monkeypatch.setattr(get_settings(), "telegram_enabled", True)
    return messages


def test_window_always_contains_last_weeks_cron_run():
    # This week's cron fires 0.7s past 18:00 IST; last week's fired 0.9s past. Both are
    # "the 18:00 run", so last week's must be inside the window despite the jitter.
    this_week = datetime(2026, 8, 2, 12, 30, 0, 700000, tzinfo=timezone.utc)
    last_week = datetime(2026, 7, 26, 12, 30, 0, 900000, tzinfo=timezone.utc)
    since = wf.retro_window_start(this_week, "Asia/Kolkata")
    assert since == datetime(2026, 7, 26, 12, 30, tzinfo=timezone.utc)
    assert last_week >= since
    assert last_week - timedelta(minutes=1) < since


async def test_sends_the_retro_and_records_a_successful_run(session_db, obs_db, sent):
    assert await wf.send_weekly_retro("inngest-run-1") == "sent"

    assert len(sent) == 1
    assert sent[0].startswith("📊 Weekly retro")
    assert "none this week" in sent[0]  # its own in-flight run isn't counted
    with get_obs_session() as s:
        row = s.query(RunLog).filter(RunLog.kind == "weekly_retro").one()
    assert row.status == RunStatus.SUCCESS
    assert row.external_id == "inngest-run-1"


async def test_telegram_off_sends_nothing_and_is_degraded(session_db, obs_db, sent, monkeypatch):
    monkeypatch.setattr(get_settings(), "telegram_enabled", False)

    assert await wf.send_weekly_retro("r") == "skipped: telegram off"

    assert sent == []
    with get_obs_session() as s:
        row = s.query(RunLog).filter(RunLog.kind == "weekly_retro").one()
    assert row.status == RunStatus.DEGRADED


def test_cron_fires_at_local_time():
    crons = [t.cron for t in wf.weekly_retro._triggers if hasattr(t, "cron")]
    assert crons == [f"TZ={get_settings().timezone} 0 18 * * 0"]


def test_workflow_registered():
    from app.workflows.registry import WORKFLOW_FUNCTIONS
    assert wf.weekly_retro in WORKFLOW_FUNCTIONS


def test_window_uses_wall_clock_days_across_a_dst_change():
    # New York falls back on 2026-11-01. The Sunday 18:00 run that day (23:00Z) must reach
    # back to the previous Sunday's 18:00 EDT run (22:00Z), not to 23:00Z, which is 7×24h.
    this_week = datetime(2026, 11, 1, 23, 0, 0, 500000, tzinfo=timezone.utc)
    last_week = datetime(2026, 10, 25, 22, 0, 0, 900000, tzinfo=timezone.utc)
    since = wf.retro_window_start(this_week, "America/New_York")
    assert since == datetime(2026, 10, 25, 22, 0, tzinfo=timezone.utc)
    assert last_week >= since


def test_inngest_wiring_runs_the_step_under_the_run_id(session_db, obs_db, sent):
    import inngest
    from inngest.experimental import mocked

    res = mocked.trigger(
        wf.weekly_retro, inngest.Event(name="workflows/weekly-retro.requested"),
        mocked.Inngest(app_id="test"),
    )

    assert res.status == mocked.Status.COMPLETED
    assert res.output == "sent"
    assert len(sent) == 1
    with get_obs_session() as s:
        row = s.query(RunLog).filter(RunLog.kind == "weekly_retro").one()
    assert row.external_id == "test"  # the mocked run id
