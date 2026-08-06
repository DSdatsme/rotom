"""Weekly retro: triage/draft/reminder/workflow-run stats for the past 7 days → Telegram."""

import inngest

from app.workflows.client import inngest_client
from app.workflows.lib import notify


@inngest_client.create_function(
    fn_id="weekly-retro",
    trigger=[
        inngest.TriggerEvent(event="workflows/weekly-retro.requested"),
        inngest.TriggerCron(cron="0 18 * * 0"),
    ],
    retries=2,
)
async def weekly_retro(ctx: inngest.Context) -> str:
    async def gather_and_format() -> str:
        from datetime import datetime, timedelta, timezone

        from app.observability.sink import record_run
        from app.tools.retro.service import (
            draft_activity, format_weekly_retro, reminder_stats, triage_stats, workflow_run_stats,
        )

        since = datetime.now(timezone.utc) - timedelta(days=7)

        with record_run("weekly_retro", source="inngest") as run:
            triage = triage_stats(since)
            drafts = draft_activity(since)
            reminders = reminder_stats(since)
            workflows = workflow_run_stats(since)
            run.summary = "weekly retro compiled"
            return format_weekly_retro(triage, drafts, reminders, workflows)

    text = await ctx.step.run("gather-and-format", gather_and_format)

    async def send() -> str:
        await notify(text)
        return "sent"

    return await ctx.step.run("notify", send)
