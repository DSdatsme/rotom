# Notify Channels (ntfy.sh) — Design Spec

**Date:** 2026-06-14
**Status:** Approved for implementation (v1)
**Owner:** Darshit

---

## 1. Context & goal

Today every outbound notification builds a Telegram `Bot(token)` inline and sends directly. The
send logic is duplicated across `workflows/lib.py`, `scheduler/jobs.py` (triage digest, triage
failure alert, reminder fire). There is no abstraction and no second channel.

**Goal (v1):** introduce a single, general-purpose `notify()` seam backed by a pluggable
`NotificationChannel` abstraction, add **ntfy.sh** as a second channel, and refactor the existing
scattered Telegram sends onto the seam. `notify()` is **not reminder-specific** — any code
(workflows especially) can call it at any point.

**Explicitly v1 only:** plumbing + the ntfy channel + refactor. Behavior of existing call sites is
**unchanged** (still Telegram) unless a caller opts into `channel="ntfy"` / `"both"`.

### Non-goals (deferred to V2 — see §10)
- `priority` field and ntfy priority mapping.
- "urgent → ntfy" escalation routing.
- Per-reminder `channel`/`priority` columns + dashboard/parser UI.
- Generalized/config-driven routing policy.

---

## 2. Security note (READ FIRST)

The target topic is the **free, unprotected** `https://ntfy.sh/your-ntfy-topic`. Unprotected
ntfy topics are **world-readable and world-writable** by anyone who knows the topic name.

Therefore, in v1:
- ntfy messages must be **terse and non-sensitive**. Do **not** route full email bodies, sender
  addresses, secrets, or other sensitive content to ntfy.
- The topic name lives in **gitignored `.env`**, never committed. `.env.example` carries only a
  placeholder.
- `NTFY_TOKEN` support exists (sent as `Authorization: Bearer`) but is **optional/empty** for the
  unprotected topic.

(Hardening — a protected or less-guessable topic — is V2.)

---

## 3. Architecture

A small `NotificationChannel` Protocol + a `notify()` dispatcher. Two concrete channels
(Telegram, ntfy). No registry/config-list machinery (YAGNI for two channels).

```
app/channels/
  __init__.py        # re-export notify()
  base.py            # NotificationChannel Protocol  (NEW)
  ntfy.py            # NtfyChannel                   (NEW)
  telegram.py        # existing inbound bot + send helpers; ADD TelegramChannel
  notify.py          # notify() dispatcher           (NEW)
```

All sends are **async** (every current caller is async). ntfy uses `httpx.AsyncClient`
(`httpx>=0.28` is already a dependency). Telegram reuses the existing `send_chunked` helper.

---

## 4. Component specs

### 4.1 `app/channels/base.py` (NEW)

```python
from typing import Protocol

class NotificationChannel(Protocol):
    name: str  # "telegram" | "ntfy"

    @property
    def configured(self) -> bool:
        """True if this channel has the settings it needs to send."""
        ...

    async def send(self, text: str, *, title: str | None = None) -> None:
        """Deliver a message. MUST raise on delivery failure."""
        ...
```

### 4.2 `app/channels/ntfy.py` (NEW)

`NtfyChannel`:
- `name = "ntfy"`.
- Reads settings: `ntfy_base_url`, `ntfy_topic`, `ntfy_token`.
- `configured` → `bool(self.topic)` (i.e. `NTFY_TOPIC` is set). Base URL has a default, token is
  optional.
- `async def send(text, *, title=None)`:
  - URL: `f"{base_url.rstrip('/')}/{topic}"`.
  - Method: `POST`, body = `text` encoded UTF-8.
  - Headers: `Title: {title}` only when `title` is provided; `Authorization: Bearer {token}` only
    when `ntfy_token` is non-empty.
  - **Do not set a `Priority` header** in v1 (ntfy defaults to 3 / "default").
  - Use `httpx.AsyncClient(timeout=10.0)`.
  - On non-2xx status or any `httpx` error/timeout → raise `RuntimeError` with status code +
    truncated response body (≤200 chars). Never leak the token in the error.

Example shape:
```python
async with httpx.AsyncClient(timeout=10.0) as client:
    resp = await client.post(url, content=text.encode("utf-8"), headers=headers)
if resp.status_code >= 300:
    raise RuntimeError(f"ntfy POST failed ({resp.status_code}): {resp.text[:200]}")
```

### 4.3 `app/channels/telegram.py` (MODIFY — keep existing bot code intact)

Add a `TelegramChannel` class alongside the existing `chunk_text` / `send_chunked` /
`create_bot_app`. Do **not** touch the inbound bot handlers.

`TelegramChannel`:
- `name = "telegram"`.
- Reads `telegram_bot_token`, `telegram_chat_id`.
- `configured` → `bool(token and chat_id)`.
- `async def send(text, *, title=None)`:
  - If `title` is provided, prepend it as a plain first line: `f"{title}\n{text}"`.
  - Construct `telegram.Bot(token)` and call the existing `send_chunked(bot, chat_id, message)`.
  - Any exception propagates (the helper already raises on send failure).

### 4.4 `app/channels/notify.py` (NEW) — the seam

```python
VALID_CHANNELS = ("telegram", "ntfy", "both")

async def notify(text: str, *, channel: str = "telegram", title: str | None = None) -> None:
    ...
```

Dispatch semantics:
1. Resolve `channel` to a target list: `telegram`→[telegram], `ntfy`→[ntfy],
   `both`→[telegram, ntfy]. Unknown value → `ValueError`.
2. Build the channel instances (from `get_settings()`).
3. For each target, classify the outcome:
   - **skipped** — `not channel.configured`: log a `warning` ("notify: channel X requested but not
     configured; skipping") and move on. Not an error.
   - **delivered** — `send()` returned.
   - **failed** — `send()` raised: log `exception`, remember the error.
4. After attempting all targets: if **any** target **failed**, raise a `RuntimeError` aggregating
   the failures (e.g. `"notify delivery failed: ntfy: ..."`). Channels that already delivered stay
   delivered.
5. If all targets were **skipped** (none delivered, none failed) → log a `warning` and return
   without raising. (Accepted v1 simplification; in practice Telegram is always configured.)

`app/channels/__init__.py` re-exports `notify` so callers can `from app.channels import notify`.

---

## 5. Why "raise on failure" matters

`scheduler/jobs.py:fire_reminder_job` only sets `Reminder.fired_at` / status `fired` **after** a
successful send (it catches the send exception and skips marking on failure). Reminders remain
**Telegram-only** in v1, and `notify(text, channel="telegram")` raises on Telegram send failure —
so wrapping the existing send in `notify()` **preserves today's exact "don't mark fired if delivery
failed" behavior**. Keep the surrounding `try/except` in `fire_reminder_job` as-is.

---

## 6. Config changes

### `app/config.py` (Settings, `BaseSettings`, `extra="allow"`)
Add three fields next to the existing `telegram_bot_token` / `telegram_chat_id`:

```python
ntfy_base_url: str = "https://ntfy.sh"
ntfy_topic: str = ""      # empty → ntfy channel is inert (skipped)
ntfy_token: str = ""      # optional; sent as "Authorization: Bearer" when set
```

### `.env.example` (repo root)
Add a commented block:
```
# --- ntfy push notifications (optional) ---
# NTFY_BASE_URL=https://ntfy.sh
# NTFY_TOPIC=your-secret-topic-name
# NTFY_TOKEN=            # leave empty for unprotected topics
```
(The real values go in gitignored `.env`; never commit the topic name.)

---

## 7. Refactor map — existing call sites onto `notify()`

Behavior must stay **Telegram + unchanged**. Just replace inline `Bot(...)` sends with `notify()`.

| File | Current (inline `Bot`) | Change to |
|------|------------------------|-----------|
| `app/workflows/lib.py` | `async def notify(text)` builds `Bot` + `send_chunked` | Delegate to `app.channels.notify.notify`, **adding the `channel` arg**: `async def notify(text, *, channel="telegram", title=None)`. Workflow steps can now pass `channel="ntfy"`/`"both"`. Keep it importable from `lib` (the workflow helper seam). |
| `app/scheduler/jobs.py` — `scheduled_gmail_triage_job` | `send_chunked(bot, chat_id, digest)` | `await notify(digest)` |
| `app/scheduler/jobs.py` — `scheduled_gmail_triage_job` (failure path) | `bot.send_message(... "⚠ Scheduled email triage failed …")` | `await notify("⚠ Scheduled email triage failed — check logs.")` |
| `app/scheduler/jobs.py` — `fire_reminder_job` | `bot.send_message(... f"⏰ Reminder: {text}")` | `await notify(f"⏰ Reminder: {text}")` — **inside the existing `try/except`**, unchanged marking logic. |

Remove the now-unused inline `from telegram import Bot` imports where they become dead. Keep
`send_chunked` (still used by `TelegramChannel`).

---

## 8. Error handling summary

- ntfy: timeout / non-2xx / transport error → `RuntimeError` (token never logged).
- Telegram: existing `send_chunked` raises on failure → propagates.
- Dispatcher: per-target `try/except`; aggregate-raise if any **configured** target failed; warn +
  skip unconfigured targets; warn (no raise) if everything was skipped.

---

## 9. Testing (TDD; mock all network — NO live pushes, NO LLM calls)

New tests under `api/tests/`:

### `test_ntfy_channel.py`
- Builds correct URL `{base}/{topic}`, body = text (UTF-8), `Title` header only when title given.
- `Authorization: Bearer` header present only when `ntfy_token` set; absent otherwise.
- No `Priority` header is sent.
- `configured` is False when `ntfy_topic` empty, True when set.
- Raises `RuntimeError` on non-2xx response and on `httpx` timeout (mock `httpx.AsyncClient`).
- Token never appears in the raised error message.

### `test_notify_dispatch.py`
- `channel="telegram"` → only Telegram `send` called.
- `channel="ntfy"` → only ntfy `send` called.
- `channel="both"` → both called.
- Unknown channel → `ValueError`.
- ntfy requested but unconfigured (`NTFY_TOPIC=""`) → warning logged, **no raise**, Telegram path
  (in `both`) still delivers.
- A configured channel raising → `notify` raises `RuntimeError`; the other channel in `both` is
  still attempted.

### Regression guard
- After refactor, `fire_reminder_job` / triage digest still deliver via Telegram (assert
  `TelegramChannel.send` / `send_chunked` is invoked with the expected text). Mock the bot.

Use the existing test patterns (`pytest`, `asyncio_mode="auto"`, monkeypatch/`unittest.mock`).

---

## 10. Deferred to V2 (recorded in `TODO.md`)

- `priority` field (`low`/`default`/`urgent`) + ntfy priority mapping (`low→2, default→3,
  urgent→5`) and Telegram silent-send for `low`.
- `urgent → auto-include ntfy` escalation rule.
- Per-reminder `channel` + `priority` columns on the `Reminder` model; NL parser keywords + the
  dashboard add-form selector + parse-confirmation display.
- Generalized routing policy (per-event-type channel defaults).
- ntfy hardening: protected topic / `NTFY_TOKEN` required / less-guessable topic name.
- ntfy extras: `Tags`/emoji, `Click` deep-link back to the dashboard, message titles for reminders.

---

## 11. File-by-file change list (for the implementer)

**New**
- `app/channels/base.py` — `NotificationChannel` Protocol.
- `app/channels/ntfy.py` — `NtfyChannel`.
- `app/channels/notify.py` — `notify()` dispatcher.
- `api/tests/test_ntfy_channel.py`, `api/tests/test_notify_dispatch.py`.

**Modify**
- `app/channels/__init__.py` — re-export `notify`.
- `app/channels/telegram.py` — add `TelegramChannel` (leave bot code untouched).
- `app/config.py` — add `ntfy_base_url`, `ntfy_topic`, `ntfy_token`.
- `app/workflows/lib.py` — `notify` delegates to `channels.notify.notify`, gains `channel`/`title`.
- `app/scheduler/jobs.py` — route the 3 sends through `notify()`; drop dead `Bot` imports.
- `.env.example` — ntfy block.
- `TODO.md` — move priority/escalation/per-reminder UI items under a "Notify v2" sub-list.

**Acceptance:** `uv run pytest` green; existing notifications still arrive on Telegram; a manual
`await notify("test", channel="ntfy")` (or `"both"`) with `NTFY_TOPIC` set reaches the ntfy topic.
