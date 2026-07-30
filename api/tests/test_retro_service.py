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
