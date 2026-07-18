"""Deterministic triage pipeline: fetch → dedup → classify → store → auto-draft → digest.

Dependencies (fetchers, classify_fn, draft_fn) are injected so the pipeline is
testable and reusable from both the scheduler and the chat agent's run_triage tool.
"""

import logging
from dataclasses import dataclass, field

from sqlalchemy.exc import IntegrityError

from app.store.db import Category, Draft, Email, ProcessedMessage, get_session

logger = logging.getLogger(__name__)


def _build_email_row(e: dict, **overrides) -> Email:
    return Email(
        account=e["account"],
        message_id=e["message_id"],
        thread_id=e.get("thread_id", ""),
        sender=e.get("sender", ""),
        subject=e.get("subject", ""),
        snippet=e.get("snippet", ""),
        body=e.get("body", ""),
        rfc_message_id=e.get("rfc_message_id", ""),
        references=e.get("references", ""),
        received_at=e.get("received_at"),
        **overrides,
    )


URGENCY_ICONS = {0: "", 1: "", 2: "❗", 3: "‼️"}
ACTION_HEADERS = [
    (Category.CRITICAL, "🔴 Critical"),
    (Category.NEEDS_REPLY, "✉️ Needs reply"),
]


@dataclass
class TriageResult:
    fetched: int = 0
    new_emails: list[Email] = field(default_factory=list)
    quarantined: list[Email] = field(default_factory=list)
    drafts_created: int = 0
    drafted_email_ids: set[int] = field(default_factory=set)
    errors: dict[str, str] = field(default_factory=dict)  # source -> error message


def run_triage(fetchers, classify_fn, draft_fn, max_per_account: int = 50, *, screen_fn=None) -> TriageResult:
    """Run one triage pass across all accounts. Never raises for per-account failures."""
    result = TriageResult()

    # 1. Fetch (degraded-state: one account failing doesn't kill the run)
    fetched: list[dict] = []
    logger.info("Starting email fetch across %d accounts", len(fetchers))
    for fetcher in fetchers:
        try:
            logger.info("Fetching unread for account %s", fetcher.account)
            f = fetcher.fetch_unread(max_results=max_per_account)
            logger.info("Fetched %d emails from %s", len(f), fetcher.account)
            fetched.extend(f)
        except Exception as exc:  # noqa: BLE001 — degraded-state reporting by design
            logger.exception("Fetch failed for account %s", fetcher.account)
            result.errors[fetcher.account] = f"fetch failed: {exc}"
    result.fetched = len(fetched)

    # 2. Dedup against the processed-messages ledger
    with get_session() as session:
        seen = {
            (p.account, p.message_id)
            for p in session.query(ProcessedMessage).filter(
                ProcessedMessage.message_id.in_([e["message_id"] for e in fetched] or [""])
            )
        }
    new = [e for e in fetched if (e["account"], e["message_id"]) not in seen]
    logger.info("Dedup complete: %d new un-processed emails found out of %d fetched", len(new), len(fetched))
    if not new:
        return result

    # 3. Screen for prompt injection (if screen_fn provided)
    quarantined_dicts: list[dict] = []
    clean_dicts: list[dict] = new
    if screen_fn is not None:
        logger.info("Screening %d emails for prompt injections", len(new))
        screen = screen_fn(new)  # ScreenResult(flagged, deferred)
        quarantined_dicts = [e for e in new if e["message_id"] in screen.flagged]
        # Deferred: judge was unavailable. Leave un-stored and un-processed so the
        # next run re-screens them — never quarantine on "couldn't check".
        clean_dicts = [
            e for e in new
            if e["message_id"] not in screen.flagged and e["message_id"] not in screen.deferred
        ]

        logger.info("Screening complete: %d quarantined, %d deferred, %d clean",
                    len(quarantined_dicts), len(screen.deferred), len(clean_dicts))
        if screen.deferred:
            logger.warning("Injection judge unavailable; deferring %d email(s) to next run", len(screen.deferred))
            result.errors["screen"] = f"injection judge unavailable: {len(screen.deferred)} email(s) deferred to next run"

        if quarantined_dicts:
            with get_session() as session:
                for e in quarantined_dicts:
                    flags = screen.flagged[e["message_id"]]
                    email_row = _build_email_row(e, category=Category.SKIP, suspicious=True, urgency=0, reason="possible prompt injection: " + ", ".join(flags))
                    try:
                        with session.begin_nested():
                            session.add(email_row)
                            session.add(ProcessedMessage(account=e["account"], message_id=e["message_id"]))
                            session.flush()
                    except IntegrityError:
                        logger.info("Skipping already-processed message %s (concurrent triage)", e["message_id"])
                        continue
                    result.quarantined.append(email_row)
                    result.new_emails.append(email_row)

    # 4. Classify (clean emails only)
    if not clean_dicts:
        logger.info("No clean emails to classify. Skipping.")
        return result
    
    logger.info("Classifying %d clean emails", len(clean_dicts))
    try:
        classified = classify_fn(clean_dicts)
    except Exception as exc:  # noqa: BLE001 — degraded-state: don't hard-fail the run
        # Leave clean emails un-stored and un-processed so the next run retries
        # them, rather than failing the whole pass (e.g. an LLM read timeout).
        logger.exception("Classification failed; leaving %d emails for the next run", len(clean_dicts))
        result.errors["classify"] = f"classification failed: {exc}"
        return result
    logger.info("Classification complete")

    # 5a. Generate draft bodies BEFORE opening the write transaction. LLM I/O must never
    #     run inside a held SQLite write lock — that would block every other writer
    #     (checkpointer, dashboard, scheduler) for the whole batch. (Failure degrades.)
    draft_bodies: dict[str, str] = {}
    for e in classified:
        if e["category"] == Category.NEEDS_REPLY:
            try:
                logger.info("Auto-drafting reply for needs_reply email: %s", e["message_id"])
                draft_bodies[e["message_id"]] = draft_fn(e)
            except Exception as exc:  # noqa: BLE001 — degrade, never lose the email
                logger.exception("Auto-draft failed for %s", e["message_id"])
                result.errors[f"draft:{e['message_id']}"] = f"draft failed: {exc}"

    # 5b. Store emails + drafts + mark processed. Each message is its own savepoint, so a
    #     concurrent triage that already inserted it (UniqueConstraint race) is skipped
    #     idempotently instead of aborting the whole pass with an IntegrityError.
    with get_session() as session:
        for e in classified:
            email_row = _build_email_row(e, category=e["category"], urgency=e.get("urgency", 0), reason=e.get("reason", ""))
            try:
                with session.begin_nested():
                    session.add(email_row)
                    session.add(ProcessedMessage(account=e["account"], message_id=e["message_id"]))
                    session.flush()
                    body = draft_bodies.get(e["message_id"])
                    if body is not None:
                        session.add(Draft(email_id=email_row.id, body=body))
            except IntegrityError:
                logger.info("Skipping already-processed message %s (concurrent triage)", e["message_id"])
                continue
            result.new_emails.append(email_row)
            if e["message_id"] in draft_bodies:
                result.drafts_created += 1
                result.drafted_email_ids.add(email_row.id)

    return result


def format_digest(result: TriageResult, dashboard_url: str) -> str:
    """Render a TriageResult as a Telegram-friendly digest message.

    Action-required emails (critical / needs_reply) are listed individually with a
    direct link to their dashboard detail page; FYI and skip collapse into counts
    so a big run stays readable.
    """
    lines: list[str] = []

    # Quarantine block — appears near the top if any emails were flagged as injection.
    if result.quarantined:
        n = len(result.quarantined)
        lines.append(f"⚠ {n} email(s) quarantined as possible prompt injection")
        for e in result.quarantined:
            lines.append(f"   {dashboard_url}/email/{e.id}")

    # Exclude quarantined emails from the regular category buckets (they're category=SKIP).
    quarantined_ids = {e.id for e in result.quarantined}
    non_quarantined = [e for e in result.new_emails if e.id not in quarantined_ids]

    actionable = [
        e for e in non_quarantined if e.category in (Category.CRITICAL, Category.NEEDS_REPLY)
    ]
    fyi_count = sum(1 for e in non_quarantined if e.category == Category.FYI)
    skip_count = sum(1 for e in non_quarantined if e.category == Category.SKIP)

    if not actionable and not fyi_count:
        lines.append("📭 No new emails worth your attention.")
    elif not actionable:
        lines.append("📬 Email triage: nothing needs action.")
    else:
        lines.append(f"📬 Email triage: {len(actionable)} need your attention")
        drafted_ids = result.drafted_email_ids
        for category, header in ACTION_HEADERS:
            in_cat = [e for e in actionable if e.category == category]
            if not in_cat:
                continue
            lines.append(f"\n{header} ({len(in_cat)})")
            for e in in_cat:
                icon = URGENCY_ICONS.get(e.urgency, "")
                draft_note = " 📝" if e.id in drafted_ids else ""
                lines.append(f"• {icon}[{e.account}] {e.subject} — {e.sender}{draft_note}")
                if e.reason:
                    lines.append(f"   ↳ {e.reason}")
                lines.append(f"   {dashboard_url}/email/{e.id}")

    counts = []
    if fyi_count:
        counts.append(f"ℹ️ {fyi_count} FYI")
    if skip_count:
        counts.append(f"🗑 {skip_count} skipped")
    if counts:
        lines.append(f"\n{' · '.join(counts)} — {dashboard_url}/email")

    if result.drafts_created:
        lines.append(f"\n📝 {result.drafts_created} draft(s) ready for review: {dashboard_url}/email/drafts")
    elif not counts:
        lines.append(f"\nDashboard: {dashboard_url}/email")

    for source, error in result.errors.items():
        lines.append(f"⚠ {source}: {error}")

    return "\n".join(lines)
