"""Weekly retro: triage/draft/reminder/workflow-run stats for the past 7 days → Telegram."""

from datetime import datetime, timedelta, timezone

import inngest

from app.config import get_settings
from app.observability.sink import record_run
from app.tools.retro.service import (
    draft_activity, format_weekly_retro, reminder_stats, triage_stats, workflow_run_stats,
)
from app.workflows.client import inngest_client
from app.workflows.lib import notify_step

_settings = get_settings()


@inngest_client.create_function(
    fn_id="weekly-retro",
    trigger=[
        inngest.TriggerEvent(event="workflows/weekly-retro.requested"),
        inngest.TriggerCron(cron=f"TZ={_settings.timezone} 0 18 * * 0"),
    ],
    retries=2,
)
async def weekly_retro(ctx: inngest.Context) -> str:
    async def gather_and_format() -> str:
        since = datetime.now(timezone.utc) - timedelta(days=7)

        with record_run("weekly_retro", source="inngest") as run:
            triage = triage_stats(since)
            drafts = draft_activity(since)
            reminders = reminder_stats(since)
            workflows = workflow_run_stats(since)
            run.summary = "weekly retro compiled"
            return format_weekly_retro(triage, drafts, reminders, workflows)

    text = await ctx.step.run("gather-and-format", gather_and_format)

    return await notify_step(ctx, text)
