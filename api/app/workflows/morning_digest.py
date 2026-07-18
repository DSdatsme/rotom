"""Morning digest: fetch top HN stories → LLM summary → Telegram. One LLM call/run."""

import inngest

from app.workflows.client import inngest_client
from app.workflows.lib import llm, notify, run_script


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
        return await llm(
            "chat",
            "Summarize these Hacker News stories in <=8 short bullet lines for a "
            f"busy engineer. Keep URLs for the 3 most interesting.\n\n{stories}",
        )

    summary = await ctx.step.run("summarize", summarize)

    async def send() -> str:
        await notify(f"🌅 Morning digest\n\n{summary}")
        return "sent"

    return await ctx.step.run("notify", send)
