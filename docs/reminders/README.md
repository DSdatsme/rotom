# Reminders & NL scheduling

One-time and recurring reminders that fire a Telegram message to the owner. Created from
chat (agent tools), from the dashboard add tile, or by natural language. Backend lives in
`api/app/tools/reminders/` + `api/app/scheduler/jobs.py`; UI in `web/components/reminder-*`.

## Model & scheduling

- `Reminder` (`app/store/db.py`): `text`, `fire_at` (UTC, first/next occurrence),
  `recurrence_cron` ("" = one-time), `status` (pending/fired/cancelled), `fired_at`.
- `schedule_reminder_job` registers an APScheduler job per reminder: a `DateTrigger` for
  one-time, a `CronTrigger.from_crontab` for recurring, id `reminder-<id>`,
  `replace_existing=True`, `misfire_grace_time=3600` (fire up to an hour late if the
  process was down). `fire_reminder_job` is module-level (picklable, scalar arg only),
  sends the Telegram message, and marks one-time reminders `fired` (recurring keep firing).
- **Boot reconciliation** (`reschedule_pending_reminders`): on startup, for every pending
  reminder lacking a job — recurring ones get re-registered; one-time ones whose `fire_at`
  already passed are fired **immediately** rather than lost. Covers a wiped jobstore.

## NL parsing — propose, then confirm

`parse_reminder` (`parser.py`) makes exactly **one** LLM call returning a `ReminderProposal`
(text, `fire_at` ISO+offset, `recurrence_cron`, human `confirmation`). The API exposes this
as `POST /api/reminders/parse` — it schedules **nothing**. The UI shows the proposal; only
the user's Confirm click calls `create_reminder`. So token cost is exactly one call per
parse, and a misparse never silently schedules anything. The user message is wrapped in
`<reminder_request>` tags and framed as data, not instructions (injection defense). The
parser re-validates: `fire_at` must parse and (for one-time) be in the future, else `ValueError`.

## Recurrence shorthands — deterministic, no LLM

`normalize_recurrence` (`recurrence.py`) turns "everyday", "weekdays", "weekends", "weekly",
"monthly", "hourly", "every monday"… into a crontab anchored to the reminder's local
minute/hour — zero tokens, zero attack surface. Raw 5-field cron passes through after
validation; anything unrecognized raises with a help string.

## Gotchas we hit

- **APScheduler day-of-week footgun.** `CronTrigger.from_crontab` reads a *numeric* DOW as
  0=Monday, while standard cron is 1=Monday — off by one and silent. We ALWAYS emit and
  require day **names** (`mon`, `mon-fri`, `sat,sun`); the parser prompt and the agent tool
  docstring both forbid numeric DOW.
- SQLite returns naive datetimes — `as_utc()` re-attaches UTC before every comparison /
  `isoformat()`, or the browser parses the time as local.
- `datetime-local` in the add tile is naive local; the client does `toISOString()` so the
  API receives a proper UTC instant.
- `create_reminder` rejects a past `fire_at` for one-time reminders, and caps active
  reminders (`MAX_ACTIVE_REMINDERS`) so a runaway can't flood the scheduler.

## UI

`reminder-board.tsx`: countdown tiles, `font-mono tabular-nums`; the `now` clock is **null
until mounted** then ticks each second (hydration-safe). `reminder-chat-bar.tsx`: the
parse→proposal→confirm flow. Cancel/confirm call server actions then `router.refresh()`.

## Agent tools

`get_current_time` (call before relative-date reminders), `create_reminder`,
`list_reminders`, `cancel_reminder` — see `docs/telegram-agent/`.

## Key files

`tools/reminders/service.py` (create/list/cancel + `next_fire_at`) · `parser.py` ·
`recurrence.py` · `scheduler/jobs.py` · `store/db.py` (Reminder) ·
`web/components/reminder-board.tsx` · `web/components/reminder-chat-bar.tsx`
