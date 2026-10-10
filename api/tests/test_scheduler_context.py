"""Scheduler jobs must never inherit the span that was current when a job was added.

AsyncIOScheduler.wakeup() uses call_soon_threadsafe, which captures the caller's
contextvars; the re-armed timer then carries that context into every later job run.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi.testclient import TestClient
from opentelemetry import trace

from tests.conftest import span_rows


class _ContextRecordingScheduler:
    """Records whether a valid span was current when add_job was called."""

    def __init__(self):
        self.span_valid_at_add: list[bool] = []

    def add_job(self, *args, **kwargs):
        self.span_valid_at_add.append(trace.get_current_span().get_span_context().is_valid)

    def get_job(self, job_id):
        return None


async def test_job_added_inside_a_span_does_not_leak_into_later_job_runs(traced):
    from app.observability.tracing import span
    from app.scheduler.jobs import schedule_reminder_job

    fired = asyncio.Event()

    async def probe():
        with span("probe.job"):
            pass
        fired.set()

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(probe, IntervalTrigger(seconds=1), id="probe")
    scheduler.start()
    try:
        await asyncio.sleep(0.05)  # let the startup wakeup arm the timer (clean context)
        reminder = SimpleNamespace(id=1, recurrence_cron="",
                                   fire_at=datetime.now(timezone.utc) + timedelta(hours=1))
        with span("POST /api/reminders"):
            schedule_reminder_job(scheduler, reminder)
        await asyncio.wait_for(fired.wait(), timeout=2.5)
    finally:
        scheduler.shutdown(wait=False)
        await asyncio.sleep(0)

    (caller,) = span_rows(name="POST /api/reminders")
    probe_row = span_rows(name="probe.job")[0]
    assert probe_row.parent_span_id is None
    assert probe_row.trace_id != caller.trace_id


def test_reschedule_pending_reminders_adds_jobs_detached(session_db, traced):
    from app.observability.tracing import span
    from app.scheduler.jobs import reschedule_pending_reminders
    from app.store.db import Reminder, get_session

    with get_session() as s:
        s.add(Reminder(text="past", fire_at=datetime.now(timezone.utc) - timedelta(minutes=5)))
        s.add(Reminder(text="future", fire_at=datetime.now(timezone.utc) + timedelta(hours=1)))
    sched = _ContextRecordingScheduler()
    with span("caller"):
        reschedule_pending_reminders(sched)
    assert sched.span_valid_at_add == [False, False]


def test_triage_trigger_route_adds_job_detached(session_db, traced, monkeypatch):
    from app.api.routes import create_app

    sched = _ContextRecordingScheduler()
    monkeypatch.setattr("app.scheduler.jobs.get_scheduler", lambda: sched)
    client = TestClient(create_app(api_token="test-token"))
    resp = client.post("/api/triage/trigger", headers={"Authorization": "Bearer test-token"})
    assert resp.status_code == 200
    assert span_rows(span_kind="SERVER")  # the request itself is traced…
    assert sched.span_valid_at_add == [False]  # …but the job is added outside its span
