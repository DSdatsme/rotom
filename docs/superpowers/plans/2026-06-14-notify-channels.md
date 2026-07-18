# Notify Channels (ntfy.sh) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a general-purpose `notify(text, channel, title)` seam backed by a pluggable `NotificationChannel` abstraction, with **ntfy.sh** as a second channel alongside Telegram, and refactor the scattered Telegram sends onto it.

**Architecture:** A `NotificationChannel` Protocol (`app/channels/base.py`) + two concrete channels (`TelegramChannel`, `NtfyChannel`) + a `notify()` dispatcher (`app/channels/notify.py`) that routes to `telegram` / `ntfy` / `both`. Existing inline `Bot(...)` sends in `workflows/lib.py` and `scheduler/jobs.py` are refactored to call `notify()` — behavior unchanged (still Telegram) unless a caller opts into ntfy.

**Tech Stack:** Python 3.12, `httpx>=0.28` (already a dep), `python-telegram-bot`, `pydantic-settings`, `pytest` + `pytest-asyncio` (`asyncio_mode = "auto"`, so `async def test_*` is awaited automatically).

**Spec:** `docs/superpowers/specs/2026-06-14-notify-channels-design.md`

**Working dir:** all paths are relative to `api/`. Run tests with `uv run pytest` from `api/`.

**Status:** Ready for execution (2026-06-14) — not yet implemented. Intended executor: Antigravity (or `superpowers:subagent-driven-development`). 6 tasks, each commits independently.

> ⚠️ **Security:** the target ntfy topic is free/unprotected (world-readable). Keep ntfy pushes terse + non-sensitive. The topic name lives only in gitignored `.env`.

---

## File structure

| File | Responsibility |
|------|----------------|
| `app/channels/base.py` (NEW) | `NotificationChannel` Protocol — the interface both channels satisfy |
| `app/channels/ntfy.py` (NEW) | `NtfyChannel` — async httpx POST to an ntfy topic |
| `app/channels/telegram.py` (MODIFY) | Add `TelegramChannel`; existing bot code untouched |
| `app/channels/notify.py` (NEW) | `notify()` dispatcher (telegram/ntfy/both) |
| `app/channels/__init__.py` (MODIFY) | Re-export `notify` |
| `app/config.py` (MODIFY) | `ntfy_base_url`, `ntfy_topic`, `ntfy_token` settings |
| `app/workflows/lib.py` (MODIFY) | `notify` delegates to the seam, gains `channel`/`title` |
| `app/scheduler/jobs.py` (MODIFY) | Route the 3 sends through `notify()` |
| `.env.example` (MODIFY, repo root) | ntfy config block |
| `tests/test_config_ntfy.py` (NEW) | settings defaults/override |
| `tests/test_ntfy_channel.py` (NEW) | `NtfyChannel` behavior |
| `tests/test_telegram_channel.py` (NEW) | `TelegramChannel` behavior |
| `tests/test_notify_dispatch.py` (NEW) | `notify()` routing/error semantics |
| `tests/test_workflow_lib.py` (MODIFY) | `lib.notify` delegation |
| `tests/test_reminders.py` (MODIFY) | `fire_reminder_job` regression |

---

## Task 1: ntfy settings

**Files:**
- Modify: `app/config.py` (after the `# --- Telegram ---` block, lines 80–82)
- Modify: `.env.example` (repo root)
- Test: `tests/test_config_ntfy.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_config_ntfy.py`:
```python
from app.config import Settings


def test_ntfy_settings_defaults(monkeypatch):
    for var in ("NTFY_BASE_URL", "NTFY_TOPIC", "NTFY_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    s = Settings(_env_file=None)  # ignore repo .env; test pure defaults
    assert s.ntfy_base_url == "https://ntfy.sh"
    assert s.ntfy_topic == ""
    assert s.ntfy_token == ""


def test_ntfy_settings_from_env(monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "alerts")
    monkeypatch.setenv("NTFY_TOKEN", "tok")
    s = Settings(_env_file=None)
    assert s.ntfy_topic == "alerts"
    assert s.ntfy_token == "tok"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config_ntfy.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'ntfy_base_url'`.

- [ ] **Step 3: Add the settings fields**

In `app/config.py`, immediately after the Telegram block:
```python
    # --- Telegram ---
    telegram_bot_token: str = ""
    telegram_chat_id: int = 0

    # --- ntfy push (optional; free topics are world-readable — keep pushes terse) ---
    ntfy_base_url: str = "https://ntfy.sh"
    ntfy_topic: str = ""      # empty → ntfy channel is inert (skipped)
    ntfy_token: str = ""      # optional; sent as "Authorization: Bearer" when set
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config_ntfy.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Update `.env.example`**

Add to the repo-root `.env.example`:
```
# --- ntfy push notifications (optional) ---
# NTFY_BASE_URL=https://ntfy.sh
# NTFY_TOPIC=your-secret-topic-name
# NTFY_TOKEN=            # leave empty for unprotected topics
```

- [ ] **Step 6: Commit**

```bash
git add api/app/config.py api/tests/test_config_ntfy.py .env.example
git commit -m "feat(notify): add ntfy settings (base url, topic, token)"
```

---

## Task 2: `NotificationChannel` Protocol

**Files:**
- Create: `app/channels/base.py`

> Pure interface (typing `Protocol`) — no runtime behavior, so no test. It is exercised by the channel implementations in Tasks 3–4.

- [ ] **Step 1: Create the Protocol**

Create `app/channels/base.py`:
```python
"""The NotificationChannel interface. Implementations live in this package."""

from typing import Protocol


class NotificationChannel(Protocol):
    name: str  # "telegram" | "ntfy"

    @property
    def configured(self) -> bool:
        """True when this channel has the settings it needs to send."""
        ...

    async def send(self, text: str, *, title: str | None = None) -> None:
        """Deliver a message. MUST raise on delivery failure."""
        ...
```

- [ ] **Step 2: Verify it imports**

Run: `uv run python -c "from app.channels.base import NotificationChannel; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add api/app/channels/base.py
git commit -m "feat(notify): add NotificationChannel protocol"
```

---

## Task 3: `NtfyChannel`

**Files:**
- Create: `app/channels/ntfy.py`
- Test: `tests/test_ntfy_channel.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ntfy_channel.py`:
```python
import httpx
import pytest

from app.channels import ntfy


class FakeSettings:
    def __init__(self, base="https://ntfy.sh", topic="", token=""):
        self.ntfy_base_url = base
        self.ntfy_topic = topic
        self.ntfy_token = token


class FakeResponse:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


def fake_client_factory(captured, *, status_code=200, text="", raise_exc=None):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            captured["init_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, content=None, headers=None):
            captured["post"] = {"url": url, "content": content, "headers": headers or {}}
            if raise_exc is not None:
                raise raise_exc
            return FakeResponse(status_code, text)

    return FakeClient


def test_configured_reflects_topic(monkeypatch):
    monkeypatch.setattr(ntfy, "get_settings", lambda: FakeSettings(topic=""))
    assert ntfy.NtfyChannel().configured is False
    monkeypatch.setattr(ntfy, "get_settings", lambda: FakeSettings(topic="alerts"))
    assert ntfy.NtfyChannel().configured is True


async def test_send_builds_request_without_token(monkeypatch):
    captured = {}
    monkeypatch.setattr(ntfy, "get_settings", lambda: FakeSettings(topic="alerts"))
    monkeypatch.setattr(ntfy.httpx, "AsyncClient", fake_client_factory(captured))
    await ntfy.NtfyChannel().send("hello", title="Hi")
    post = captured["post"]
    assert post["url"] == "https://ntfy.sh/alerts"
    assert post["content"] == b"hello"
    assert post["headers"]["Title"] == "Hi"
    assert "Authorization" not in post["headers"]
    assert "Priority" not in post["headers"]


async def test_send_includes_bearer_when_token_set(monkeypatch):
    captured = {}
    monkeypatch.setattr(ntfy, "get_settings", lambda: FakeSettings(topic="alerts", token="tok"))
    monkeypatch.setattr(ntfy.httpx, "AsyncClient", fake_client_factory(captured))
    await ntfy.NtfyChannel().send("hi")
    assert captured["post"]["headers"]["Authorization"] == "Bearer tok"
    assert "Title" not in captured["post"]["headers"]


async def test_non_2xx_raises_runtimeerror(monkeypatch):
    captured = {}
    monkeypatch.setattr(ntfy, "get_settings", lambda: FakeSettings(topic="alerts"))
    monkeypatch.setattr(
        ntfy.httpx, "AsyncClient",
        fake_client_factory(captured, status_code=403, text="forbidden"),
    )
    with pytest.raises(RuntimeError, match="403"):
        await ntfy.NtfyChannel().send("hi")


async def test_httpx_error_raises_and_hides_token(monkeypatch):
    captured = {}
    monkeypatch.setattr(ntfy, "get_settings", lambda: FakeSettings(topic="alerts", token="secret"))
    monkeypatch.setattr(
        ntfy.httpx, "AsyncClient",
        fake_client_factory(captured, raise_exc=httpx.TimeoutException("slow")),
    )
    with pytest.raises(RuntimeError) as ei:
        await ntfy.NtfyChannel().send("hi")
    assert "secret" not in str(ei.value)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ntfy_channel.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.channels.ntfy'`.

- [ ] **Step 3: Implement `NtfyChannel`**

Create `app/channels/ntfy.py`:
```python
"""ntfy.sh push channel: a terse HTTP POST to a topic.

Free ntfy.sh topics are unprotected (world-readable) — keep messages non-sensitive.
"""

import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_TIMEOUT = 10.0


class NtfyChannel:
    name = "ntfy"

    @property
    def configured(self) -> bool:
        return bool(get_settings().ntfy_topic)

    async def send(self, text: str, *, title: str | None = None) -> None:
        s = get_settings()
        url = f"{s.ntfy_base_url.rstrip('/')}/{s.ntfy_topic}"
        headers: dict[str, str] = {}
        if title:
            headers["Title"] = title
        if s.ntfy_token:
            headers["Authorization"] = f"Bearer {s.ntfy_token}"
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(url, content=text.encode("utf-8"), headers=headers)
        except httpx.HTTPError as exc:
            # Never include headers/token in the message.
            raise RuntimeError(f"ntfy POST error: {type(exc).__name__}") from exc
        if resp.status_code >= 300:
            raise RuntimeError(f"ntfy POST failed ({resp.status_code}): {resp.text[:200]}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ntfy_channel.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add api/app/channels/ntfy.py api/tests/test_ntfy_channel.py
git commit -m "feat(notify): add NtfyChannel (httpx POST, raises on failure)"
```

---

## Task 4: `TelegramChannel`

**Files:**
- Modify: `app/channels/telegram.py` (line 9 import; add class at end — leave bot handlers untouched)
- Test: `tests/test_telegram_channel.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_telegram_channel.py`:
```python
from app.channels import telegram as tg


class FakeSettings:
    def __init__(self, token="t", chat_id=42):
        self.telegram_bot_token = token
        self.telegram_chat_id = chat_id


def test_configured_requires_token_and_chat(monkeypatch):
    monkeypatch.setattr(tg, "get_settings", lambda: FakeSettings(token="", chat_id=0))
    assert tg.TelegramChannel().configured is False
    monkeypatch.setattr(tg, "get_settings", lambda: FakeSettings(token="t", chat_id=42))
    assert tg.TelegramChannel().configured is True


async def test_send_prepends_title_and_uses_send_chunked(monkeypatch):
    calls = {}

    class FakeBot:
        def __init__(self, token=None):
            calls["token"] = token

    async def fake_send_chunked(bot, chat_id, text):
        calls["chat_id"] = chat_id
        calls["text"] = text

    monkeypatch.setattr(tg, "Bot", FakeBot)
    monkeypatch.setattr(tg, "send_chunked", fake_send_chunked)
    monkeypatch.setattr(tg, "get_settings", lambda: FakeSettings(token="t", chat_id=42))

    await tg.TelegramChannel().send("hello", title="Hi")
    assert calls["text"] == "Hi\nhello"
    assert calls["chat_id"] == 42
    assert calls["token"] == "t"


async def test_send_without_title(monkeypatch):
    calls = {}

    class FakeBot:
        def __init__(self, token=None):
            pass

    async def fake_send_chunked(bot, chat_id, text):
        calls["text"] = text

    monkeypatch.setattr(tg, "Bot", FakeBot)
    monkeypatch.setattr(tg, "send_chunked", fake_send_chunked)
    monkeypatch.setattr(tg, "get_settings", lambda: FakeSettings())

    await tg.TelegramChannel().send("plain")
    assert calls["text"] == "plain"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_telegram_channel.py -v`
Expected: FAIL — `AttributeError: module 'app.channels.telegram' has no attribute 'TelegramChannel'`.

- [ ] **Step 3: Add `Bot` to the import and the `TelegramChannel` class**

In `app/channels/telegram.py`, change line 9 from:
```python
from telegram import Update
```
to:
```python
from telegram import Bot, Update
```

Then append at the end of the file (after `create_bot_app`):
```python
class TelegramChannel:
    name = "telegram"

    @property
    def configured(self) -> bool:
        s = get_settings()
        return bool(s.telegram_bot_token and s.telegram_chat_id)

    async def send(self, text: str, *, title: str | None = None) -> None:
        s = get_settings()
        message = f"{title}\n{text}" if title else text
        bot = Bot(token=s.telegram_bot_token)
        await send_chunked(bot, s.telegram_chat_id, message)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_telegram_channel.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add api/app/channels/telegram.py api/tests/test_telegram_channel.py
git commit -m "feat(notify): add TelegramChannel wrapping send_chunked"
```

---

## Task 5: `notify()` dispatcher

**Files:**
- Create: `app/channels/notify.py`
- Modify: `app/channels/__init__.py`
- Test: `tests/test_notify_dispatch.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_notify_dispatch.py`:
```python
import pytest

from app.channels import notify as notify_mod


class FakeChannel:
    def __init__(self, name, *, configured=True, fail=False):
        self.name = name
        self._configured = configured
        self._fail = fail
        self.sent = []

    @property
    def configured(self) -> bool:
        return self._configured

    async def send(self, text, *, title=None):
        if self._fail:
            raise RuntimeError("boom")
        self.sent.append((text, title))


def _wire(monkeypatch, tg, nt):
    monkeypatch.setattr(notify_mod, "TelegramChannel", lambda: tg)
    monkeypatch.setattr(notify_mod, "NtfyChannel", lambda: nt)


async def test_telegram_only(monkeypatch):
    tg, nt = FakeChannel("telegram"), FakeChannel("ntfy")
    _wire(monkeypatch, tg, nt)
    await notify_mod.notify("hi")
    assert tg.sent == [("hi", None)]
    assert nt.sent == []


async def test_ntfy_only(monkeypatch):
    tg, nt = FakeChannel("telegram"), FakeChannel("ntfy")
    _wire(monkeypatch, tg, nt)
    await notify_mod.notify("hi", channel="ntfy", title="T")
    assert nt.sent == [("hi", "T")]
    assert tg.sent == []


async def test_both(monkeypatch):
    tg, nt = FakeChannel("telegram"), FakeChannel("ntfy")
    _wire(monkeypatch, tg, nt)
    await notify_mod.notify("hi", channel="both")
    assert tg.sent == [("hi", None)]
    assert nt.sent == [("hi", None)]


async def test_unknown_channel_raises(monkeypatch):
    tg, nt = FakeChannel("telegram"), FakeChannel("ntfy")
    _wire(monkeypatch, tg, nt)
    with pytest.raises(ValueError, match="Unknown channel"):
        await notify_mod.notify("hi", channel="email")


async def test_unconfigured_ntfy_skipped_no_raise(monkeypatch):
    tg = FakeChannel("telegram")
    nt = FakeChannel("ntfy", configured=False)
    _wire(monkeypatch, tg, nt)
    await notify_mod.notify("hi", channel="both")  # ntfy skipped; telegram delivers
    assert tg.sent == [("hi", None)]
    assert nt.sent == []


async def test_configured_failure_raises_and_other_attempted(monkeypatch):
    tg = FakeChannel("telegram", fail=True)
    nt = FakeChannel("ntfy")
    _wire(monkeypatch, tg, nt)
    with pytest.raises(RuntimeError, match="telegram"):
        await notify_mod.notify("hi", channel="both")
    assert nt.sent == [("hi", None)]  # other channel still attempted
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_notify_dispatch.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.channels.notify'`.

- [ ] **Step 3: Implement the dispatcher**

Create `app/channels/notify.py`:
```python
"""The notify() seam: route a message to one or more channels.

General-purpose — usable from workflows, scheduler jobs, reminders, anywhere.
v1 has no priority concept; see the spec's V2 section.
"""

import logging

from app.channels.base import NotificationChannel
from app.channels.ntfy import NtfyChannel
from app.channels.telegram import TelegramChannel

logger = logging.getLogger(__name__)

VALID_CHANNELS = ("telegram", "ntfy", "both")


def _targets(channel: str) -> list[NotificationChannel]:
    if channel == "telegram":
        return [TelegramChannel()]
    if channel == "ntfy":
        return [NtfyChannel()]
    if channel == "both":
        return [TelegramChannel(), NtfyChannel()]
    raise ValueError(f"Unknown channel {channel!r}; expected one of {VALID_CHANNELS}")


async def notify(text: str, *, channel: str = "telegram", title: str | None = None) -> None:
    """Send `text` via the named channel(s). Skips unconfigured channels with a
    warning; raises RuntimeError if any *configured* target fails (after attempting
    the rest)."""
    targets = _targets(channel)
    errors: list[str] = []
    delivered = 0
    for ch in targets:
        if not ch.configured:
            logger.warning("notify: channel %s requested but not configured; skipping", ch.name)
            continue
        try:
            await ch.send(text, title=title)
            delivered += 1
        except Exception as exc:  # noqa: BLE001 — collected and re-raised below
            logger.exception("notify: channel %s failed", ch.name)
            errors.append(f"{ch.name}: {exc}")
    if errors:
        raise RuntimeError("notify delivery failed: " + "; ".join(errors))
    if delivered == 0:
        logger.warning("notify: no configured channel for %r; nothing sent", channel)
```

- [ ] **Step 4: Re-export from the package**

Replace the contents of `app/channels/__init__.py` with:
```python
from app.channels.notify import notify

__all__ = ["notify"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_notify_dispatch.py -v`
Expected: PASS (6 passed).

- [ ] **Step 6: Commit**

```bash
git add api/app/channels/notify.py api/app/channels/__init__.py api/tests/test_notify_dispatch.py
git commit -m "feat(notify): add notify() dispatcher (telegram/ntfy/both)"
```

---

## Task 6: Refactor existing call sites onto `notify()`

**Files:**
- Modify: `app/workflows/lib.py` (the `notify` function, lines 44–51)
- Modify: `app/scheduler/jobs.py` (`scheduled_gmail_triage_job` and `fire_reminder_job`)
- Test: `tests/test_workflow_lib.py` (add one test), `tests/test_reminders.py` (add one test)

### 6a — `lib.notify` delegates to the seam

- [ ] **Step 1: Write the failing test**

Append to `tests/test_workflow_lib.py`:
```python
def test_notify_delegates_to_channel_seam(monkeypatch):
    calls = {}

    async def rec(text, *, channel="telegram", title=None):
        calls.update(text=text, channel=channel, title=title)

    monkeypatch.setattr("app.channels.notify.notify", rec)
    asyncio.run(lib.notify("hi", channel="ntfy"))
    assert calls == {"text": "hi", "channel": "ntfy", "title": None}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_workflow_lib.py::test_notify_delegates_to_channel_seam -v`
Expected: FAIL — current `lib.notify(text)` has no `channel` kwarg → `TypeError: notify() got an unexpected keyword argument 'channel'`.

- [ ] **Step 3: Rewrite `lib.notify`**

In `app/workflows/lib.py`, replace the existing `notify` function (lines 44–51):
```python
async def notify(text: str) -> None:
    """Send a (chunked) Telegram message to the owner."""
    from telegram import Bot

    from app.channels.telegram import send_chunked

    settings = get_settings()
    await send_chunked(Bot(settings.telegram_bot_token), settings.telegram_chat_id, text)
```
with:
```python
async def notify(text: str, *, channel: str = "telegram", title: str | None = None) -> None:
    """Send a notification to the owner via one or more channels (telegram|ntfy|both)."""
    from app.channels.notify import notify as _notify

    await _notify(text, channel=channel, title=title)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_workflow_lib.py::test_notify_delegates_to_channel_seam -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app/workflows/lib.py api/tests/test_workflow_lib.py
git commit -m "refactor(notify): lib.notify delegates to channel seam, gains channel/title"
```

### 6b — `fire_reminder_job` delivers via `notify()`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_reminders.py` (reuses the `session_db`, `fake_scheduler`, and `in_one_hour` helpers already in that file):
```python
async def test_fire_reminder_job_delivers_via_notify(session_db, fake_scheduler, monkeypatch):
    from app.scheduler import jobs
    from app.store.db import Reminder, ReminderStatus, get_session

    sent = []

    async def rec(text, *, channel="telegram", title=None):
        sent.append(text)

    monkeypatch.setattr(jobs, "notify", rec)

    r = create_reminder("call mom", in_one_hour())
    await jobs.fire_reminder_job(r.id)

    assert sent == ["⏰ Reminder: call mom"]
    with get_session() as s:
        assert s.get(Reminder, r.id).status == ReminderStatus.FIRED
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_reminders.py::test_fire_reminder_job_delivers_via_notify -v`
Expected: FAIL — `jobs` has no attribute `notify` (`AttributeError` on the `monkeypatch.setattr`).

- [ ] **Step 3: Add the top-level import and refactor `fire_reminder_job`**

In `app/scheduler/jobs.py`, add to the imports block (after line 16, `from app.config import get_settings`):
```python
from app.channels import notify
```

Then in `fire_reminder_job`, remove the now-dead late import and the unused `settings`, and replace the send. Change this:
```python
async def fire_reminder_job(reminder_id: int) -> None:
    """Send a due reminder to the owner's Telegram chat and update its status."""
    from telegram import Bot

    from app.store.db import Reminder, ReminderStatus, get_session, utcnow
    from app.observability.sink import record_run

    settings = get_settings()
    with get_session() as s:
```
to:
```python
async def fire_reminder_job(reminder_id: int) -> None:
    """Send a due reminder to the owner and update its status."""
    from app.store.db import Reminder, ReminderStatus, get_session, utcnow
    from app.observability.sink import record_run

    with get_session() as s:
```
And change the delivery line inside the `try:`:
```python
            bot = Bot(token=settings.telegram_bot_token)
            await bot.send_message(chat_id=settings.telegram_chat_id, text=f"⏰ Reminder: {text}")
```
to:
```python
            await notify(f"⏰ Reminder: {text}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_reminders.py::test_fire_reminder_job_delivers_via_notify -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app/scheduler/jobs.py api/tests/test_reminders.py
git commit -m "refactor(notify): fire_reminder_job delivers via notify()"
```

### 6c — `scheduled_gmail_triage_job` (mechanical swap, no new logic)

> The digest send + failure alert are a straight swap from inline `Bot(...)` to `notify()` — no new branching. They are covered by the dispatcher unit tests (Task 5); the regression guard here is the full suite (Step 3).

- [ ] **Step 1: Refactor the digest send**

In `app/scheduler/jobs.py`, `scheduled_gmail_triage_job`:

Remove the late import on line 34:
```python
    from telegram import Bot
```

Remove the now-unused `settings = get_settings()` (line 38).

Replace the digest send:
```python
            if result.new_emails or result.errors:
                from app.channels.telegram import send_chunked

                bot = Bot(token=settings.telegram_bot_token)
                await send_chunked(bot, settings.telegram_chat_id, digest)
```
with:
```python
            if result.new_emails or result.errors:
                await notify(digest)
```

Replace the failure alert:
```python
        try:
            bot = Bot(token=settings.telegram_bot_token)
            await bot.send_message(chat_id=settings.telegram_chat_id, text="⚠ Scheduled email triage failed — check logs.")
        except Exception:
            logger.exception("Could not report triage failure to Telegram")
```
with:
```python
        try:
            await notify("⚠ Scheduled email triage failed — check logs.")
        except Exception:
            logger.exception("Could not report triage failure")
```

- [ ] **Step 2: Verify no `Bot` references remain in jobs.py**

Run: `grep -n "Bot" app/scheduler/jobs.py`
Expected: no output (all inline `Bot` usage removed).

- [ ] **Step 3: Run the full suite (regression guard)**

Run: `uv run pytest`
Expected: PASS — all tests, including the existing triage/reminder tests, green.

- [ ] **Step 4: Commit**

```bash
git add api/app/scheduler/jobs.py
git commit -m "refactor(notify): route triage digest + failure alert through notify()"
```

---

## Final verification

- [ ] Run the full suite from `api/`: `uv run pytest` → all green.
- [ ] Manual smoke (operator, once `NTFY_TOPIC` is set in `.env`): from a Python shell,
      `import asyncio; from app.channels import notify; asyncio.run(notify.notify("rotom test", channel="ntfy"))`
      → the push arrives on the ntfy topic. Repeat with `channel="both"` to confirm Telegram + ntfy.
- [ ] Confirm existing Telegram notifications (reminder fire, triage digest) still arrive unchanged.

---

## Self-review (against the spec)

**Spec coverage:**
- §3 module layout → Tasks 2–5 create `base/ntfy/notify`, Task 4 extends `telegram.py`. ✓
- §4.1 Protocol → Task 2. ✓
- §4.2 `NtfyChannel` (URL, headers, token-optional, no Priority, timeout, raise) → Task 3. ✓
- §4.3 `TelegramChannel` (title prepend, send_chunked) → Task 4. ✓
- §4.4 dispatch semantics (telegram/ntfy/both, skip-unconfigured, aggregate-raise, ValueError) → Task 5. ✓
- §5 raise-on-failure preserves reminder behavior → Task 6b asserts `FIRED` only after delivery. ✓
- §6 config + `.env.example` → Task 1. ✓
- §7 refactor map (lib.notify, triage digest, triage failure, fire_reminder) → Task 6a/6b/6c. ✓
- §9 tests (ntfy request shape, token-only-when-set, non-2xx + timeout raise, token not leaked, routing, skip, failure; lib delegation; reminder regression) → Tasks 3/5/6. ✓
- §2 security (terse content, topic in `.env`, token optional) → reflected in Task 1 `.env.example` + ntfy docstring. ✓

**Placeholder scan:** none — every code/test step has full content; no TBD/"handle errors".

**Type consistency:** `NotificationChannel` (`name`, `configured`, `send(text, *, title=None)`) is identical across base.py, both channels, the dispatcher's `list[NotificationChannel]`, and the fakes. `notify(text, *, channel="telegram", title=None)` signature matches in `notify.py`, `lib.notify`, and all call sites/tests. `VALID_CHANNELS` defined once in `notify.py`.

**Out of scope (V2, per spec §10 + TODO):** priority field/mapping, urgent→ntfy escalation, per-reminder channel/priority columns + UI, generalized routing, ntfy hardening/extras. Not in this plan.
