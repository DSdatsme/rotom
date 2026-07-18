"""Tests for tools/reminders — service lifecycle and NL parser plumbing."""

from datetime import datetime, timedelta, timezone

import pytest

from app.store.db import Reminder, ReminderStatus, get_session
from app.tools.reminders.parser import ReminderProposal, parse_reminder
from app.tools.reminders.service import cancel_reminder, create_reminder, list_reminders, next_fire_at


class FakeScheduler:
    def __init__(self):
        self.jobs: dict[str, dict] = {}

    def add_job(self, func, trigger, args=None, id=None, **kw):
        self.jobs[id] = {"func": func, "trigger": trigger, "args": args}

    def get_job(self, job_id):
        job = self.jobs.get(job_id)
        if job is None:
            return None

        class _J:
            def remove(_self):
                del self.jobs[job_id]

        return _J()


@pytest.fixture()
def fake_scheduler(monkeypatch):
    sched = FakeScheduler()
    monkeypatch.setattr("app.scheduler.jobs.get_scheduler", lambda: sched)
    return sched


def in_one_hour() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=1)


def test_create_reminder_stores_and_schedules(session_db, fake_scheduler):
    r = create_reminder("call mom", in_one_hour())
    assert r.id is not None
    assert f"reminder-{r.id}" in fake_scheduler.jobs
    with get_session() as s:
        assert s.get(Reminder, r.id).status == ReminderStatus.PENDING


def test_create_reminder_rejects_past_time(session_db, fake_scheduler):
    with pytest.raises(ValueError, match="past"):
        create_reminder("too late", datetime.now(timezone.utc) - timedelta(minutes=5))


def test_create_reminder_rejects_bad_cron(session_db, fake_scheduler):
    with pytest.raises(ValueError):
        create_reminder("bad", in_one_hour(), recurrence_cron="not a cron")


def test_cancel_reminder_removes_job(session_db, fake_scheduler):
    r = create_reminder("call mom", in_one_hour())
    assert cancel_reminder(r.id) is True
    assert f"reminder-{r.id}" not in fake_scheduler.jobs
    with get_session() as s:
        assert s.get(Reminder, r.id).status == ReminderStatus.CANCELLED
    assert cancel_reminder(r.id) is False  # already cancelled


def test_next_fire_at_one_time_and_recurring(session_db, fake_scheduler):
    when = in_one_hour()
    one = create_reminder("once", when)
    rec = create_reminder("weekly", in_one_hour(), recurrence_cron="0 9 * * mon")
    assert abs((next_fire_at(one) - when).total_seconds()) < 1
    nxt = next_fire_at(rec)
    assert nxt is not None and nxt > datetime.now(timezone.utc)


def test_list_reminders_filters_by_status(session_db, fake_scheduler):
    a = create_reminder("a", in_one_hour())
    create_reminder("b", in_one_hour())
    cancel_reminder(a.id)
    pending = list_reminders(status=ReminderStatus.PENDING)
    assert [r.text for r in pending] == ["b"]


def test_recurrence_shorthands(session_db, fake_scheduler):
    from zoneinfo import ZoneInfo

    from app.tools.reminders.recurrence import normalize_recurrence

    # 9:30am Monday in IST
    fire = datetime(2026, 6, 8, 9, 30, tzinfo=ZoneInfo("Asia/Kolkata"))
    n = lambda e: normalize_recurrence(e, fire, "Asia/Kolkata")  # noqa: E731
    assert n("") == ""
    assert n("everyday") == "30 9 * * *"
    assert n("Daily") == "30 9 * * *"
    assert n("weekdays") == "30 9 * * mon-fri"
    assert n("weekends") == "30 9 * * sat,sun"
    assert n("weekly") == "30 9 * * mon"  # anchored to fire_at's weekday
    assert n("every monday") == "30 9 * * mon"
    assert n("tuesdays") == "30 9 * * tue"
    assert n("monthly") == "30 9 8 * *"
    assert n("hourly") == "30 * * * *"
    assert n("15 7 * * mon") == "15 7 * * mon"  # raw cron passthrough
    with pytest.raises(ValueError, match="everyday"):
        n("whenever I feel like it")


def test_monthly_clamps_day_to_28(session_db, fake_scheduler):
    # A "monthly" reminder created on the 31st must still fire every month — not
    # silently skip Feb/Apr/Jun/Sep/Nov. We clamp the day-of-month to 28.
    from zoneinfo import ZoneInfo
    from app.tools.reminders.recurrence import normalize_recurrence

    fire = datetime(2026, 1, 31, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert normalize_recurrence("monthly", fire, "Asia/Kolkata") == "0 9 28 * *"
    # A day <= 28 is preserved.
    fire2 = datetime(2026, 1, 10, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert normalize_recurrence("monthly", fire2, "Asia/Kolkata") == "0 9 10 * *"


def test_raw_cron_rejects_numeric_day_of_week(session_db, fake_scheduler):
    # APScheduler reads numeric DOW as 0=Mon (vs standard cron 1=Mon), so a numeric
    # DOW would fire one day off. Names are the only safe form — reject digits.
    from zoneinfo import ZoneInfo
    from app.tools.reminders.recurrence import normalize_recurrence

    fire = datetime(2026, 6, 8, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    with pytest.raises(ValueError):
        normalize_recurrence("0 9 * * 1", fire, "Asia/Kolkata")
    # Name form is accepted.
    assert normalize_recurrence("0 9 * * mon", fire, "Asia/Kolkata") == "0 9 * * mon"
    # A numeric day-of-MONTH (3rd field) is still fine — only DOW (5th) is unsafe.
    assert normalize_recurrence("0 9 15 * *", fire, "Asia/Kolkata") == "0 9 15 * *"


def test_create_reminder_accepts_shorthand(session_db, fake_scheduler):
    r = create_reminder("standup", in_one_hour(), recurrence_cron="everyday")
    assert r.recurrence_cron.endswith("* * *")  # normalized to cron
    assert f"reminder-{r.id}" in fake_scheduler.jobs


class FakeLLM:
    def __init__(self, result):
        self.result = result

    def with_structured_output(self, schema):
        return self

    def invoke(self, prompt):
        self.prompt = prompt
        return self.result


def test_parse_reminder_validates_future_and_wraps_message():
    fire = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    llm = FakeLLM(ReminderProposal(text="call mom", fire_at=fire, confirmation="Call mom — tomorrow"))
    p = parse_reminder("remind me to call mom tomorrow", llm, tz="Asia/Kolkata")
    assert p.text == "call mom"
    assert "<reminder_request>" in llm.prompt  # injected as data, not instructions


def test_parse_reminder_rejects_past():
    fire = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    llm = FakeLLM(ReminderProposal(text="x", fire_at=fire, confirmation="x"))
    with pytest.raises(ValueError, match="future"):
        parse_reminder("remind me yesterday", llm, tz="Asia/Kolkata")


def test_triage_cron_and_scheduler_honor_configured_timezone(tmp_path, monkeypatch):
    # The triage cron must fire on settings.timezone, not host-local/UTC.
    from app.config import get_settings
    from app.scheduler import jobs

    s = get_settings()
    monkeypatch.setattr(s, "data_dir", str(tmp_path))
    try:
        sched = jobs.create_scheduler()
        assert str(sched.timezone) == s.timezone
    finally:
        jobs._scheduler = None  # don't leak the global into other tests
