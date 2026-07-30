"""Tests for weekly retro data gathering: triage/draft/reminder stats."""

from datetime import datetime, timedelta, timezone

from app.store.db import Category, Draft, DraftStatus, Email, Reminder, ReminderStatus, get_session
from tests.test_observability import obs_db  # noqa: F401 — reuse the obs-DB fixture

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
            s.commit()  # get_obs_session() does not auto-commit (unlike get_session())

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
