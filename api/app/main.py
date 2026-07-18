"""rotom api entrypoint: FastAPI + Telegram bot + scheduler in one asyncio process.

    uv run python -m app.main
"""

import asyncio
import logging

import inngest.fast_api
import uvicorn

from app.api.routes import create_app
from app.config import get_settings, validate_required_settings
from app.scheduler.jobs import create_scheduler, reschedule_pending_reminders
from app.store.db import init_db
from app.channels.telegram import create_bot_app
from app.workflows.client import inngest_client
from app.workflows.registry import WORKFLOW_FUNCTIONS
from app.logging_setup import setup_logging
from app.store.observability import create_all as init_obs_db

setup_logging()
logger = logging.getLogger("rotom")


async def main() -> None:
    settings = get_settings()
    validate_required_settings(settings)  # fail fast on blank/placeholder API_TOKEN
    init_db(settings.db_path)
    init_obs_db()

    # FastAPI
    api = create_app(api_token=settings.api_token)
    inngest.fast_api.serve(api, inngest_client, WORKFLOW_FUNCTIONS)
    server = uvicorn.Server(uvicorn.Config(api, host=settings.api_host, port=settings.api_port, log_level="info", log_config=None))

    # Scheduler
    scheduler = create_scheduler()
    scheduler.start()
    reschedule_pending_reminders(scheduler)  # re-attach jobs for reminders that lost theirs

    # Telegram bot (long polling) — skippable via TELEGRAM_ENABLED so a blocked/
    # unreachable Telegram (e.g. ISP-level block) can't take down the API + scheduler.
    bot_app = None
    if settings.telegram_enabled:
        bot_app = create_bot_app()
        await bot_app.initialize()
        await bot_app.start()
        await bot_app.updater.start_polling()
    else:
        logger.warning("TELEGRAM_ENABLED=false — Telegram bot disabled; API + scheduler only")
    logger.info("rotom online: api on :%d, telegram=%s, triage cron %r",
                settings.api_port, "polling" if bot_app else "OFF", settings.gmail_triage_cron)

    try:
        await server.serve()  # blocks until SIGINT/SIGTERM
    finally:
        logger.info("shutting down")
        if bot_app is not None:
            await bot_app.updater.stop()
            await bot_app.stop()
            await bot_app.shutdown()
        scheduler.shutdown(wait=False)
        from app.agent.graph import close_agent

        await close_agent()


if __name__ == "__main__":
    asyncio.run(main())
