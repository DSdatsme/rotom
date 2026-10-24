"""Morning digest: fetch top HN stories → LLM summary → Telegram. One LLM call/run."""

import inngest

from app.config import get_settings
from app.workflows.client import inngest_client
from app.workflows.lib import inngest_run, llm, notify_step, record_failure, run_script

_settings = get_settings()


@inngest_client.create_function(
    fn_id="morning-digest",
    trigger=[
        inngest.TriggerEvent(event="workflows/morning-digest.requested"),
        inngest.TriggerCron(cron=f"TZ={_settings.timezone} 30 8 * * *"),
    ],
    retries=2,
    on_failure=record_failure("morning_digest"),
)
async def morning_digest(ctx: inngest.Context) -> str:
    if not get_settings().telegram_enabled:
        # Nobody would see the summary: record the skipped run, spend no LLM call.
        async def record_skipped() -> str:
            with inngest_run("morning_digest", ctx.run_id) as run:
                run.degrade(summary="skipped: telegram off")
            return "skipped: telegram off"

        return await ctx.step.run("skip", record_skipped)

    async def fetch() -> str:
        return await run_script("top_hn.py")

    stories = await ctx.step.run("fetch-hn", fetch)
    if not stories.strip():
        async def record_empty() -> str:
            with inngest_run("morning_digest", ctx.run_id) as run:
                run.degrade(summary="nothing fetched from Hacker News")
            return "nothing fetched"

        return await ctx.step.run("record-empty", record_empty)

    async def summarize() -> str:
        with inngest_run("morning_digest", ctx.run_id) as run:
            text = await llm(
                "chat",
                "Summarize these Hacker News stories in <=8 short bullet lines for a "
                f"busy engineer. Keep URLs for the 3 most interesting.\n\n{stories}",
            )
            run.summary = "summarized"
            return text

    summary = await ctx.step.run("summarize", summarize)

    return await notify_step(ctx, "morning_digest", f"🌅 Morning digest\n\n{summary}")
