"""Workflow step helpers. Workflows call these, never raw SDKs — future guardrails
(LLM budgets, allow-lists, log scrubbing) land here without touching workflow files."""

import asyncio
import sys
from pathlib import Path

from app.config import get_settings
from app.llm.provider import extract_text, get_chat_model

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
