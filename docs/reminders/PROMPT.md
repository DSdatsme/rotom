# Generation prompt — reminders & NL scheduling

> Paste into an AI coding agent together with `docs/architecture/PROMPT.md` (it assumes the
> skeleton: settings/`TIMEZONE`, SQLite store with `as_utc`/`utcnow`, the module-level
> APScheduler with a persistent jobstore, the Telegram channel).

---

Build a reminder feature: one-time and recurring reminders that fire a Telegram message to
the owner, created by agent tools, the dashboard, or natural language.

**Model.** A `Reminder` row: `text`, `fire_at` (timezone-aware UTC, the first/next
occurrence), `recurrence_cron` (string, "" = one-time), `status` ∈ {pending, fired,
cancelled}, `created_at`, `fired_at`. A `reminder_json(r)` serializer also computes
`next_fire_at`.

**Scheduling** (`scheduler/jobs.py`, functions module-level + picklable, scalar args only):
- `schedule_reminder_job(scheduler, reminder)`: `DateTrigger(run_date=as_utc(fire_at))` for
  one-time, else `CronTrigger.from_crontab(recurrence_cron, timezone=TIMEZONE)`. Job id
  `reminder-<id>`, `replace_existing=True`, `misfire_grace_time=3600`.
- `fire_reminder_job(reminder_id)`: reload the row; skip if gone/non-pending; send the
  Telegram message; on send failure return without marking fired; on success set `fired_at`
  and mark one-time reminders `fired` (recurring stay pending).
- `unschedule_reminder_job(scheduler, id)`: remove the job if present.
- `reschedule_pending_reminders(scheduler)` at boot: for each pending reminder with no live
  job — recurring ⇒ re-register; one-time with `fire_at <= now` ⇒ fire immediately (don't
  lose it); else re-register. Run this once on startup.

**Service** (`tools/reminders/service.py`): `create_reminder(text, fire_at, recurrence_cron)`
normalizes recurrence, rejects a past `fire_at` for one-time, enforces a max-active cap,
stores the row, and registers the job in one session. `cancel_reminder(id)` flips status and
removes the job. `list_reminders(status)`, and `next_fire_at(r)` (the `fire_at` for one-time,
else the cron trigger's next fire in UTC).

**NL parsing = propose, never schedule** (`tools/reminders/parser.py`): `parse_reminder(
message, llm, tz, now=None)` makes ONE structured-output LLM call → `ReminderProposal`
{text, fire_at (ISO + offset), recurrence_cron, confirmation}. Pass the current local
datetime + weekday into the prompt. Wrap the user message in `<reminder_request>` tags and
state it is DATA, not instructions. Re-validate the result: parse `fire_at`, attach the
user's tz if naive, and raise `ValueError` if a one-time time isn't in the future. Expose as
`POST /api/reminders/parse` that returns the proposal and schedules NOTHING — the dashboard
shows it and a Confirm click calls `create_reminder`. One LLM call per parse, period.

**Recurrence shorthands, deterministic** (`recurrence.py`, NO LLM): `normalize_recurrence(
expr, fire_at, tz)` maps "everyday"/"daily", "weekdays", "weekends", "weekly", "monthly",
"hourly", and "every <weekday>" to a crontab anchored to `fire_at`'s local minute/hour. Raw
5-field cron passes through after `CronTrigger.from_crontab` validates it; unrecognized input
raises with a help string. **Always emit day NAMES in the DOW field.**

> **The APScheduler DOW footgun:** `from_crontab` treats a *numeric* day-of-week as
> 0=Monday, but standard cron uses 1=Monday — silently off by one. Never emit or accept
> numeric DOW; use names (`mon`, `mon-fri`, `sat,sun`) everywhere, and tell the LLM the same.

**UI.** Countdown tiles (`font-mono tabular-nums`); the ticking `now` is `null` until a
`useEffect` mount so SSR/client match (no hydration mismatch); when a countdown hits zero,
`router.refresh()` once so fired reminders drop off. `datetime-local` is naive local — send
`new Date(value).toISOString()`. A chat bar: parse → show proposal → confirm.

**Tests** (FakeScheduler recording add/remove, FakeLLM, temp SQLite):
- service lifecycle: create registers a job; cancel flips status + removes the job.
- past one-time `fire_at` ⇒ `ValueError`.
- `normalize_recurrence`: "everyday"→`m h * * *`, "weekdays"→`m h * * mon-fri`,
  "every monday"→`m h * * mon`, "weekly" uses the fire day, raw cron passes, garbage raises.
- parser: future proposal accepted; a past one-time proposal raises; recurrence forces names.
- boot reconciliation: a pending one-time whose time passed gets a fire-now job.
