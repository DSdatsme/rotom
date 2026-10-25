"""Smoke-test workflow: proves cron + manual trigger + Telegram end-to-end."""

import datetime

import inngest

from app.config import get_settings
from app.workflows.client import inngest_client
from app.workflows.lib import notify

_settings = get_settings()


@inngest_client.create_function(
    fn_id="hello",
    trigger=[
        inngest.TriggerEvent(event="workflows/hello.requested"),
        inngest.TriggerCron(cron=f"TZ={_settings.timezone} 0 9 * * *"),
    ],
    retries=2,
)
async def hello(ctx: inngest.Context) -> str:
    async def ping() -> str:
        now = datetime.datetime.now().strftime("%H:%M")
        await notify(f"👋 hello workflow ran at {now}")
        return "sent"

    return await ctx.step.run("ping-telegram", ping)
