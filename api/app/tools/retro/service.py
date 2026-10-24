"""Weekly retro data: triage, draft, reminder, and workflow-run stats — reads existing
tables only, no new schema."""

import logging
from datetime import datetime, timedelta, timezone

from app.store.db import (
    Category, CodingRun, CodingStatus, Draft, DraftStatus, Email, Reminder, ReminderStatus,
    get_session,
)
from app.store.observability import RunLog, RunStatus, get_obs_session

logger = logging.getLogger(__name__)


def triage_stats(since: datetime) -> dict[str, int]:
    """Count emails triaged (by created_at) since `since`, grouped by category, plus
    "quarantined": emails flagged as suspected prompt injection. Those are stored as
    category=skip with suspicious=True; they're counted on their own, not as skip, because
    the weekly view is where a run of them should stand out. All keys are always present,
    even at zero, so callers/formatters don't need to guard against missing keys."""
    counts = {c.value: 0 for c in Category}
    counts["quarantined"] = 0
    with get_session() as s:
        rows = s.query(Email.category, Email.suspicious).filter(Email.created_at >= since).all()
    for category, suspicious in rows:
        key = "quarantined" if suspicious else category
        counts[key] = counts.get(key, 0) + 1
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

# RunLog status → retro bucket. INTERRUPTED (the process died mid-run) is a failure.
_RUN_BUCKETS = {
    RunStatus.SUCCESS: "success",
    RunStatus.DEGRADED: "degraded",
    RunStatus.FAILURE: "failure",
    RunStatus.INTERRUPTED: "failure",
}

# A coding run still RUNNING/REVIEW this long after its last update never reached a final
# state (nothing writes CodingStatus.FAILED when a step exhausts its retries), so it counts
# as a failure; a more recent one is still in flight and isn't counted yet.
CODING_RUN_STALE_AFTER = timedelta(hours=24)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def workflow_run_stats(since: datetime, *, now: datetime | None = None) -> dict[str, dict] | None:
    """Merge two sources of workflow-run tracking: RunLog (observability DB) for
    workflows with no dedicated table, and CodingRun (main DB) for code_issue, which
    deliberately tracks its own lifecycle there instead — see workflows/code_issue.py's
    module docstring. An empty result means nothing ran this window; None means the
    observability DB couldn't be read (logged), so the caller can say so instead of
    losing the whole retro.

    RunLog rows are restricted to `_TOP_LEVEL_WORKFLOW_KINDS` (code_issue's internal
    "coder"/"code_review" sub-runs would otherwise double-count it). Each retried attempt
    of an Inngest run writes its own row, so rows sharing an external_id (the Inngest run
    id) collapse to one run whose status is the latest row's; rows without one count
    individually. A run whose latest row is still RUNNING is in flight — e.g. the
    weekly_retro run calling this — and isn't counted."""
    now = now or datetime.now(timezone.utc)
    stats: dict[str, dict] = {}

    def _bump(kind: str, bucket: str) -> None:
        entry = stats.setdefault(kind, {"count": 0, "success": 0, "failure": 0, "degraded": 0})
        entry["count"] += 1
        entry[bucket] += 1

    try:
        with get_obs_session() as s:
            rows = s.query(RunLog.id, RunLog.kind, RunLog.external_id, RunLog.status).filter(
                RunLog.source == "inngest",
                RunLog.started_at >= since,
                RunLog.kind.in_(_TOP_LEVEL_WORKFLOW_KINDS),
            ).order_by(RunLog.id).all()
    except Exception:
        logger.exception("Weekly retro: couldn't read workflow runs from the observability DB")
        return None
    latest: dict[tuple[str, str], str] = {}
    for row_id, kind, external_id, status in rows:
        latest[(kind, external_id or f"row:{row_id}")] = status  # ordered by id: last wins
    for (kind, _), status in latest.items():
        if status != RunStatus.RUNNING:
            _bump(kind, _RUN_BUCKETS.get(status, "failure"))

    with get_session() as s:
        rows = s.query(CodingRun.status, CodingRun.updated_at).filter(
            CodingRun.created_at >= since
        ).all()
    for status, updated_at in rows:
        if status == CodingStatus.DONE:
            _bump("code_issue", "success")
        elif status == CodingStatus.BLOCKED:
            _bump("code_issue", "degraded")  # PR open, CI still red after the fix rounds
        elif status == CodingStatus.FAILED:
            _bump("code_issue", "failure")
        else:  # RUNNING / REVIEW: in flight, or died before reaching a final state
            updated = _as_utc(updated_at)
            if updated is None or updated < now - CODING_RUN_STALE_AFTER:
                _bump("code_issue", "failure")

    return stats


def compile_weekly_retro(since: datetime) -> str:
    """Gather every section and format the message. Sync (plain DB reads): the workflow
    runs it with asyncio.to_thread."""
    return format_weekly_retro(
        triage_stats(since), draft_activity(since), reminder_stats(since), workflow_run_stats(since)
    )


def format_weekly_retro(
    triage: dict, drafts: dict, reminders: dict, workflows: dict | None
) -> str:
    """Assemble the four sections into one Telegram message. `workflows` is None when the
    run history couldn't be read."""
    lines = ["📊 Weekly retro", ""]

    lines.append("📧 Email triage")
    line = (f"  {triage['critical']} critical · {triage['needs_reply']} needs reply · "
            f"{triage['fyi']} fyi · {triage['skip']} skip")
    if triage.get("quarantined"):
        line += f" · ⚠ {triage['quarantined']} quarantined"
    lines.append(line)
    lines.append("")

    lines.append("✉️ Drafts")
    lines.append(f"  {drafts['sent']} sent · {drafts['pending']} still pending · "
                 f"{drafts['discarded']} discarded")
    lines.append("")

    lines.append("⏰ Reminders")
    lines.append(f"  {reminders['fired']} fired · {reminders['pending']} pending")
    lines.append("")

    lines.append("⚙️ Workflow runs")
    if workflows is None:
        lines.append("  unavailable (couldn't read run history)")
    elif workflows:
        for kind, stat in sorted(workflows.items()):
            lines.append(f"  {kind}: {stat['count']} runs ({stat['success']} success, "
                         f"{stat['failure']} failure, {stat['degraded']} degraded)")
    else:
        lines.append("  none this week")

    return "\n".join(lines)
