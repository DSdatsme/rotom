"""Morning digest: fetch top HN stories → LLM summary → Telegram. One LLM call/run."""

import inngest

from app.workflows.client import inngest_client
from app.workflows.lib import llm, notify_step, run_script


@inngest_client.create_function(
    fn_id="morning-digest",
    trigger=[
        inngest.TriggerEvent(event="workflows/morning-digest.requested"),
        inngest.TriggerCron(cron="30 8 * * *"),
    ],
    retries=2,
)
async def morning_digest(ctx: inngest.Context) -> str:
    async def fetch() -> str:
        return await run_script("top_hn.py")

    stories = await ctx.step.run("fetch-hn", fetch)
    if not stories.strip():
        return "nothing fetched"

    async def summarize() -> str:
        from app.observability.sink import record_run

        with record_run("morning_digest", source="inngest") as run:
            text = await llm(
                "chat",
                "Summarize these Hacker News stories in <=8 short bullet lines for a "
                f"busy engineer. Keep URLs for the 3 most interesting.\n\n{stories}",
            )
            run.summary = "summarized"
            return text

    summary = await ctx.step.run("summarize", summarize)

    return await notify_step(ctx, f"🌅 Morning digest\n\n{summary}")
