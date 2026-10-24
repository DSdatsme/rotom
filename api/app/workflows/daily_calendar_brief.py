"""Daily calendar brief: today's merged agenda across all accounts → Telegram."""

import asyncio
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import inngest

from app.config import get_settings
from app.observability.tracing import span
from app.tools.calendar.client import load_accounts
from app.tools.calendar.service import format_daily_brief, list_events_for_range
from app.workflows.client import inngest_client
from app.workflows.lib import deliver, inngest_run

_settings = get_settings()


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


async def send_daily_brief(run_key: str | None, *, now: datetime | None = None) -> str:
    """Fetch today's events, format the brief and send it, as one recorded run.

    Fetching is cheap, so delivery lives in the same step: a failed send raises, the run
    records the failure, and Inngest retries the whole step. No calendar data at all (no
    accounts, or every account failing) is a failed run even though a warning is still
    sent; some accounts failing is degraded, as is Telegram being off."""
    settings = get_settings()
    zone = ZoneInfo(settings.timezone)
    today = (now or datetime.now(zone)).astimezone(zone).date()
    time_min = datetime.combine(today, time.min, tzinfo=zone)
    time_max = datetime.combine(today + timedelta(days=1), time.min, tzinfo=zone)

    with inngest_run("daily_calendar_brief", run_key) as run:
        accounts = load_accounts(settings)
        with span("calendar.fetch"):
            events, errors = await asyncio.to_thread(
                list_events_for_range, accounts, time_min, time_max, settings.timezone
            )
        text = format_daily_brief(events, errors, today, tz=zone, accounts_checked=len(accounts))
        sent = await deliver(text)

        error = "; ".join(f"{e['account']}: {e['message']}" for e in errors)
        notes = [_plural(len(errors), "account") + " failed"] if errors else []
        if not sent:
            notes.append("not sent (telegram off)")
        summary = " · ".join([_plural(len(events), "event"), *notes])
        if not accounts:
            run.fail(summary="no calendar accounts connected")
        elif errors and len(errors) == len(accounts):
            run.fail(summary=summary, error=error)
        elif notes:
            run.degrade(summary=summary, error=error)
        else:
            run.summary = summary
        return "sent" if sent else "skipped: telegram off"


@inngest_client.create_function(
    fn_id="daily-calendar-brief",
    trigger=[
        inngest.TriggerEvent(event="workflows/daily-calendar-brief.requested"),
        inngest.TriggerCron(cron=f"TZ={_settings.timezone} 30 8 * * *"),
    ],
    retries=2,
)
async def daily_calendar_brief(ctx: inngest.Context) -> str:
    return await ctx.step.run("brief", send_daily_brief, ctx.run_id)
