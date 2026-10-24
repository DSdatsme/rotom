"""Weekly retro: triage/draft/reminder/workflow-run stats for the past 7 days → Telegram."""

import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import inngest

from app.config import get_settings
from app.tools.retro.service import compile_weekly_retro
from app.workflows.client import inngest_client
from app.workflows.lib import deliver, inngest_run

_settings = get_settings()


def retro_window_start(now: datetime, tz_name: str) -> datetime:
    """Start of the 7-day window, in UTC. Seven days back in the owner's wall-clock time,
    floored to the minute, so last week's cron run (same minute, sub-second jitter
    either way) is always inside the window rather than in or out by chance."""
    local = now.astimezone(ZoneInfo(tz_name)) - timedelta(days=7)
    return local.replace(second=0, microsecond=0).astimezone(timezone.utc)


async def send_weekly_retro(run_key: str | None, *, now: datetime | None = None) -> str:
    """Compile the retro and send it, as one recorded run (the sync DB queries run off the
    event loop). Compiling is cheap, so delivery lives in the same step: a failed send
    raises and Inngest retries the whole step."""
    settings = get_settings()
    since = retro_window_start(now or datetime.now(timezone.utc), settings.timezone)

    with inngest_run("weekly_retro", run_key) as run:
        text = await asyncio.to_thread(compile_weekly_retro, since)
        if await deliver(text):
            run.summary = "weekly retro sent"
            return "sent"
        run.degrade(summary="weekly retro compiled · not sent (telegram off)")
        return "skipped: telegram off"


@inngest_client.create_function(
    fn_id="weekly-retro",
    trigger=[
        inngest.TriggerEvent(event="workflows/weekly-retro.requested"),
        inngest.TriggerCron(cron=f"TZ={_settings.timezone} 0 18 * * 0"),
    ],
    retries=2,
)
async def weekly_retro(ctx: inngest.Context) -> str:
    return await ctx.step.run("retro", send_weekly_retro, ctx.run_id)
