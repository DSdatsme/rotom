"""Weekly retro data: triage, draft, reminder, and workflow-run stats — reads existing
tables only, no new schema."""

from datetime import datetime

from app.store.db import (
    Category, CodingRun, CodingStatus, Draft, DraftStatus, Email, Reminder, ReminderStatus,
    get_session,
)


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
    time-boxed — pending reminders aren't "new" or "old", they're just outstanding).

    "Fired" is counted by `fired_at >= since` alone, with no status predicate — matching
    the spec exactly. A recurring reminder (`recurrence_cron` set) never flips to FIRED;
    it stays PENDING forever and only has `fired_at` bumped on each fire (see
    `scheduler/jobs.py`'s fire-reminder job), so filtering on status would silently drop
    every recurring reminder from this count. This still undercounts a recurring reminder
    that fires more than once within the window, since `fired_at` is a single column
    overwritten on each fire rather than an audit log — a known, accepted limitation of
    the spec's chosen design, not something to fix here."""
    with get_session() as s:
        fired = s.query(Reminder).filter(Reminder.fired_at >= since).count()
        pending = s.query(Reminder).filter(Reminder.status == ReminderStatus.PENDING).count()
    return {"fired": fired, "pending": pending}


# Real top-level workflow kinds: Inngest functions that call `record_run` on themselves.
# An allowlist, not a denylist, so any future workflow that adds internal `record_run`
# sub-steps (like code_issue's "coder"/"code_review") doesn't leak through as a bogus
# top-level entry — see workflow_run_stats.
_TOP_LEVEL_WORKFLOW_KINDS = {"morning_digest", "daily_calendar_brief", "weekly_retro"}


def workflow_run_stats(since: datetime) -> dict[str, dict]:
    """Merge two sources of workflow-run tracking: RunLog (observability DB) for
    workflows with no dedicated table, and CodingRun (main DB) for code_issue, which
    deliberately tracks its own lifecycle there instead — see workflows/code_issue.py's
    module docstring. Never raises; an empty result just means nothing ran this window.

    The RunLog query is restricted to `_TOP_LEVEL_WORKFLOW_KINDS` (excludes code_issue's
    internal "coder"/"code_review" sub-runs, which would otherwise double-count code_issue
    and show up as bogus top-level entries) and excludes RunStatus.RUNNING rows (a
    workflow's own still-in-flight RunLog row — e.g. weekly_retro calls this function from
    inside its own `record_run` block — must not count itself as "degraded")."""
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
            RunLog.source == "inngest",
            RunLog.started_at >= since,
            RunLog.kind.in_(_TOP_LEVEL_WORKFLOW_KINDS),
            RunLog.status != RunStatus.RUNNING,
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
