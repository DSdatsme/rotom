"""APScheduler setup: persistent job store, the recurring triage job, and reminder jobs.

Job functions are module-level (args limited to picklable scalars) so they survive
round-trips through SQLAlchemyJobStore.
"""

import asyncio
import logging

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import get_settings

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler | None:
    """The process-wide scheduler (None if not started, e.g. in tests)."""
    return _scheduler


async def scheduled_gmail_triage_job(source: str = "scheduler") -> None:
    """Run a triage pass and push the digest to the owner's Telegram chat.

    `source` distinguishes the cron path ("scheduler", the default) from the
    dashboard "run now" path ("manual"), which passes it via APScheduler kwargs.
    """
    from app.channels.telegram import notify_owner
    from app.tools.gmail.service import run_triage_now
    from app.observability.sink import record_run

    settings = get_settings()
    try:
        with record_run("gmail_triage", source=source) as run:
            # run_triage_now is sync (Gmail + LLM SDK calls); keep the event loop free.
            result, digest = await asyncio.to_thread(run_triage_now)
            logger.info("Scheduled gmail triage: %d fetched, %d new, %d drafts",
                        result.fetched, len(result.new_emails), result.drafts_created)

            summary = f"{result.fetched} fetched · {len(result.new_emails)} new · {result.drafts_created} drafts"

            # Delivering the digest is part of the job, so a skipped/failed send
            # is a *degraded* run (warning), not a clean success and not a hard
            # failure — the triage results are already persisted either way.
            notes: list[str] = []
            err = ""
            if result.errors:
                notes.append(f"{len(result.errors)} errors")

            # Skip the "nothing new" ping only if there were also no errors.
            if result.new_emails or result.errors:
                if not settings.telegram_enabled:
                    logger.info("TELEGRAM_ENABLED=false — skipping triage digest send")
                    notes.append("digest not sent (telegram off)")
                else:
                    try:
                        from app.channels.telegram import notify_owner

                        await notify_owner(digest)
                    except Exception as exc:  # noqa: BLE001 — delivery failure ≠ run failure
                        logger.exception("Triage digest delivery failed")
                        notes.append("digest delivery failed")
                        err = str(exc)

            if notes:
                run.degrade(summary=f"{summary} · {' · '.join(notes)}", error=err)
            else:
                run.summary = summary
    except Exception:
        logger.exception("Scheduled gmail triage failed")
        if settings.telegram_enabled:
            try:
                await notify_owner("⚠ Scheduled email triage failed — check logs.")
            except Exception:
                logger.exception("Could not report triage failure to Telegram")


async def fire_reminder_job(reminder_id: int) -> None:
    """Send a due reminder to the owner's Telegram chat and update its status."""
    from app.channels.telegram import notify_owner

    from app.store.db import Reminder, ReminderStatus, get_session, utcnow
    from app.observability.sink import record_run

    settings = get_settings()
    with get_session() as s:
        r = s.get(Reminder, reminder_id)
        if r is None or r.status != ReminderStatus.PENDING:
            logger.info("Reminder %s gone or not pending; skipping fire", reminder_id)
            return  # nothing fired → no audit row
        text, recurring = r.text, bool(r.recurrence_cron)

    # A cheap "fired & delivered at T" audit run (no LLM).
    with record_run("reminder_fire", source="scheduler") as run:
        if not settings.telegram_enabled:
            logger.warning("TELEGRAM_ENABLED=false — cannot deliver reminder %s", reminder_id)
            run.fail(summary=f"telegram disabled; reminder #{reminder_id} not delivered")
            return
        try:
            await notify_owner(f"⏰ Reminder: {text}")
        except Exception as exc:
            logger.exception("Failed to deliver reminder %s; will not mark fired", reminder_id)
            # one-time job already consumed by APScheduler is acceptable loss; cron retries next cycle
            run.fail(summary=f"delivery failed for reminder #{reminder_id}", error=str(exc))
            return

        with get_session() as s:
            r = s.get(Reminder, reminder_id)
            if r is None:
                run.summary = f"reminder #{reminder_id} vanished after delivery"
                return
            r.fired_at = utcnow()
            if not recurring:
                r.status = ReminderStatus.FIRED
        run.summary = f"delivered reminder #{reminder_id}"


def reap_interrupted_runs_job() -> None:
    """Flip zombie `running` RunLog rows (process died mid-run) to `interrupted`.

    Runs every few minutes and once at startup. Inngest runs are excluded (they
    resume on their own). Observability maintenance must never raise.
    """
    try:
        from app.observability.sqlite_sink import SqliteSink

        reaped = SqliteSink().reap_stale_runs()
        if reaped:
            logger.info("Stale-run reaper: marked %d run(s) interrupted", reaped)
    except Exception:
        logger.exception("Stale-run reaper failed")


def schedule_reminder_job(scheduler: AsyncIOScheduler, reminder) -> None:
    """Register (or re-register) the APScheduler job for a Reminder row."""
    from app.store.db import as_utc

    settings = get_settings()
    if reminder.recurrence_cron:
        trigger = CronTrigger.from_crontab(reminder.recurrence_cron, timezone=settings.timezone)
    else:
        trigger = DateTrigger(run_date=as_utc(reminder.fire_at))
    scheduler.add_job(
        fire_reminder_job,
        trigger,
        args=[reminder.id],
        id=f"reminder-{reminder.id}",
        replace_existing=True,
        misfire_grace_time=3600,  # fire up to an hour late if the process was down
    )


def unschedule_reminder_job(scheduler: AsyncIOScheduler, reminder_id: int) -> None:
    job = scheduler.get_job(f"reminder-{reminder_id}")
    if job is not None:
        job.remove()


def reschedule_pending_reminders(scheduler: AsyncIOScheduler) -> None:
    """Boot reconciliation: ensure every pending reminder has a job (covers jobstore wipe).

    One-time reminders whose fire time passed while we were down (and whose job is
    gone) are fired immediately rather than lost.
    """
    from app.store.db import Reminder, ReminderStatus, as_utc, get_session, utcnow

    now = utcnow()
    with get_session() as s:
        pending = s.query(Reminder).filter(Reminder.status == ReminderStatus.PENDING).all()
    for r in pending:
        if scheduler.get_job(f"reminder-{r.id}") is not None:
            continue  # jobstore already has it (misfire grace handles late fires)
        if not r.recurrence_cron and as_utc(r.fire_at) <= now:
            logger.warning("Reminder %s missed while down; firing now", r.id)
            scheduler.add_job(fire_reminder_job, DateTrigger(run_date=now), args=[r.id],
                              id=f"reminder-{r.id}", replace_existing=True, misfire_grace_time=3600)
        else:
            logger.info("Re-registering missing job for reminder %s", r.id)
            schedule_reminder_job(scheduler, r)


def create_scheduler() -> AsyncIOScheduler:
    global _scheduler
    settings = get_settings()
    scheduler = AsyncIOScheduler(
        jobstores={"default": SQLAlchemyJobStore(url=f"sqlite:///{settings.data_dir}/scheduler.db")},
        timezone=settings.timezone,  # else triggers default to host-local/UTC, not the configured zone
    )
    scheduler.add_job(
        scheduled_gmail_triage_job,
        CronTrigger.from_crontab(settings.gmail_triage_cron, timezone=settings.timezone),
        id="gmail-triage-cron",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    # Stale-run reaper: sweep every 5 min, and once right at startup to clean up
    # zombies left by the previous (possibly crashed) process.
    from app.store.db import utcnow

    scheduler.add_job(
        reap_interrupted_runs_job,
        IntervalTrigger(minutes=5),
        id="run-reaper",
        replace_existing=True,
        next_run_time=utcnow(),
    )
    _scheduler = scheduler
    return scheduler
