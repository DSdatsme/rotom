"""Reminder lifecycle: create / list / cancel + next-fire computation.

Shared by the agent tools, the API routes, and the dashboard. Scheduling itself
lives in app.scheduler.jobs; this module owns the DB rows and delegates jobs.
"""

import logging
from datetime import datetime

from apscheduler.triggers.cron import CronTrigger

from app.config import get_settings
from app.store.db import Reminder, ReminderStatus, as_utc, get_session, utcnow

logger = logging.getLogger(__name__)

MAX_ACTIVE_REMINDERS = 100


def _get_live_scheduler():
    from app.scheduler.jobs import get_scheduler

    scheduler = get_scheduler()
    if scheduler is None:
        raise RuntimeError("Scheduler is not running; cannot manage reminder jobs")
    return scheduler


def create_reminder(text: str, fire_at: datetime, recurrence_cron: str = "") -> Reminder:
    """Store a reminder and register its scheduler job. fire_at must be aware UTC."""
    from app.scheduler.jobs import schedule_reminder_job

    from app.tools.reminders.recurrence import normalize_recurrence

    text = text.strip()
    if not text:
        raise ValueError("Reminder text is empty")
    fire_at = as_utc(fire_at)
    if not recurrence_cron and fire_at <= utcnow():
        raise ValueError(f"Reminder time {fire_at.isoformat()} is in the past")
    # Shorthands ("everyday", "every monday") become cron anchored to fire_at's time;
    # raw cron is validated. Raises ValueError with a helpful message otherwise.
    recurrence_cron = normalize_recurrence(recurrence_cron, fire_at, get_settings().timezone)

    scheduler = _get_live_scheduler()
    with get_session() as s:
        active = s.query(Reminder).filter(Reminder.status == ReminderStatus.PENDING).count()
        if active >= MAX_ACTIVE_REMINDERS:
            raise ValueError(f"Too many active reminders ({active}); cancel some first")
        r = Reminder(text=text, fire_at=fire_at, recurrence_cron=recurrence_cron)
        s.add(r)
        s.flush()
        schedule_reminder_job(scheduler, r)
        return r


def cancel_reminder(reminder_id: int) -> bool:
    """Cancel a pending reminder and remove its job. Returns False if not found/pending."""
    from app.scheduler.jobs import unschedule_reminder_job

    scheduler = _get_live_scheduler()
    with get_session() as s:
        r = s.get(Reminder, reminder_id)
        if r is None or r.status != ReminderStatus.PENDING:
            return False
        r.status = ReminderStatus.CANCELLED
    unschedule_reminder_job(scheduler, reminder_id)
    return True


def list_reminders(status: str = ReminderStatus.PENDING, limit: int = 100) -> list[Reminder]:
    with get_session() as s:
        q = s.query(Reminder).order_by(Reminder.fire_at.asc())
        if status:
            q = q.filter(Reminder.status == status)
        return q.limit(limit).all()


def next_fire_at(reminder: Reminder) -> datetime | None:
    """Next occurrence in UTC: fire_at for one-time, computed from cron for recurring."""
    if reminder.status != ReminderStatus.PENDING:
        return None
    if not reminder.recurrence_cron:
        return as_utc(reminder.fire_at)
    trigger = CronTrigger.from_crontab(reminder.recurrence_cron, timezone=get_settings().timezone)
    nxt = trigger.get_next_fire_time(None, utcnow())
    return as_utc(nxt.replace(tzinfo=nxt.tzinfo)) if nxt else None


def reminder_json(r: Reminder) -> dict:
    nxt = next_fire_at(r)
    return {
        "id": r.id,
        "text": r.text,
        "fire_at": as_utc(r.fire_at).isoformat() if r.fire_at else None,
        "next_fire_at": nxt.isoformat() if nxt else None,
        "recurrence_cron": r.recurrence_cron,
        "status": r.status,
        "created_at": as_utc(r.created_at).isoformat() if r.created_at else None,
        "fired_at": as_utc(r.fired_at).isoformat() if r.fired_at else None,
    }
