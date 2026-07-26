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
api/app/workflows/morning_digest.py         # MODIFY — wrap in record_run (see §4.2)
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
- `workflow_run_stats(since: datetime) -> dict[str, dict]` — merges **two** sources, since
  not every workflow tracks itself the same way:
  - `RunLog` (**observability DB**, separate session from the other three), `source ==
    "inngest"` and `started_at >= since`, grouped by `kind`, each entry `{count, success,
    failure, degraded}` — covers `morning_digest`, `daily_calendar_brief`, `weekly_retro`.
  - `CodingRun` (**main DB**), `created_at >= since`, grouped by `status` — covers
    `code_issue`, which deliberately has **no** workflow-level `record_run` (see §4.2) and
    already tracks its own lifecycle in this dedicated table.
  Both are folded into one `{kind: {count, ...}}` dict so `format_weekly_retro` renders a
  single "workflow runs" section without needing to know which source each entry came from.

`format_weekly_retro(stats: dict) -> str` assembles the four sections into one message,
each a short labeled block (counts, not prose).

### 4.2 Instrumentation gap this depends on
`workflow_run_stats` needs every workflow it reports on to be trackable somehow — but not
all of them the same way, and that's fine (see §4.1's two-source merge above):

- `code_issue.py`'s own docstring is explicit: "the top-level lifecycle lives in the
  `CodingRun` table ... no workflow-wrapping `record_run`" — a deliberate existing decision,
  not a gap. **Leave `code_issue.py` untouched.** Its counts come from `CodingRun` directly.
- `morning_digest.py` calls `record_run` **not at all** today — this genuinely is a gap (it
  has no dedicated tracking table the way `code_issue` does). Fix: wrap its existing
  "summarize" step in `record_run("morning_digest", source="inngest")`.
- The two new workflows (§3.3, §4.3) each get their own `record_run` around their
  substantive step from the start, as already specced — never around `notify()`, and never
  spanning multiple `ctx.step.run` calls (keeps each recorded run inside a single Inngest
  step's boundary, matching the one existing precedent in `code_issue.py`'s inner
  "coder"/"code_review" runs).

Net effect: only `morning_digest.py` changes among the *existing* workflows;
`code_issue.py` is not touched.

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
`record_run` wrapping added to `morning_digest.py` is exercised indirectly
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
- `api/app/workflows/morning_digest.py` — wrap its "summarize" step in `record_run`.
- `TODO.md` — mark this sub-project done; keep meeting-prep and conflict-aware-drafting as
  the remaining "cross-source synthesis" backlog items.

**Acceptance:** `uv run pytest` green; a manual on-demand fire of each workflow
(`TriggerEvent`, via Inngest's dev dashboard or a chat `run_workflow` call) delivers a
correctly formatted message to Telegram; `weekly_retro`'s workflow-run section shows nonzero
counts once at least one of the four workflows has run since the instrumentation landed.
