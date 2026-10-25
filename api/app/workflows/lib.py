"""Workflow step helpers. Workflows call these, never raw SDKs — future guardrails
(LLM budgets, allow-lists, log scrubbing) land here without touching workflow files."""

import asyncio
import logging
import sys
from pathlib import Path

import inngest

from app.config import get_settings
from app.llm.provider import extract_text, get_chat_model
from app.observability.sink import record_run
from app.observability.tracing import span

logger = logging.getLogger(__name__)

SCRIPTS_DIR = Path(__file__).parent / "scripts"


async def llm(role: str, prompt: str) -> str:
    """One LLM call (sync SDK moved off the event loop)."""
    model = get_chat_model(role, get_settings())
    msg = await asyncio.to_thread(model.invoke, prompt)
    return extract_text(msg.content)


async def run_script(name: str, *args: str, timeout: int = 120) -> str:
    """Run a script from workflows/scripts/ and return stdout. .py files run
    under the current interpreter; anything else must be executable."""
    path = (SCRIPTS_DIR / name).resolve()
    if not path.is_relative_to(SCRIPTS_DIR.resolve()):
        raise ValueError(f"Script {name!r} escapes the scripts directory")
    if not path.exists():
        raise FileNotFoundError(f"No script {name!r} in workflows/scripts/")
    cmd = [sys.executable, str(path), *args] if path.suffix == ".py" else [str(path), *args]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError(f"Script {name!r} timed out after {timeout}s")
    if proc.returncode != 0:
        raise RuntimeError(f"Script {name!r} failed ({proc.returncode}): {err.decode('utf-8', errors='replace')[:500]}")
    return out.decode("utf-8", errors="replace")


async def notify(text: str) -> None:
    """Send a (chunked) Telegram message to the owner."""
    from app.channels.telegram import notify_owner

    await notify_owner(text)


def inngest_run(kind: str, run_key: str | None):
    """`record_run` for a workflow step. The Inngest run id is stored as the run's
    external_id: each retried attempt opens its own RunLog row, and the shared id is what
    lets the weekly retro count one run per Inngest run (latest attempt wins)."""
    return record_run(kind, source="inngest", external_id=run_key)


async def deliver(text: str) -> bool:
    """Send a digest to the owner. Returns False, sending nothing, when TELEGRAM_ENABLED=false
    (the caller marks its run degraded). A failed send is logged and re-raised, so the step
    is retried and the enclosing run records the failure."""
    if not get_settings().telegram_enabled:
        logger.info("TELEGRAM_ENABLED=false — digest not sent")
        return False
    with span("telegram.notify"):
        try:
            await notify(text)
        except Exception:
            logger.exception("Digest delivery to Telegram failed")
            raise
    return True


async def notify_step(ctx: inngest.Context, kind: str, text: str) -> str:
    """Final 'notify' step for a workflow that recorded its run in an earlier step, so a
    failed send doesn't redo that work (e.g. an LLM call). Telegram off is recorded as a
    degraded `kind` run under the same Inngest run id; a failed send raises, and once
    retries are exhausted `record_failure` records it."""
    async def send() -> str:
        if await deliver(text):
            return "sent"
        with inngest_run(kind, ctx.run_id) as run:
            run.degrade(summary="digest not sent (telegram off)")
        return "skipped: telegram off"

    return await ctx.step.run("notify", send)


def record_failure(kind: str):
    """An `on_failure` handler: when Inngest gives up on a run, record it as a failed `kind`
    run under the failed run's id, so failures outside a recorded step (a fetch, a send)
    still reach the Runs page and the weekly retro."""
    async def on_failure(ctx: inngest.Context) -> None:
        # ctx.event is Inngest's "inngest/function.failed" system event; per its docs the
        # data carries function_id, run_id (the failed run), error {name, message, stack}
        # and the original event. Read defensively: the SDK itself doesn't type it.
        data = ctx.event.data or {}
        err = data.get("error")
        message = err.get("message") if isinstance(err, dict) else err
        with inngest_run(kind, data.get("run_id")) as run:
            logger.error("Workflow %s failed after retries: %s", kind, message)
            run.fail(summary="failed after retries", error=str(message or "workflow failed"))

    return on_failure
