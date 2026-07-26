# Digest Synthesis: Morning Brief + Weekly Retro — Design Spec

**Date:** 2026-07-26
**Status:** Approved for implementation (v1)
**Owner:** Darshit

---

## 1. Context & goal

Rotom already pushes two kinds of scheduled Telegram messages: the Gmail triage digest
(`scheduled_gmail_triage_job`, APScheduler, every 6h) and a placeholder Inngest workflow
called `morning-digest` that summarizes Hacker News at 8:30am. There is no daily calendar
briefing and no weekly look-back.

**Goal (v1):** two new, independent Inngest workflows:
- **Morning Brief** — today's merged calendar agenda (all accounts), sent daily at 8:30am.
- **Weekly Retro** — a Sunday-evening look-back covering email triage stats, draft activity,
  reminder activity, and workflow-run counts.

Both are deterministic (no LLM call) — they restate data that already exists, they don't
need to write new prose.

**Explicitly out of scope for v1** (from the broader "cross-source synthesis" brainstorm,
deferred to later sub-projects):
- Conflict-aware drafting (detecting double-bookings and drafting a decline/reschedule).
- Meeting prep packets (matching a calendar event to its related email thread).
- Folding email/reminders into the *morning* brief, or next week's calendar into the
  *weekly* retro — both were explicitly scoped out when this was designed; the two
  messages stay complementary (morning = forward/daily/calendar-only, retro =
  backward/weekly/everything-but-calendar) rather than overlapping.
- LLM-narrated prose for either message — both are plain, deterministic formatting.

---

## 2. Architecture

```
api/app/tools/calendar/service.py     # ADD format_daily_brief()
api/app/tools/retro/__init__.py       # NEW
api/app/tools/retro/service.py        # NEW — 4 stat-gathering + formatting functions

api/app/workflows/daily_calendar_brief.py   # NEW
api/app/workflows/weekly_retro.py           # NEW
api/app/workflows/registry.py               # MODIFY — register both
api/app/workflows/morning_digest.py         # MODIFY — wrap in record_run (see §5)
api/app/workflows/code_issue.py             # MODIFY — wrap in record_run (see §5)
```

Both new workflows follow the existing `morning_digest.py` shape exactly: a
`TriggerCron` + a matching `TriggerEvent` (for on-demand chat/manual firing), one
`ctx.step.run` for the substantive work, one for `notify()`. No new DB table, no new
cron system — reuses Inngest (already running) exactly like `morning_digest.py` and
`code_issue.py` do today.

---

## 3. Morning Brief

### 3.1 Data
Reuses the calendar feature exactly as shipped — no new backend module for fetching:
`app.tools.calendar.client.load_accounts(settings)` →
`app.tools.calendar.service.list_events_for_range(accounts, time_min, time_max, tz_name)`,
with `time_min`/`time_max` bounding **today only** (`datetime.now(zone).date()` through the
next day, in `settings.timezone`) rather than a week.

### 3.2 Formatting — new `format_daily_brief()` in `tools/calendar/service.py`
Plain chronological list, matching the approved preview:
```
📅 Today — Tue Jul 28

09:00 Standup [work]
13:00 Dentist [personal]
16:00 1:1 w/ Priya [work]
```
- All-day events get their own line at the top (no time prefix), same as the dashboard grid.
- No events → `"📅 Today — Tue Jul 28\n\nNothing on the calendar today."`
- If `errors` is non-empty, append one terse footnote line — `"⚠ 2 accounts unavailable"` —
  never the raw per-account error text (that's dashboard-appropriate detail, not
  Telegram-appropriate).

### 3.3 Workflow (`daily_calendar_brief.py`)
`TriggerCron("30 8 * * *")` + `TriggerEvent("workflows/daily-calendar-brief.requested")`.
One `record_run("daily_calendar_brief", source="inngest")` wraps the fetch+format step —
`.degrade()` if any account errored (data is still useful, just partial), plain success
otherwise. The `notify()` step is separate and un-instrumented, matching
`morning_digest.py`'s existing behavior (Inngest's own `retries=2` handles delivery
failures — no need to duplicate that with a manual try/except).

---

## 4. Weekly Retro

### 4.1 Data — new `tools/retro/service.py`, four functions, each reading from what
already exists (no re-computation, no new tables):

- `triage_stats(since: datetime) -> dict[str, int]` — `Email` table (main DB), `created_at
  >= since`, counted by `category` (critical/needs_reply/fyi/skip).
- `draft_activity(since: datetime) -> dict` — `Draft` table (main DB):
  - `sent`: count where `sent_at >= since`.
  - `pending`: **all** currently-pending drafts regardless of age (an old unsent draft is
    more worth nudging about, not less — not time-boxed).
  - `discarded`: count where `status == discarded` and `updated_at >= since` (approximate —
    there's no dedicated `discarded_at` column; `updated_at` is the closest proxy).
- `reminder_stats(since: datetime) -> dict` — `Reminder` table (main DB):
  - `fired`: count where `fired_at >= since`.
  - `pending`: current count where `status == pending` (live snapshot, not time-boxed).
- `workflow_run_stats(since: datetime) -> dict[str, dict]` — `RunLog` table
  (**observability DB**, separate session from the other three), `source == "inngest"` and
  `started_at >= since`, grouped by `kind`, each entry `{count, success, failure, degraded}`.

`format_weekly_retro(stats: dict) -> str` assembles the four sections into one message,
each a short labeled block (counts, not prose).

### 4.2 Instrumentation gap this depends on
`workflow_run_stats` only works if every top-level workflow actually writes a `RunLog` row.
Today, `code_issue.py` calls `record_run` **around individual internal steps** ("coder",
"code_review") but never around the workflow as a whole, and `morning_digest.py` doesn't
call `record_run` at all. Fix: give each of the four top-level workflows — `code_issue`,
`morning_digest`, `daily_calendar_brief`, `weekly_retro` — one `record_run(kind="<workflow-
name>", source="inngest")` around its own substantive step, the same scoping already used
for the two new workflows (§3.3, §4.3) — never around the `notify()` step, and never
spanning multiple `ctx.step.run` calls at once (keeps each recorded run inside a single
Inngest step's boundary, matching the one existing precedent). For `code_issue.py`
specifically, this means one *new*, additional `record_run("code_issue", ...)` around
whichever step is judged its main unit of work (nesting already supports this — existing
inner "coder"/"code_review" runs become children via `parent_run_id` automatically); for
`morning_digest.py`, wrap its existing "summarize" (or fetch) step, whichever is judged the
substantive one. No behavior change to any workflow's actual work, only to what gets
recorded.

### 4.3 Workflow (`weekly_retro.py`)
`TriggerCron("0 18 * * 0")` (Sunday 6pm) + `TriggerEvent("workflows/weekly-retro.requested")`.
One `record_run("weekly_retro", source="inngest")` wraps the four stat-gathering calls +
formatting; always a plain success (there's no partial-failure mode here — either the DB
queries work or the run fails outright, no degraded state needed).

---

## 5. Testing

### `tools/calendar/service.py` additions
- `format_daily_brief`: empty events → "nothing today" message; single timed event;
  all-day event rendered without a time prefix; non-empty `errors` appends the footnote
  line; multiple events stay in chronological order.

### `tools/retro/service.py` (new)
- `triage_stats`: emails split across categories and across the `since` boundary — only
  in-window ones counted, grouped correctly.
- `draft_activity`: a draft sent this week, one sent last week (excluded from `sent`), an
  old pending draft (included in `pending` despite being outside the window), a discarded
  draft updated this week vs. one updated last week.
- `reminder_stats`: fired this week vs. fired last week (excluded); pending count unaffected
  by `since`.
- `workflow_run_stats`: multiple `RunLog` rows across different `kind`s and statuses within
  and outside the window; grouping and status breakdown are correct.
- `format_weekly_retro`: renders all four sections from a hand-built stats dict.

### Workflows
Same minimal pattern as `test_code_issue_workflow_import.py` — for each new workflow:
`test_<name>_imports_without_inngest_server_or_token` and `test_<name>_registered`. The
`record_run` wrapping added to `code_issue.py`/`morning_digest.py` is exercised indirectly
by their existing import/registration tests (no behavior to newly unit-test there beyond
"still imports cleanly").

---

## 6. File-by-file change list

**New**
- `api/app/tools/retro/__init__.py`
- `api/app/tools/retro/service.py`
- `api/app/workflows/daily_calendar_brief.py`
- `api/app/workflows/weekly_retro.py`
- Tests: `api/tests/test_retro_service.py`, `api/tests/test_calendar_daily_brief_format.py`
  (or folded into the existing `test_calendar_service.py`), `api/tests/test_daily_calendar_brief_workflow.py`,
  `api/tests/test_weekly_retro_workflow.py`.

**Modify**
- `api/app/tools/calendar/service.py` — add `format_daily_brief`.
- `api/app/workflows/registry.py` — register both new workflows.
- `api/app/workflows/morning_digest.py` — wrap in an outer `record_run`.
- `api/app/workflows/code_issue.py` — wrap in an outer `record_run` (additive to existing
  inner ones).
- `TODO.md` — mark this sub-project done; keep meeting-prep and conflict-aware-drafting as
  the remaining "cross-source synthesis" backlog items.

**Acceptance:** `uv run pytest` green; a manual on-demand fire of each workflow
(`TriggerEvent`, via Inngest's dev dashboard or a chat `run_workflow` call) delivers a
correctly formatted message to Telegram; `weekly_retro`'s workflow-run section shows nonzero
counts once at least one of the four workflows has run since the instrumentation landed.
