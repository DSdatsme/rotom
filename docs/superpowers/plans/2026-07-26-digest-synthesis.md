# Digest Synthesis (Morning Brief + Weekly Retro) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two new Inngest workflows — a daily calendar-only morning brief and a Sunday
weekly retro (triage stats, draft activity, reminders, workflow-run counts) — both
deterministic, delivered to Telegram.

**Architecture:** Reuses the calendar feature's `list_events_for_range` unchanged for the
morning brief. A new `tools/retro/service.py` gathers weekly stats from existing tables
(no new DB schema). Both workflows follow `morning_digest.py`'s exact existing shape:
`TriggerCron` + `TriggerEvent`, one substantive `ctx.step.run`, one `notify()` step.

**Tech Stack:** Inngest (already running), SQLAlchemy against the existing main DB and the
separate observability DB, pytest.

Spec: `docs/superpowers/specs/2026-07-26-digest-synthesis-design.md`

## Global Constraints

- No new DB tables, no new migrations — every stat reads from tables that already exist
  (`emails`, `drafts`, `reminders`, `coding_runs`, `run_log`).
- No LLM calls in either workflow — both are deterministic formatting of data that already
  exists.
- `code_issue.py` is **not modified** — it deliberately has no workflow-level `record_run`
  (its own docstring: lifecycle lives in `CodingRun`). Only `morning_digest.py` gets new
  instrumentation.
- `record_run(...)` wraps a single workflow's substantive `ctx.step.run` step only — never
  the `notify()` step, never spanning multiple steps at once (matches the one existing
  precedent in `code_issue.py`'s inner "coder"/"code_review" runs).
- Synchronous SQLAlchemy queries against the local SQLite DBs are called directly from
  `async def` functions with **no** `asyncio.to_thread` wrap — this repo's `to_thread` rule
  targets slow external SDK calls (Gmail/Calendar/LLM), not local DB queries; `routes.py`'s
  existing reminder/email routes already call sync DB helpers directly from `async def`
  handlers this same way.
- Telegram messages stay terse: never include raw per-account error text or stack traces —
  that's dashboard-appropriate detail, not Telegram brevity (see `format_daily_brief`, §Task
  1).
- Never add an AI co-author / "Co-Authored-By" line to any commit (repo-wide rule).

---

### Task 1: `format_daily_brief()` in `tools/calendar/service.py`

**Files:**
- Modify: `api/app/tools/calendar/service.py`
- Modify: `api/tests/test_calendar_service.py`

**Interfaces:**
- Consumes: nothing new — takes the same `events`/`errors` shape `list_events_for_range`
  already produces (`{account, event_id, title, start, end, all_day, location}` /
  `{account, message}`).
- Produces: `format_daily_brief(events: list[dict], errors: list[dict], today: date) ->
  str`, consumed by Task 4's workflow.

- [ ] **Step 1: Write the failing tests**

Append to `api/tests/test_calendar_service.py` (after the existing `TestListEventsForRange`
class):

```python
class TestFormatDailyBrief:
    def test_no_events(self):
        from datetime import date

        from app.tools.calendar.service import format_daily_brief

        text = format_daily_brief([], [], date(2026, 7, 28))
        assert text == "📅 Today — Tue Jul 28\n\nNothing on the calendar today."

    def test_single_timed_event(self):
        from datetime import date

        from app.tools.calendar.service import format_daily_brief

        events = [{"account": "work", "title": "Standup", "start": "2026-07-28T09:00:00+05:30",
                   "end": "2026-07-28T09:30:00+05:30", "all_day": False, "event_id": "e1",
                   "location": None}]
        text = format_daily_brief(events, [], date(2026, 7, 28))
        assert "09:00 Standup [work]" in text

    def test_all_day_event_has_no_time_prefix(self):
        from datetime import date

        from app.tools.calendar.service import format_daily_brief

        events = [{"account": "personal", "title": "Diwali", "start": "2026-07-28",
                   "end": "2026-07-29", "all_day": True, "event_id": "e2", "location": None}]
        text = format_daily_brief(events, [], date(2026, 7, 28))
        assert "Diwali [personal]" in text
        # No leaked time-slice prefix (all-day events have no 'HH:MM' in their start string)
        assert "None Diwali" not in text

    def test_errors_append_terse_footnote_not_raw_text(self):
        from datetime import date

        from app.tools.calendar.service import format_daily_brief

        text = format_daily_brief([], [{"account": "broken", "message": "invalid_scope: Bad Request"}],
                                   date(2026, 7, 28))
        assert "⚠ 1 account unavailable" in text
        assert "invalid_scope" not in text  # raw error text stays out of Telegram

    def test_multiple_accounts_pluralizes_footnote(self):
        from datetime import date

        from app.tools.calendar.service import format_daily_brief

        text = format_daily_brief(
            [], [{"account": "a", "message": "x"}, {"account": "b", "message": "y"}], date(2026, 7, 28)
        )
        assert "⚠ 2 accounts unavailable" in text

    def test_multiple_events_preserve_input_order(self):
        from datetime import date

        from app.tools.calendar.service import format_daily_brief

        events = [
            {"account": "work", "title": "Standup", "start": "2026-07-28T09:00:00+05:30",
             "end": "2026-07-28T09:30:00+05:30", "all_day": False, "event_id": "e1", "location": None},
            {"account": "personal", "title": "Dentist", "start": "2026-07-28T13:00:00+05:30",
             "end": "2026-07-28T14:00:00+05:30", "all_day": False, "event_id": "e2", "location": None},
        ]
        text = format_daily_brief(events, [], date(2026, 7, 28))
        assert text.index("09:00 Standup") < text.index("13:00 Dentist")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd api && uv run pytest tests/test_calendar_service.py::TestFormatDailyBrief -v`
Expected: FAIL with `ImportError: cannot import name 'format_daily_brief'`

- [ ] **Step 3: Write the implementation**

In `api/app/tools/calendar/service.py`, change the top import line:

```python
from datetime import datetime, timezone
```

to:

```python
from datetime import date, datetime, timezone
```

Then append this function at the end of the file:

```python
def format_daily_brief(events: list[dict], errors: list[dict], today: date) -> str:
    """Plain-text daily brief for Telegram: today's events in the order given (callers
    pass output straight from list_events_for_range, already chronologically sorted).
    All-day events render without a time prefix. A non-empty errors list appends one
    terse footnote — never the raw per-account error text, which is dashboard-appropriate
    detail, not Telegram brevity."""
    header = f"📅 Today — {today:%a %b} {today.day}"
    if not events:
        body = "Nothing on the calendar today."
    else:
        lines = []
        for ev in events:
            if ev["all_day"]:
                lines.append(f"{ev['title']} [{ev['account']}]")
            else:
                lines.append(f"{ev['start'][11:16]} {ev['title']} [{ev['account']}]")
        body = "\n".join(lines)
    text = f"{header}\n\n{body}"
    if errors:
        n = len(errors)
        text += f"\n\n⚠ {n} account{'s' if n != 1 else ''} unavailable"
    return text
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && uv run pytest tests/test_calendar_service.py -v`
Expected: PASS (all existing tests + 5 new `TestFormatDailyBrief` tests)

- [ ] **Step 5: Commit**

```bash
git add api/app/tools/calendar/service.py api/tests/test_calendar_service.py
git commit -m "feat(digest): add format_daily_brief for the morning brief workflow"
```

---

### Task 2: `tools/retro/service.py` — triage, draft, and reminder stats

**Files:**
- Create: `api/app/tools/retro/__init__.py` (empty)
- Create: `api/app/tools/retro/service.py`
- Create: `api/tests/test_retro_service.py`

**Interfaces:**
- Produces: `triage_stats(since: datetime) -> dict[str, int]` (keys: `critical`,
  `needs_reply`, `fyi`, `skip`, always all four present). `draft_activity(since: datetime)
  -> dict` (keys: `sent`, `pending`, `discarded`). `reminder_stats(since: datetime) -> dict`
  (keys: `fired`, `pending`).

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_retro_service.py
"""Tests for weekly retro data gathering: triage/draft/reminder stats."""

from datetime import datetime, timedelta, timezone

from app.store.db import Category, Draft, DraftStatus, Email, Reminder, ReminderStatus, get_session

NOW = datetime.now(timezone.utc)
WEEK_AGO = NOW - timedelta(days=7)
TWO_WEEKS_AGO = NOW - timedelta(days=14)


def _make_email(category, created_at, **overrides):
    data = dict(account="main", message_id=f"m-{created_at.timestamp()}-{category}",
                sender="a@b.c", subject="s", category=category, created_at=created_at)
    data.update(overrides)
    return Email(**data)


class TestTriageStats:
    def test_counts_by_category_within_window(self, session_db):
        from app.tools.retro.service import triage_stats

        with get_session() as s:
            s.add(_make_email(Category.CRITICAL, NOW - timedelta(days=1)))
            s.add(_make_email(Category.NEEDS_REPLY, NOW - timedelta(days=2)))
            s.add(_make_email(Category.NEEDS_REPLY, NOW - timedelta(days=3)))
            s.add(_make_email(Category.FYI, TWO_WEEKS_AGO))  # outside window

        stats = triage_stats(WEEK_AGO)
        assert stats["critical"] == 1
        assert stats["needs_reply"] == 2
        assert stats["fyi"] == 0
        assert stats["skip"] == 0

    def test_all_categories_present_even_at_zero(self, session_db):
        from app.tools.retro.service import triage_stats

        stats = triage_stats(WEEK_AGO)
        assert set(stats.keys()) == {"critical", "needs_reply", "fyi", "skip"}
        assert all(v == 0 for v in stats.values())


class TestDraftActivity:
    def test_sent_counts_only_within_window(self, session_db):
        from app.tools.retro.service import draft_activity

        with get_session() as s:
            s.add(Draft(body="a", status=DraftStatus.SENT, sent_at=NOW - timedelta(days=1)))
            s.add(Draft(body="b", status=DraftStatus.SENT, sent_at=TWO_WEEKS_AGO))  # outside window

        stats = draft_activity(WEEK_AGO)
        assert stats["sent"] == 1

    def test_pending_counts_regardless_of_age(self, session_db):
        from app.tools.retro.service import draft_activity

        with get_session() as s:
            s.add(Draft(body="old", status=DraftStatus.PENDING, created_at=TWO_WEEKS_AGO))

        stats = draft_activity(WEEK_AGO)
        assert stats["pending"] == 1

    def test_discarded_counts_only_within_window_via_updated_at(self, session_db):
        from app.tools.retro.service import draft_activity

        with get_session() as s:
            s.add(Draft(body="a", status=DraftStatus.DISCARDED, updated_at=NOW - timedelta(days=1)))
            s.add(Draft(body="b", status=DraftStatus.DISCARDED, updated_at=TWO_WEEKS_AGO))

        stats = draft_activity(WEEK_AGO)
        assert stats["discarded"] == 1


class TestReminderStats:
    def test_fired_counts_only_within_window(self, session_db):
        from app.tools.retro.service import reminder_stats

        with get_session() as s:
            s.add(Reminder(text="a", fire_at=NOW, status=ReminderStatus.FIRED,
                            fired_at=NOW - timedelta(days=1)))
            s.add(Reminder(text="b", fire_at=NOW, status=ReminderStatus.FIRED,
                            fired_at=TWO_WEEKS_AGO))

        stats = reminder_stats(WEEK_AGO)
        assert stats["fired"] == 1

    def test_pending_is_a_live_snapshot_not_time_boxed(self, session_db):
        from app.tools.retro.service import reminder_stats

        with get_session() as s:
            s.add(Reminder(text="old", fire_at=NOW, status=ReminderStatus.PENDING,
                            created_at=TWO_WEEKS_AGO))

        stats = reminder_stats(WEEK_AGO)
        assert stats["pending"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd api && uv run pytest tests/test_retro_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.tools.retro'`

- [ ] **Step 3: Write the implementation**

```python
# api/app/tools/retro/__init__.py
```
(empty file)

```python
# api/app/tools/retro/service.py
"""Weekly retro data: triage, draft, and reminder stats — reads existing tables only,
no new schema. Workflow-run stats live in a separate function (see workflow_run_stats,
added in a later task) since it merges a second database."""

from datetime import datetime

from app.store.db import Category, Draft, DraftStatus, Email, Reminder, ReminderStatus, get_session


def triage_stats(since: datetime) -> dict[str, int]:
    """Count emails triaged (by created_at) since `since`, grouped by category. All four
    categories are always present in the result, even at zero, so callers/formatters don't
    need to guard against missing keys."""
    counts = {c.value: 0 for c in Category}
    with get_session() as s:
        rows = s.query(Email.category).filter(Email.created_at >= since).all()
    for (category,) in rows:
        counts[category] = counts.get(category, 0) + 1
    return counts


def draft_activity(since: datetime) -> dict:
    """Draft activity: sent since `since` (by sent_at), all currently-pending drafts
    regardless of age (an old unsent draft is more worth nudging about, not less — not
    time-boxed), and discarded since `since` — approximated via updated_at since there's
    no dedicated discarded_at column."""
    with get_session() as s:
        sent = s.query(Draft).filter(Draft.sent_at >= since).count()
        pending = s.query(Draft).filter(Draft.status == DraftStatus.PENDING).count()
        discarded = s.query(Draft).filter(
            Draft.status == DraftStatus.DISCARDED, Draft.updated_at >= since
        ).count()
    return {"sent": sent, "pending": pending, "discarded": discarded}


def reminder_stats(since: datetime) -> dict:
    """Reminders fired since `since` vs. current pending count (a live snapshot, not
    time-boxed — pending reminders aren't "new" or "old", they're just outstanding)."""
    with get_session() as s:
        fired = s.query(Reminder).filter(
            Reminder.status == ReminderStatus.FIRED, Reminder.fired_at >= since
        ).count()
        pending = s.query(Reminder).filter(Reminder.status == ReminderStatus.PENDING).count()
    return {"fired": fired, "pending": pending}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && uv run pytest tests/test_retro_service.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add api/app/tools/retro/__init__.py api/app/tools/retro/service.py api/tests/test_retro_service.py
git commit -m "feat(digest): add triage/draft/reminder stat gathering for weekly retro"
```

---

### Task 3: `tools/retro/service.py` — workflow-run stats + message assembly

**Files:**
- Modify: `api/app/tools/retro/service.py`
- Modify: `api/tests/test_retro_service.py`

**Interfaces:**
- Consumes: `RunLog`, `RunStatus`, `get_obs_session` from `app.store.observability`;
  `CodingRun`, `CodingStatus` from `app.store.db` (already imported in Task 2's file, add
  these two).
- Produces: `workflow_run_stats(since: datetime) -> dict[str, dict]` — each value shaped
  `{count, success, failure, degraded}`. `format_weekly_retro(triage: dict, drafts: dict,
  reminders: dict, workflows: dict) -> str`, consumed by Task 6's workflow.

- [ ] **Step 1: Write the failing tests**

Append to `api/tests/test_retro_service.py`:

```python
class TestWorkflowRunStats:
    def test_merges_runlog_and_codingrun_sources(self, session_db, obs_db):
        from app.store.db import CodingRun, CodingStatus, get_session
        from app.store.observability import RunLog, RunStatus, get_obs_session
        from app.tools.retro.service import workflow_run_stats

        with get_obs_session() as s:
            s.add(RunLog(kind="morning_digest", source="inngest", status=RunStatus.SUCCESS,
                          started_at=NOW - timedelta(days=1)))
            s.add(RunLog(kind="morning_digest", source="inngest", status=RunStatus.FAILURE,
                          started_at=NOW - timedelta(days=2)))
            s.add(RunLog(kind="morning_digest", source="inngest", status=RunStatus.SUCCESS,
                          started_at=TWO_WEEKS_AGO))  # outside window
            s.add(RunLog(kind="gmail_triage", source="scheduler", status=RunStatus.SUCCESS,
                          started_at=NOW - timedelta(days=1)))  # not source=inngest, excluded

        with get_session() as s:
            s.add(CodingRun(issue_url="u", repo="r", issue_number=1, status=CodingStatus.DONE,
                             created_at=NOW - timedelta(days=1)))
            s.add(CodingRun(issue_url="u", repo="r", issue_number=2, status=CodingStatus.FAILED,
                             created_at=TWO_WEEKS_AGO))  # outside window

        stats = workflow_run_stats(WEEK_AGO)
        assert stats["morning_digest"] == {"count": 2, "success": 1, "failure": 1, "degraded": 0}
        assert "gmail_triage" not in stats
        assert stats["code_issue"] == {"count": 1, "success": 1, "failure": 0, "degraded": 0}

    def test_no_runs_in_window_returns_empty(self, session_db, obs_db):
        from app.tools.retro.service import workflow_run_stats

        assert workflow_run_stats(WEEK_AGO) == {}


class TestFormatWeeklyRetro:
    def test_renders_all_four_sections(self):
        from app.tools.retro.service import format_weekly_retro

        text = format_weekly_retro(
            triage={"critical": 1, "needs_reply": 2, "fyi": 5, "skip": 3},
            drafts={"sent": 4, "pending": 2, "discarded": 1},
            reminders={"fired": 3, "pending": 5},
            workflows={"morning_digest": {"count": 7, "success": 6, "failure": 1, "degraded": 0}},
        )
        assert "1 critical" in text
        assert "2 needs reply" in text
        assert "4 sent" in text
        assert "2 still pending" in text
        assert "3 fired" in text
        assert "morning_digest: 7 runs" in text

    def test_no_workflow_runs_renders_none(self):
        from app.tools.retro.service import format_weekly_retro

        text = format_weekly_retro(
            triage={"critical": 0, "needs_reply": 0, "fyi": 0, "skip": 0},
            drafts={"sent": 0, "pending": 0, "discarded": 0},
            reminders={"fired": 0, "pending": 0},
            workflows={},
        )
        assert "none this week" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd api && uv run pytest tests/test_retro_service.py::TestWorkflowRunStats tests/test_retro_service.py::TestFormatWeeklyRetro -v`
Expected: FAIL with `ImportError` (both functions don't exist yet)

- [ ] **Step 3: Write the implementation**

In `api/app/tools/retro/service.py`, change the top imports to:

```python
from datetime import datetime

from app.store.db import (
    Category, CodingRun, CodingStatus, Draft, DraftStatus, Email, Reminder, ReminderStatus,
    get_session,
)
```

Then append:

```python
def workflow_run_stats(since: datetime) -> dict[str, dict]:
    """Merge two sources of workflow-run tracking: RunLog (observability DB) for
    workflows with no dedicated table, and CodingRun (main DB) for code_issue, which
    deliberately tracks its own lifecycle there instead — see workflows/code_issue.py's
    module docstring. Never raises; an empty result just means nothing ran this window."""
    from app.store.observability import RunLog, RunStatus, get_obs_session

    stats: dict[str, dict] = {}

    def _bump(kind: str, is_success: bool, is_failure: bool) -> None:
        entry = stats.setdefault(kind, {"count": 0, "success": 0, "failure": 0, "degraded": 0})
        entry["count"] += 1
        if is_success:
            entry["success"] += 1
        elif is_failure:
            entry["failure"] += 1
        else:
            entry["degraded"] += 1

    with get_obs_session() as s:
        rows = s.query(RunLog.kind, RunLog.status).filter(
            RunLog.source == "inngest", RunLog.started_at >= since
        ).all()
    for kind, status in rows:
        _bump(kind, status == RunStatus.SUCCESS, status == RunStatus.FAILURE)

    with get_session() as s:
        rows = s.query(CodingRun.status).filter(CodingRun.created_at >= since).all()
    for (status,) in rows:
        # RUNNING/REVIEW/BLOCKED aren't clean success or hard failure — the "degraded"
        # bucket doubles as "not finished cleanly" here, same as it does for RunLog rows.
        _bump("code_issue", status == CodingStatus.DONE, status == CodingStatus.FAILED)

    return stats


def format_weekly_retro(triage: dict, drafts: dict, reminders: dict, workflows: dict) -> str:
    """Assemble the four sections into one Telegram message."""
    lines = ["📊 Weekly retro", ""]

    lines.append("📧 Email triage")
    lines.append(f"  {triage['critical']} critical · {triage['needs_reply']} needs reply · "
                 f"{triage['fyi']} fyi · {triage['skip']} skip")
    lines.append("")

    lines.append("✉️ Drafts")
    lines.append(f"  {drafts['sent']} sent · {drafts['pending']} still pending · "
                 f"{drafts['discarded']} discarded")
    lines.append("")

    lines.append("⏰ Reminders")
    lines.append(f"  {reminders['fired']} fired · {reminders['pending']} pending")
    lines.append("")

    lines.append("⚙️ Workflow runs")
    if workflows:
        for kind, stat in sorted(workflows.items()):
            lines.append(f"  {kind}: {stat['count']} runs ({stat['success']} success, "
                         f"{stat['failure']} failure, {stat['degraded']} degraded)")
    else:
        lines.append("  none this week")

    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && uv run pytest tests/test_retro_service.py -v`
Expected: PASS (13 tests total)

- [ ] **Step 5: Commit**

```bash
git add api/app/tools/retro/service.py api/tests/test_retro_service.py
git commit -m "feat(digest): add workflow-run stats and weekly retro message assembly"
```

---

### Task 4: `workflows/daily_calendar_brief.py`

**Files:**
- Create: `api/app/workflows/daily_calendar_brief.py`
- Modify: `api/app/workflows/registry.py`
- Create: `api/tests/test_daily_calendar_brief_workflow.py`

**Interfaces:**
- Consumes: `load_accounts` (`tools/calendar/client.py`), `list_events_for_range` +
  `format_daily_brief` (`tools/calendar/service.py`, Task 1), `notify` (`workflows/lib.py`),
  `record_run` (`observability/sink.py`).
- Produces: `daily_calendar_brief` — an Inngest function, registered in
  `WORKFLOW_FUNCTIONS`.

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_daily_calendar_brief_workflow.py
def test_workflow_imports_without_inngest_server_or_token():
    from app.workflows.daily_calendar_brief import daily_calendar_brief
    assert daily_calendar_brief is not None


def test_workflow_registered():
    from app.workflows.daily_calendar_brief import daily_calendar_brief
    from app.workflows.registry import WORKFLOW_FUNCTIONS
    assert daily_calendar_brief in WORKFLOW_FUNCTIONS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd api && uv run pytest tests/test_daily_calendar_brief_workflow.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.workflows.daily_calendar_brief'`

- [ ] **Step 3: Write the implementation**

```python
# api/app/workflows/daily_calendar_brief.py
"""Daily calendar brief: today's merged agenda across all accounts → Telegram."""

import inngest

from app.workflows.client import inngest_client
from app.workflows.lib import notify


@inngest_client.create_function(
    fn_id="daily-calendar-brief",
    trigger=[
        inngest.TriggerEvent(event="workflows/daily-calendar-brief.requested"),
        inngest.TriggerCron(cron="30 8 * * *"),
    ],
    retries=2,
)
async def daily_calendar_brief(ctx: inngest.Context) -> str:
    async def fetch_and_format() -> str:
        import asyncio
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        from app.config import get_settings
        from app.observability.sink import record_run
        from app.tools.calendar.client import load_accounts
        from app.tools.calendar.service import format_daily_brief, list_events_for_range

        settings = get_settings()
        zone = ZoneInfo(settings.timezone)
        today = datetime.now(zone).date()
        time_min = datetime.combine(today, datetime.min.time(), tzinfo=zone)
        time_max = datetime.combine(today + timedelta(days=1), datetime.min.time(), tzinfo=zone)

        with record_run("daily_calendar_brief", source="inngest") as run:
            accounts = load_accounts(settings)
            events, errors = await asyncio.to_thread(
                list_events_for_range, accounts, time_min, time_max, settings.timezone
            )
            text = format_daily_brief(events, errors, today)
            if errors:
                run.degrade(summary=f"{len(events)} events, {len(errors)} accounts failed")
            else:
                run.summary = f"{len(events)} events"
            return text

    text = await ctx.step.run("fetch-and-format", fetch_and_format)

    async def send() -> str:
        await notify(text)
        return "sent"

    return await ctx.step.run("notify", send)
```

In `api/app/workflows/registry.py`, replace the full file with:

```python
"""All workflow functions, handed to inngest.fast_api.serve()."""

from app.workflows.code_issue import code_issue
from app.workflows.daily_calendar_brief import daily_calendar_brief
from app.workflows.hello import hello
from app.workflows.morning_digest import morning_digest

WORKFLOW_FUNCTIONS = [hello, morning_digest, code_issue, daily_calendar_brief]
```

(Task 6 will add `weekly_retro` to this same list — don't add it here yet, to keep this
task's diff scoped to exactly what it introduces.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && uv run pytest tests/test_daily_calendar_brief_workflow.py -v`
Expected: PASS (2 tests)

Then run the full suite: `cd api && uv run pytest -v` — expect all green, no regressions.

- [ ] **Step 5: Commit**

```bash
git add api/app/workflows/daily_calendar_brief.py api/app/workflows/registry.py api/tests/test_daily_calendar_brief_workflow.py
git commit -m "feat(digest): add daily calendar brief workflow"
```

---

### Task 5: Instrument `morning_digest.py` with `record_run`

**Files:**
- Modify: `api/app/workflows/morning_digest.py`
- Create: `api/tests/test_morning_digest_workflow.py`

**Interfaces:**
- Consumes: `record_run` (`observability/sink.py`).
- Produces: no new public interface — `morning_digest` now writes a `RunLog` row
  (`kind="morning_digest", source="inngest"`) each run, which Task 3's
  `workflow_run_stats` reads.

- [ ] **Step 1: Write the failing test**

```python
# api/tests/test_morning_digest_workflow.py
def test_workflow_imports_without_inngest_server_or_token():
    from app.workflows.morning_digest import morning_digest
    assert morning_digest is not None


def test_workflow_registered():
    from app.workflows.morning_digest import morning_digest
    from app.workflows.registry import WORKFLOW_FUNCTIONS
    assert morning_digest in WORKFLOW_FUNCTIONS
```

(This file had zero test coverage before this task — these two are the same minimal
import/registration pair every other workflow file already has, per
`test_code_issue_workflow_import.py`.)

- [ ] **Step 2: Run test to verify it currently passes (sanity check, not a red step)**

Run: `cd api && uv run pytest tests/test_morning_digest_workflow.py -v`
Expected: PASS — `morning_digest` already exists and is already registered; this task adds
*instrumentation*, not new importable surface, so there's no red step here. Proceed
directly to the implementation change.

- [ ] **Step 3: Write the implementation**

In `api/app/workflows/morning_digest.py`, replace the `summarize` step:

```python
    async def summarize() -> str:
        return await llm(
            "chat",
            "Summarize these Hacker News stories in <=8 short bullet lines for a "
            f"busy engineer. Keep URLs for the 3 most interesting.\n\n{stories}",
        )

    summary = await ctx.step.run("summarize", summarize)
```

with:

```python
    async def summarize() -> str:
        from app.observability.sink import record_run

        with record_run("morning_digest", source="inngest") as run:
            text = await llm(
                "chat",
                "Summarize these Hacker News stories in <=8 short bullet lines for a "
                f"busy engineer. Keep URLs for the 3 most interesting.\n\n{stories}",
            )
            run.summary = "summarized"
            return text

    summary = await ctx.step.run("summarize", summarize)
```

- [ ] **Step 4: Run tests to verify they still pass**

Run: `cd api && uv run pytest tests/test_morning_digest_workflow.py -v`
Expected: PASS (2 tests)

Then run the full suite: `cd api && uv run pytest -v` — expect all green, no regressions.

- [ ] **Step 5: Commit**

```bash
git add api/app/workflows/morning_digest.py api/tests/test_morning_digest_workflow.py
git commit -m "feat(digest): instrument morning_digest with record_run for weekly retro counts"
```

---

### Task 6: `workflows/weekly_retro.py`

**Files:**
- Create: `api/app/workflows/weekly_retro.py`
- Modify: `api/app/workflows/registry.py`
- Create: `api/tests/test_weekly_retro_workflow.py`

**Interfaces:**
- Consumes: `triage_stats`, `draft_activity`, `reminder_stats`, `workflow_run_stats`,
  `format_weekly_retro` (`tools/retro/service.py`, Tasks 2-3), `notify` (`workflows/lib.py`),
  `record_run` (`observability/sink.py`).
- Produces: `weekly_retro` — an Inngest function, registered in `WORKFLOW_FUNCTIONS`.

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_weekly_retro_workflow.py
def test_workflow_imports_without_inngest_server_or_token():
    from app.workflows.weekly_retro import weekly_retro
    assert weekly_retro is not None


def test_workflow_registered():
    from app.workflows.registry import WORKFLOW_FUNCTIONS
    from app.workflows.weekly_retro import weekly_retro
    assert weekly_retro in WORKFLOW_FUNCTIONS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd api && uv run pytest tests/test_weekly_retro_workflow.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.workflows.weekly_retro'`

- [ ] **Step 3: Write the implementation**

```python
# api/app/workflows/weekly_retro.py
"""Weekly retro: triage/draft/reminder/workflow-run stats for the past 7 days → Telegram."""

import inngest

from app.workflows.client import inngest_client
from app.workflows.lib import notify


@inngest_client.create_function(
    fn_id="weekly-retro",
    trigger=[
        inngest.TriggerEvent(event="workflows/weekly-retro.requested"),
        inngest.TriggerCron(cron="0 18 * * 0"),
    ],
    retries=2,
)
async def weekly_retro(ctx: inngest.Context) -> str:
    async def gather_and_format() -> str:
        from datetime import datetime, timedelta, timezone

        from app.observability.sink import record_run
        from app.tools.retro.service import (
            draft_activity, format_weekly_retro, reminder_stats, triage_stats, workflow_run_stats,
        )

        since = datetime.now(timezone.utc) - timedelta(days=7)

        with record_run("weekly_retro", source="inngest") as run:
            triage = triage_stats(since)
            drafts = draft_activity(since)
            reminders = reminder_stats(since)
            workflows = workflow_run_stats(since)
            run.summary = "weekly retro compiled"
            return format_weekly_retro(triage, drafts, reminders, workflows)

    text = await ctx.step.run("gather-and-format", gather_and_format)

    async def send() -> str:
        await notify(text)
        return "sent"

    return await ctx.step.run("notify", send)
```

In `api/app/workflows/registry.py`, replace the full file with:

```python
"""All workflow functions, handed to inngest.fast_api.serve()."""

from app.workflows.code_issue import code_issue
from app.workflows.daily_calendar_brief import daily_calendar_brief
from app.workflows.hello import hello
from app.workflows.morning_digest import morning_digest
from app.workflows.weekly_retro import weekly_retro

WORKFLOW_FUNCTIONS = [hello, morning_digest, code_issue, daily_calendar_brief, weekly_retro]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && uv run pytest tests/test_weekly_retro_workflow.py -v`
Expected: PASS (2 tests)

Then run the full suite: `cd api && uv run pytest -v` — expect all green, no regressions.

- [ ] **Step 5: Commit**

```bash
git add api/app/workflows/weekly_retro.py api/app/workflows/registry.py api/tests/test_weekly_retro_workflow.py
git commit -m "feat(digest): add weekly retro workflow"
```

---

### Task 7: Docs — `TODO.md`

**Files:**
- Modify: `TODO.md`

- [ ] **Step 1: Update `TODO.md`**

Find the "Iteration 4 — More tools" section (where the now-completed Calendar bullet
lives) and add a new bullet immediately after the Calendar v1 entry:

```markdown
- [x] **Digest synthesis — morning brief + weekly retro** (`tools/retro/`,
      `workflows/daily_calendar_brief.py`, `workflows/weekly_retro.py`): a daily
      calendar-only agenda (8:30am) and a Sunday-evening retro covering triage stats,
      draft activity, reminders, and workflow-run counts. Spec:
      `docs/superpowers/specs/2026-07-26-digest-synthesis-design.md`.
  - [ ] **Cross-source synthesis V2** (remaining backlog): meeting prep packets
        (match a calendar event to its related email thread); conflict-aware drafting
        (detect double-bookings across accounts, draft a decline/reschedule for
        approval — must go through the existing HITL send-gate, never auto-send).
```

- [ ] **Step 2: Commit**

```bash
git add TODO.md
git commit -m "docs: record digest synthesis as shipped, note remaining cross-source backlog"
```
