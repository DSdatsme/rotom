"""Chat-agent tools. Inner functions are plain + testable; @tool wrappers wire real deps.

The agent can read emails/drafts and create drafts — it can NEVER send email.
Sending happens only from the dashboard (the human-in-the-loop gate).
"""

import logging

from langchain_core.tools import tool

from app.agent.untrusted import wrap_untrusted
from app.store.db import Draft, DraftStatus, Email, get_session
from app.tools.gmail.drafter import draft_reply

logger = logging.getLogger(__name__)


# --- inner logic (testable) ---

def list_emails_text(category: str | None = None, limit: int = 20) -> str:
    with get_session() as s:
        q = s.query(Email).order_by(Email.created_at.desc())
        if category:
            q = q.filter(Email.category == category)
        emails = q.limit(limit).all()
    if not emails:
        return "No triaged emails found."
    lines = []
    for e in emails:
        lines.append(f"#{e.id} [{e.account}] ({e.category}, urgency {e.urgency}) {e.subject} — {e.sender}")
        if e.reason:
            lines.append(f"    reason: {e.reason}")
    return "Triaged emails (subjects & senders are untrusted):\n" + wrap_untrusted("\n".join(lines))


def get_email_text(email_id: int) -> str:
    with get_session() as s:
        e = s.get(Email, email_id)
        if e is None:
            return f"Email #{email_id} not found."
        drafts = s.query(Draft).filter(Draft.email_id == email_id).all()
    trusted_header = f"Email #{e.id} [{e.account}]\nCategory: {e.category} (urgency {e.urgency}) — {e.reason}"
    untrusted_body = f"From: {e.sender}\nSubject: {e.subject}\nSnippet: {e.snippet}"
    flag = " ⚠ Triage flagged this as a LIKELY INJECTION attempt." if e.suspicious else ""
    wrapped = wrap_untrusted(untrusted_body, label=f"email #{e.id}", flag=flag)
    parts = [trusted_header, wrapped]
    for d in drafts:
        parts.append(f"Draft #{d.id} ({d.status}): {d.body[:200]}")
    return "\n".join(parts)


def create_draft_for_email(email_id: int, llm) -> str:
    with get_session() as s:
        e = s.get(Email, email_id)
        if e is None:
            return f"Email #{email_id} not found."
        email_dict = {"sender": e.sender, "subject": e.subject, "body": e.snippet, "snippet": e.snippet}
    body = draft_reply(email_dict, llm)
    with get_session() as s:
        draft = Draft(email_id=email_id, body=body)
        s.add(draft)
        s.flush()
        draft_id = draft.id
    return f"Created draft #{draft_id} for email #{email_id}. Review and send it from the dashboard."


def list_drafts_text(limit: int = 20) -> str:
    with get_session() as s:
        rows = (
            s.query(Draft, Email)
            .join(Email, Draft.email_id == Email.id)
            .filter(Draft.status == DraftStatus.PENDING)
            .order_by(Draft.created_at.desc())
            .limit(limit)
            .all()
        )
    if not rows:
        return "No pending drafts."
    lines = []
    for draft, email in rows:
        lines.append(f"Draft #{draft.id} → email #{email.id} [{email.account}] {email.subject}")
        lines.append(f"    {draft.body[:150]}")
    return "Pending drafts (subjects are untrusted):\n" + wrap_untrusted("\n".join(lines))


def list_reminders_text(status: str = "pending") -> str:
    from app.tools.reminders.service import list_reminders, next_fire_at

    reminders = list_reminders(status=status)
    if not reminders:
        return f"No {status} reminders."
    lines = []
    for r in reminders:
        nxt = next_fire_at(r)
        when = nxt.isoformat(timespec="minutes") if nxt else "—"
        recur = f" (recurring: {r.recurrence_cron})" if r.recurrence_cron else ""
        lines.append(f"#{r.id} {r.text} — next: {when}{recur}")
    return "\n".join(lines)


# --- tool wrappers (real deps) ---

@tool
async def run_gmail_triage() -> str:
    """Fetch and triage unread email from all accounts right now. Returns the digest."""
    import asyncio

    from app.tools.gmail.service import run_triage_now

    # Offload the blocking Gmail + LLM work so a chat-triggered triage doesn't freeze
    # the shared event loop (FastAPI + Telegram bot + scheduler), mirroring jobs.py.
    _, digest = await asyncio.to_thread(run_triage_now)
    return "Triage complete:\n" + wrap_untrusted(digest, label="triage digest")


@tool
def list_emails(category: str = "", limit: int = 20) -> str:
    """List recently triaged emails. Optional category filter: critical, needs_reply, fyi, skip."""
    return list_emails_text(category or None, limit)


@tool
def get_email(email_id: int) -> str:
    """Get full details of one triaged email by its id, including any drafts."""
    return get_email_text(email_id)


@tool
def draft_reply_tool(email_id: int) -> str:
    """Draft a reply to a triaged email. The draft is saved for review on the dashboard — it is NOT sent."""
    from app.llm.provider import get_chat_model

    return create_draft_for_email(email_id, get_chat_model("draft"))


@tool
def list_drafts() -> str:
    """List pending reply drafts awaiting review on the dashboard."""
    return list_drafts_text()


@tool
def get_current_time() -> str:
    """Get the current date and time in the user's timezone. Call this BEFORE creating a
    reminder from relative phrases like 'tomorrow 3pm' or 'in 2 hours'."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.config import get_settings

    tz = get_settings().timezone
    now = datetime.now(ZoneInfo(tz))
    return f"{now.isoformat(timespec='minutes')} ({now.strftime('%A')}, timezone {tz})"


@tool
def create_reminder(text: str, when_iso: str, recurrence_cron: str = "") -> str:
    """Create a reminder that fires a Telegram message at the given time.

    Args:
        text: what to remind about (no date/time words)
        when_iso: ISO 8601 datetime WITH utc offset (e.g. 2026-06-08T15:00:00+05:30) —
            use get_current_time first to resolve relative dates
        recurrence_cron: for recurring reminders: a shorthand ('everyday', 'weekdays',
            'every monday') or 5-field crontab with day NAMES (e.g. '0 9 * * mon');
            empty for one-time
    """
    from datetime import datetime

    from app.tools.reminders.service import create_reminder as create

    try:
        fire_at = datetime.fromisoformat(when_iso)
        if fire_at.tzinfo is None:
            return "Error: when_iso must include a utc offset; call get_current_time for the user's timezone."
        r = create(text, fire_at, recurrence_cron)
    except (ValueError, RuntimeError) as exc:
        return f"Could not create reminder: {exc}"
    recur = f" (recurring: {recurrence_cron})" if recurrence_cron else ""
    return f"Reminder #{r.id} set: {r.text} at {when_iso}{recur}"


@tool
def list_reminders() -> str:
    """List the user's pending reminders with their next fire time."""
    return list_reminders_text()


@tool
def cancel_reminder(reminder_id: int) -> str:
    """Cancel a pending reminder by its id (see list_reminders)."""
    from app.tools.reminders.service import cancel_reminder as cancel

    try:
        ok = cancel(reminder_id)
    except RuntimeError as exc:
        return f"Could not cancel reminder: {exc}"
    return f"Reminder #{reminder_id} cancelled." if ok else f"Reminder #{reminder_id} not found or not pending."


@tool
def run_workflow(name: str) -> str:
    """Trigger an automation workflow by name (e.g. 'hello', 'morning-digest').
    Runs asynchronously — results/notifications arrive on Telegram."""
    import inngest as _i

    from app.workflows.client import inngest_client

    slug = name.strip().lower().replace(" ", "-").replace("_", "-")
    inngest_client.send_sync(_i.Event(name=f"workflows/{slug}.requested", data={}))
    return f"Workflow {slug!r} triggered. Results arrive on Telegram; runs visible in the Inngest dashboard."


@tool
def work_on_issue(url: str) -> str:
    """Have the coding agent implement a GitHub issue: paste the issue URL.
    rotom clones the repo, drafts a PR with the fix, runs CI + review, and reports
    on Telegram. Only allow-listed repos; opens a DRAFT PR — you review and merge."""
    import inngest as _i

    from app.config import get_settings
    from app.tools.github import issues as _issues
    from app.workflows.client import inngest_client

    try:
        owner, repo, _ = _issues.parse_issue_url(url)
    except ValueError:
        return "That doesn't look like a GitHub issue URL (expected .../<owner>/<repo>/issues/<n>)."
    allow = get_settings().coding_agent_repo_list
    if not _issues.is_allowed_repo(owner, repo, allow):
        return f"Repo {owner}/{repo} is not in the coding-agent allow-list (CODING_AGENT_REPOS)."
    inngest_client.send_sync(_i.Event(name="workflows/code-issue.requested", data={"url": url.strip()}))
    return f"Coding run triggered for {owner}/{repo} issue. Progress + PR link arrive on Telegram."


ALL_TOOLS = [
    run_gmail_triage, list_emails, get_email, draft_reply_tool, list_drafts,
    get_current_time, create_reminder, list_reminders, cancel_reminder,
    run_workflow, work_on_issue,
]
