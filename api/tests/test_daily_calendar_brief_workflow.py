"""daily_calendar_brief: the step body (fetch → format → send as one run), its cron and
registration. Calendar accounts and Telegram are faked; no Inngest server."""

from datetime import datetime, timezone

import pytest

from app.config import get_settings
from app.store.observability import RunLog, RunStatus, get_obs_session
from app.workflows import daily_calendar_brief as wf
from app.workflows import lib


class _FakeAccount:
    def __init__(self, account, events=(), error=None):
        self.account = account
        self._events = list(events)
        self._error = error
        self.calls = []

    def list_events(self, time_min, time_max, tz_name):
        self.calls.append((time_min, time_max, tz_name))
        if self._error:
            raise self._error
        return self._events


def _event(title, start, end):
    return {"id": title, "summary": title, "start": {"dateTime": start}, "end": {"dateTime": end}}


@pytest.fixture()
def sent(monkeypatch):
    """Captured Telegram messages (deliver → notify is faked)."""
    messages: list[str] = []

    async def fake_notify(text: str) -> None:
        messages.append(text)

    monkeypatch.setattr(lib, "notify", fake_notify)
    monkeypatch.setattr(get_settings(), "telegram_enabled", True)
    monkeypatch.setattr(get_settings(), "timezone", "Asia/Kolkata")
    return messages


def _accounts(monkeypatch, *accounts):
    monkeypatch.setattr(wf, "load_accounts", lambda settings: list(accounts))


def _run_row() -> RunLog:
    with get_obs_session() as s:
        rows = s.query(RunLog).filter(RunLog.kind == "daily_calendar_brief").all()
    assert len(rows) == 1
    return rows[0]


# 20:00 UTC on Jul 28 is 01:30 on Jul 29 in Kolkata: "today" must be the owner's day.
NOW = datetime(2026, 7, 28, 20, 0, tzinfo=timezone.utc)


async def test_sends_the_brief_and_records_a_successful_run(obs_db, sent, monkeypatch):
    acc = _FakeAccount("work", [_event("Standup", "2026-07-29T09:00:00+05:30",
                                       "2026-07-29T09:30:00+05:30")])
    _accounts(monkeypatch, acc)

    assert await wf.send_daily_brief("inngest-run-1", now=NOW) == "sent"

    assert sent == ["📅 Today — Wed Jul 29\n\n09:00 Standup [work]"]
    row = _run_row()
    assert row.status == RunStatus.SUCCESS
    assert row.source == "inngest"
    assert row.external_id == "inngest-run-1"
    time_min, time_max, tz_name = acc.calls[0]
    assert time_min.isoformat() == "2026-07-29T00:00:00+05:30"
    assert time_max.isoformat() == "2026-07-30T00:00:00+05:30"
    assert tz_name == "Asia/Kolkata"


async def test_some_accounts_failing_is_degraded_and_names_them(obs_db, sent, monkeypatch):
    _accounts(monkeypatch, _FakeAccount("work"),
              _FakeAccount("personal", error=RuntimeError("invalid_grant")))

    await wf.send_daily_brief("r", now=NOW)

    assert sent[0].endswith("⚠ 1 account unavailable")
    row = _run_row()
    assert row.status == RunStatus.DEGRADED
    assert "personal: invalid_grant" in row.error


async def test_every_account_failing_is_a_failed_run_but_still_warns(obs_db, sent, monkeypatch):
    _accounts(monkeypatch, _FakeAccount("work", error=RuntimeError("invalid_grant")))

    await wf.send_daily_brief("r", now=NOW)

    assert "Couldn't read your calendar today" in sent[0]
    assert _run_row().status == RunStatus.FAILURE


async def test_no_accounts_is_a_failed_run(obs_db, sent, monkeypatch):
    _accounts(monkeypatch)

    await wf.send_daily_brief("r", now=NOW)

    assert "No calendar accounts connected" in sent[0]
    assert _run_row().status == RunStatus.FAILURE


async def test_telegram_off_sends_nothing_and_is_degraded(obs_db, sent, monkeypatch):
    monkeypatch.setattr(get_settings(), "telegram_enabled", False)
    _accounts(monkeypatch, _FakeAccount("work"))

    assert await wf.send_daily_brief("r", now=NOW) == "skipped: telegram off"

    assert sent == []
    row = _run_row()
    assert row.status == RunStatus.DEGRADED
    assert "not sent (telegram off)" in row.summary


async def test_failed_send_raises_for_a_retry_and_records_failure(obs_db, sent, monkeypatch):
    async def broken_notify(text):
        raise ConnectionError("telegram unreachable")

    monkeypatch.setattr(lib, "notify", broken_notify)
    _accounts(monkeypatch, _FakeAccount("work"))

    with pytest.raises(ConnectionError):
        await wf.send_daily_brief("r", now=NOW)

    assert _run_row().status == RunStatus.FAILURE


def test_cron_fires_at_local_time():
    crons = [t.cron for t in wf.daily_calendar_brief._triggers if hasattr(t, "cron")]
    assert crons == [f"TZ={get_settings().timezone} 30 8 * * *"]


def test_workflow_registered():
    from app.workflows.registry import WORKFLOW_FUNCTIONS
    assert wf.daily_calendar_brief in WORKFLOW_FUNCTIONS


async def test_run_summary_pluralizes(obs_db, sent, monkeypatch):
    _accounts(monkeypatch, _FakeAccount("work", [_event("Standup", "2026-07-29T09:00:00+05:30",
                                                         "2026-07-29T09:30:00+05:30")]),
              _FakeAccount("personal", error=RuntimeError("x")))

    await wf.send_daily_brief("r", now=NOW)

    assert _run_row().summary == "1 event · 1 account failed"


def test_inngest_wiring_runs_the_step_under_the_run_id(obs_db, sent, monkeypatch):
    import inngest
    from inngest.experimental import mocked

    _accounts(monkeypatch, _FakeAccount("work"))
    res = mocked.trigger(
        wf.daily_calendar_brief, inngest.Event(name="workflows/daily-calendar-brief.requested"),
        mocked.Inngest(app_id="test"),
    )

    assert res.status == mocked.Status.COMPLETED
    assert res.output == "sent"
    assert len(sent) == 1
    assert _run_row().external_id == "test"  # the mocked run id
