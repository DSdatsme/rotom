"""Wires settings + Gmail + LLM into the triage pipeline. Used by the scheduler,
the chat agent's run_triage tool, and (indirectly) the API."""

import logging
import threading

from app.config import get_settings
from app.tools.gmail.client import load_accounts
from app.llm.provider import get_chat_model
from app.tools.gmail.classifier import classify_emails
from app.tools.gmail.drafter import draft_reply
from app.tools.gmail.pipeline import TriageResult, format_digest, run_triage

logger = logging.getLogger(__name__)

# Triage has three entry points (cron, dashboard "run now", chat tool) under
# different APScheduler job ids, so max_instances=1 can't serialize them. This
# process-wide lock ensures only one pass runs at a time; overlapping triggers
# skip rather than race the dedup read-then-write.
_triage_lock = threading.Lock()


def run_triage_now() -> tuple[TriageResult, str]:
    """One full triage pass. Returns (result, digest text).

    If a pass is already running, returns immediately with an empty result and a
    note (no second pass) — this serializes cron / manual / chat triggers.
    """
    if not _triage_lock.acquire(blocking=False):
        logger.info("Triage already in progress; skipping this trigger")
        return TriageResult(), "⏳ A triage run is already in progress — skipped this trigger."
    try:
        return _run_triage_locked()
    finally:
        _triage_lock.release()


def _run_triage_locked() -> tuple[TriageResult, str]:
    from app.tools.gmail.injection import ScreenResult, judge_injections, screen_emails

    settings = get_settings()
    fetchers = load_accounts(settings)
    classify_llm = get_chat_model("classify", settings)
    draft_llm = get_chat_model("draft", settings)

    def classify_fn(emails: list[dict]) -> list[dict]:
        return classify_emails(emails, classify_llm, settings.key_sender_list, settings.excluded_topic_list)

    def draft_fn(email: dict) -> str:
        return draft_reply(email, draft_llm)

    def screen_fn(emails: list[dict]) -> ScreenResult:
        # Heuristic pre-classifies; the LLM judge sees all non-malicious email (recall).
        # A judge outage defers the borderline band to the next run (see screen_emails).
        return screen_emails(emails, lambda batch: judge_injections(batch, classify_llm))

    result = run_triage(fetchers, classify_fn, draft_fn, max_per_account=settings.max_emails_per_run, screen_fn=screen_fn)
    digest = format_digest(result, settings.dashboard_url)
    return result, digest
