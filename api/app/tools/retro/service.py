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
