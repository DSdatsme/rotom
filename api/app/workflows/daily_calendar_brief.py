"""Daily calendar brief: today's merged agenda across all accounts → Telegram."""

import inngest

from app.config import get_settings
from app.workflows.client import inngest_client
from app.workflows.lib import notify

_settings = get_settings()


@inngest_client.create_function(
    fn_id="daily-calendar-brief",
    trigger=[
        inngest.TriggerEvent(event="workflows/daily-calendar-brief.requested"),
        inngest.TriggerCron(cron=f"TZ={_settings.timezone} 30 8 * * *"),
    ],
    retries=2,
)
async def daily_calendar_brief(ctx: inngest.Context) -> str:
    async def fetch_and_format() -> str:
        import asyncio
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        from app.config import get_settings
        from app.observability.sink import record_run
        from app.tools.calendar.client import load_accounts
        from app.tools.calendar.service import format_daily_brief, list_events_for_range

        settings = get_settings()
        zone = ZoneInfo(settings.timezone)
        today = datetime.now(zone).date()
        time_min = datetime.combine(today, datetime.min.time(), tzinfo=zone)
        time_max = datetime.combine(today + timedelta(days=1), datetime.min.time(), tzinfo=zone)

        with record_run("daily_calendar_brief", source="inngest") as run:
            accounts = load_accounts(settings)
            events, errors = await asyncio.to_thread(
                list_events_for_range, accounts, time_min, time_max, settings.timezone
            )
            text = format_daily_brief(events, errors, today)
            if errors:
                run.degrade(summary=f"{len(events)} events, {len(errors)} accounts failed")
            else:
                run.summary = f"{len(events)} events"
            return text

    text = await ctx.step.run("fetch-and-format", fetch_and_format)

    async def send() -> str:
        await notify(text)
        return "sent"

    return await ctx.step.run("notify", send)
