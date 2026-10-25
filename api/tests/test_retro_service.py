"""Tests for weekly retro data gathering: triage/draft/reminder stats."""

from datetime import datetime, timedelta, timezone

from app.store.db import (
    Category, CodingRun, CodingStatus, Draft, DraftStatus, Email, Reminder, ReminderStatus,
    get_session,
)
from app.store.observability import RunLog, RunStatus, get_obs_session
from app.tools.retro.service import (
    draft_activity, format_weekly_retro, reminder_stats, triage_stats, workflow_run_stats,
)

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
        stats = triage_stats(WEEK_AGO)
        assert set(stats.keys()) == {"critical", "needs_reply", "fyi", "skip", "quarantined"}
        assert all(v == 0 for v in stats.values())

    def test_quarantined_emails_are_counted_apart_from_skip(self, session_db):
        with get_session() as s:
            s.add(_make_email(Category.SKIP, NOW - timedelta(days=1)))
            s.add(_make_email(Category.SKIP, NOW - timedelta(days=2), suspicious=True))

        stats = triage_stats(WEEK_AGO)
        assert stats["skip"] == 1
        assert stats["quarantined"] == 1


class TestDraftActivity:
    def test_sent_counts_only_within_window(self, session_db):
        with get_session() as s:
            s.add(Draft(body="a", status=DraftStatus.SENT, sent_at=NOW - timedelta(days=1)))
            s.add(Draft(body="b", status=DraftStatus.SENT, sent_at=TWO_WEEKS_AGO))  # outside window

        stats = draft_activity(WEEK_AGO)
        assert stats["sent"] == 1

    def test_pending_counts_regardless_of_age(self, session_db):
        with get_session() as s:
            s.add(Draft(body="old", status=DraftStatus.PENDING, created_at=TWO_WEEKS_AGO))

        stats = draft_activity(WEEK_AGO)
        assert stats["pending"] == 1

    def test_discarded_counts_only_within_window_via_updated_at(self, session_db):
        with get_session() as s:
            s.add(Draft(body="a", status=DraftStatus.DISCARDED, updated_at=NOW - timedelta(days=1)))
            s.add(Draft(body="b", status=DraftStatus.DISCARDED, updated_at=TWO_WEEKS_AGO))

        stats = draft_activity(WEEK_AGO)
        assert stats["discarded"] == 1


class TestReminderStats:
    def test_fired_counts_only_within_window(self, session_db):
        with get_session() as s:
            s.add(Reminder(text="a", fire_at=NOW, status=ReminderStatus.FIRED,
                            fired_at=NOW - timedelta(days=1)))
            s.add(Reminder(text="b", fire_at=NOW, status=ReminderStatus.FIRED,
                            fired_at=TWO_WEEKS_AGO))

        stats = reminder_stats(WEEK_AGO)
        assert stats["fired"] == 1

    def test_pending_is_a_live_snapshot_not_time_boxed(self, session_db):
        with get_session() as s:
            s.add(Reminder(text="old", fire_at=NOW, status=ReminderStatus.PENDING,
                            created_at=TWO_WEEKS_AGO))

        stats = reminder_stats(WEEK_AGO)
        assert stats["pending"] == 1

    def test_recurring_reminder_counts_as_fired_despite_staying_pending(self, session_db):
        """Recurring reminders (recurrence_cron set) never flip to FIRED — the
        fire-reminder job only sets status=FIRED for one-time reminders — so "fired"
        must be counted by fired_at alone, with no status predicate."""
        with get_session() as s:
            s.add(Reminder(text="a", fire_at=NOW, recurrence_cron="0 9 * * *",
                            status=ReminderStatus.PENDING, fired_at=NOW - timedelta(days=1)))

        stats = reminder_stats(WEEK_AGO)
        assert stats["fired"] == 1


class TestWorkflowRunStats:
    def test_merges_runlog_and_codingrun_sources(self, session_db, obs_db):
        with get_obs_session() as s:
            s.add(RunLog(kind="morning_digest", source="inngest", status=RunStatus.SUCCESS,
                          started_at=NOW - timedelta(days=1)))
            s.add(RunLog(kind="morning_digest", source="inngest", status=RunStatus.FAILURE,
                          started_at=NOW - timedelta(days=2)))
            s.add(RunLog(kind="morning_digest", source="inngest", status=RunStatus.SUCCESS,
                          started_at=TWO_WEEKS_AGO))  # outside window
            s.add(RunLog(kind="morning_digest", source="manual", status=RunStatus.SUCCESS,
                          started_at=NOW - timedelta(days=1)))  # not source=inngest, excluded
            s.add(RunLog(kind="gmail_triage", source="inngest", status=RunStatus.SUCCESS,
                          started_at=NOW - timedelta(days=1)))  # not a workflow kind, excluded
            s.commit()  # get_obs_session() does not auto-commit (unlike get_session())

        with get_session() as s:
            s.add(CodingRun(issue_url="u", repo="r", issue_number=1, status=CodingStatus.DONE,
                             created_at=NOW - timedelta(days=1), updated_at=NOW - timedelta(days=1)))
            s.add(CodingRun(issue_url="u", repo="r", issue_number=2, status=CodingStatus.FAILED,
                             created_at=TWO_WEEKS_AGO, updated_at=TWO_WEEKS_AGO))  # outside window

        stats = workflow_run_stats(WEEK_AGO)
        assert stats["morning_digest"] == {"count": 2, "success": 1, "failure": 1, "degraded": 0}
        assert "gmail_triage" not in stats
        assert stats["code_issue"] == {"count": 1, "success": 1, "failure": 0, "degraded": 0}

    def test_no_runs_in_window_returns_empty(self, session_db, obs_db):
        assert workflow_run_stats(WEEK_AGO) == {}

    def test_excludes_code_issue_internal_sub_runs(self, session_db, obs_db):
        """code_issue's internal "coder"/"code_review" steps record their own RunLog
        rows via record_run, but they aren't top-level workflows — they're code_issue's
        implementation detail, already counted separately via CodingRun. They must not
        leak through as their own bogus top-level entries."""
        with get_obs_session() as s:
            s.add(RunLog(kind="coder", source="inngest", status=RunStatus.SUCCESS,
                          started_at=NOW - timedelta(days=1)))
            s.add(RunLog(kind="code_review", source="inngest", status=RunStatus.SUCCESS,
                          started_at=NOW - timedelta(days=1)))
            s.commit()

        stats = workflow_run_stats(WEEK_AGO)
        assert "coder" not in stats
        assert "code_review" not in stats

    def test_excludes_own_in_flight_run_from_degraded(self, session_db, obs_db):
        """A workflow's own still-RUNNING RunLog row (e.g. weekly_retro calling this
        function from inside its own record_run block) must never count itself as
        "degraded" — RUNNING rows should be excluded entirely, not bucketed at all."""
        with get_obs_session() as s:
            s.add(RunLog(kind="weekly_retro", source="inngest", status=RunStatus.RUNNING,
                          started_at=NOW - timedelta(days=1)))
            s.commit()

        stats = workflow_run_stats(WEEK_AGO)
        assert "weekly_retro" not in stats

    def test_retried_attempts_of_one_inngest_run_count_once_with_the_latest_status(
        self, session_db, obs_db
    ):
        """Each Inngest retry opens its own RunLog row; rows sharing the Inngest run id
        (external_id) are one run, and the last attempt decides its status."""
        with get_obs_session() as s:
            day = NOW - timedelta(days=1)
            s.add(RunLog(kind="morning_digest", source="inngest", status=RunStatus.FAILURE,
                          external_id="run-a", started_at=day))
            s.add(RunLog(kind="morning_digest", source="inngest", status=RunStatus.SUCCESS,
                          external_id="run-a", started_at=day))  # retry fixed it
            s.add(RunLog(kind="morning_digest", source="inngest", status=RunStatus.SUCCESS,
                          external_id="run-b", started_at=day))
            s.add(RunLog(kind="morning_digest", source="inngest", status=RunStatus.FAILURE,
                          external_id="run-b", started_at=day))  # e.g. record_failure's row
            s.add(RunLog(kind="morning_digest", source="inngest", status=RunStatus.DEGRADED,
                          started_at=day))  # no external_id: counted on its own
            s.add(RunLog(kind="daily_calendar_brief", source="inngest",
                          status=RunStatus.INTERRUPTED, external_id="run-c", started_at=day))
            s.commit()

        stats = workflow_run_stats(WEEK_AGO)
        assert stats["morning_digest"] == {"count": 3, "success": 1, "failure": 1, "degraded": 1}
        assert stats["daily_calendar_brief"] == {"count": 1, "success": 0, "failure": 1, "degraded": 0}

    def test_coding_runs_map_final_states_and_skip_ones_still_in_flight(self, session_db, obs_db):
        hour_ago, stale = NOW - timedelta(hours=1), NOW - timedelta(hours=30)
        with get_session() as s:
            for number, status, updated in [
                (1, CodingStatus.DONE, hour_ago), (2, CodingStatus.BLOCKED, hour_ago),
                (3, CodingStatus.FAILED, hour_ago),
                (4, CodingStatus.RUNNING, hour_ago),  # in flight: not counted yet
                (5, CodingStatus.RUNNING, stale),  # died without a final state
                (6, CodingStatus.REVIEW, stale),
                (7, CodingStatus.DONE, TWO_WEEKS_AGO),  # settled before the window
            ]:
                s.add(CodingRun(issue_url="u", repo="r", issue_number=number, status=status,
                                created_at=TWO_WEEKS_AGO, updated_at=updated))

        stats = workflow_run_stats(WEEK_AGO, now=NOW)
        assert stats["code_issue"] == {"count": 5, "success": 1, "failure": 3, "degraded": 1}

    def test_a_coding_run_in_flight_at_retro_time_is_counted_the_next_week(self, session_db, obs_db):
        """A run that dies the evening before a retro is "in flight" for that retro; it must
        land in the following week's retro, not fall between the two windows."""
        retro = NOW
        with get_session() as s:
            s.add(CodingRun(issue_url="u", repo="r", issue_number=1, status=CodingStatus.RUNNING,
                            created_at=retro - timedelta(hours=22),
                            updated_at=retro - timedelta(hours=21)))

        this_week = workflow_run_stats(retro - timedelta(days=7), now=retro)
        next_week = workflow_run_stats(retro, now=retro + timedelta(days=7))
        assert "code_issue" not in this_week
        assert next_week["code_issue"] == {"count": 1, "success": 0, "failure": 1, "degraded": 0}

    def test_a_coding_run_finished_this_week_counts_even_if_started_earlier(self, session_db, obs_db):
        with get_session() as s:
            s.add(CodingRun(issue_url="u", repo="r", issue_number=1, status=CodingStatus.DONE,
                            created_at=WEEK_AGO - timedelta(hours=2),
                            updated_at=NOW - timedelta(days=6)))

        stats = workflow_run_stats(WEEK_AGO, now=NOW)
        assert stats["code_issue"]["success"] == 1

    def test_unreadable_observability_db_returns_none(self, session_db, obs_db, monkeypatch):
        import app.tools.retro.service as retro

        def broken():
            raise RuntimeError("database is locked")

        monkeypatch.setattr(retro, "get_obs_session", broken)
        assert workflow_run_stats(WEEK_AGO) is None


class TestCompileWeeklyRetro:
    def test_survives_an_unreadable_observability_db(self, session_db, obs_db, monkeypatch):
        import app.tools.retro.service as retro

        with get_session() as s:
            s.add(_make_email(Category.CRITICAL, NOW - timedelta(days=1)))

        def broken():
            raise RuntimeError("database is locked")

        monkeypatch.setattr(retro, "get_obs_session", broken)
        text = retro.compile_weekly_retro(WEEK_AGO)
        assert "1 critical" in text
        assert "unavailable (couldn't read run history)" in text


class TestFormatWeeklyRetro:
    def test_renders_all_four_sections(self):
        text = format_weekly_retro(
            triage={"critical": 1, "needs_reply": 2, "fyi": 5, "skip": 3, "quarantined": 0},
            drafts={"sent": 4, "pending": 2, "discarded": 1},
            reminders={"fired": 3, "pending": 5},
            workflows={"morning_digest": {"count": 7, "success": 6, "failure": 1, "degraded": 0}},
        )
        assert "  1 critical · 2 needs reply · 5 fyi · 3 skip\n" in text
        assert "  4 sent · 2 still pending · 1 discarded\n" in text
        assert "  3 fired · 5 pending\n" in text
        assert "  morning_digest: 7 runs (6 success, 1 failure, 0 degraded)" in text
        assert "quarantined" not in text

    def test_quarantined_count_is_flagged(self):
        text = format_weekly_retro(
            triage={"critical": 0, "needs_reply": 0, "fyi": 0, "skip": 1, "quarantined": 2},
            drafts={"sent": 0, "pending": 0, "discarded": 0},
            reminders={"fired": 0, "pending": 0},
            workflows={},
        )
        assert "1 skip · ⚠ 2 quarantined" in text

    def test_unreadable_run_history_says_so(self):
        text = format_weekly_retro(
            triage={"critical": 0, "needs_reply": 0, "fyi": 0, "skip": 0},
            drafts={"sent": 0, "pending": 0, "discarded": 0},
            reminders={"fired": 0, "pending": 0},
            workflows=None,
        )
        assert "unavailable (couldn't read run history)" in text
        assert "none this week" not in text

    def test_no_workflow_runs_renders_none(self):
        text = format_weekly_retro(
            triage={"critical": 0, "needs_reply": 0, "fyi": 0, "skip": 0},
            drafts={"sent": 0, "pending": 0, "discarded": 0},
            reminders={"fired": 0, "pending": 0},
            workflows={},
        )
        assert "none this week" in text
