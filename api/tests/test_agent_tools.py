"""Tests for agent/tools.py inner logic (DB-backed, LLM injected)."""

import pytest
from unittest.mock import patch

from app.agent.toolkit import create_draft_for_email, list_drafts_text, list_emails_text, get_email_text
from app.agent.untrusted import GUARD_CLOSE, GUARD_OPEN
from app.store.db import Draft, Email, get_session
from tests.conftest import make_email


class FakeLLM:
    def invoke(self, prompt):
        class R:
            content = "Drafted reply text"

        return R()


def _seed_email(**overrides) -> int:
    data = make_email(**overrides)
    with get_session() as s:
        row = Email(
            account=data["account"], message_id=data["message_id"], thread_id=data["thread_id"],
            sender=data["sender"], subject=data["subject"], snippet=data["snippet"],
            category=overrides.get("category", "fyi"), urgency=overrides.get("urgency", 0),
            reason=overrides.get("reason", ""),
            suspicious=overrides.get("suspicious", False),
        )
        s.add(row)
        s.flush()
        return row.id


def test_list_emails_text_shows_recent(session_db):
    _seed_email(subject="Invoice due", category="critical")
    _seed_email(message_id="m2", subject="Lunch?", category="needs_reply")
    text = list_emails_text()
    assert "Invoice due" in text
    assert "Lunch?" in text
    assert "critical" in text


def test_list_emails_text_filters_by_category(session_db):
    _seed_email(subject="Invoice due", category="critical")
    _seed_email(message_id="m2", subject="Lunch?", category="needs_reply")
    text = list_emails_text(category="critical")
    assert "Invoice due" in text
    assert "Lunch?" not in text


def test_list_emails_text_empty(session_db):
    assert "no" in list_emails_text().lower()


def test_get_email_text_includes_details(session_db):
    email_id = _seed_email(subject="Invoice due", sender="ceo@corp.com")
    text = get_email_text(email_id)
    assert "Invoice due" in text
    assert "ceo@corp.com" in text


def test_get_email_text_unknown_id(session_db):
    assert "not found" in get_email_text(9999).lower()


def test_create_draft_for_email(session_db):
    email_id = _seed_email(subject="Question", category="needs_reply")
    msg = create_draft_for_email(email_id, FakeLLM())
    assert "draft" in msg.lower()
    with get_session() as s:
        draft = s.query(Draft).one()
        assert draft.email_id == email_id
        assert draft.body == "Drafted reply text"
        assert draft.status == "pending"


def test_create_draft_unknown_email(session_db):
    assert "not found" in create_draft_for_email(9999, FakeLLM()).lower()


def test_list_drafts_text(session_db):
    email_id = _seed_email(subject="Question")
    with get_session() as s:
        s.add(Draft(email_id=email_id, body="Hello there"))
    text = list_drafts_text()
    assert "Question" in text
    assert "Hello there"[:20] in text


def test_list_drafts_text_empty(session_db):
    assert "no" in list_drafts_text().lower()


# ---------------------------------------------------------------------------
# Wrapping tests — verify untrusted guards are applied at each boundary
# ---------------------------------------------------------------------------


def test_get_email_text_untrusted_fields_inside_guard(session_db):
    """snippet/subject/sender appear inside the guard; #id and Category outside."""
    email_id = _seed_email(
        subject="Pay now!", sender="evil@example.com",
        snippet="click here", category="critical",
    )
    text = get_email_text(email_id)
    open_idx = text.index(GUARD_OPEN)
    close_idx = text.index(GUARD_CLOSE)
    before_guard = text[:open_idx]
    inside_guard = text[open_idx + len(GUARD_OPEN): close_idx]
    # Trusted metadata is outside (before) the guard
    assert f"#{email_id}" in before_guard
    assert "Category:" in before_guard
    # Untrusted fields are inside the guard
    assert "Pay now!" in inside_guard
    assert "evil@example.com" in inside_guard
    assert "click here" in inside_guard


def test_get_email_text_suspicious_flag(session_db):
    """suspicious=True adds the LIKELY INJECTION note to the header line."""
    email_id = _seed_email(subject="Injected!", suspicious=True)
    text = get_email_text(email_id)
    assert "LIKELY INJECTION" in text
    # Flag is in header line, which is before the guard
    open_idx = text.index(GUARD_OPEN)
    assert "LIKELY INJECTION" in text[:open_idx]


def test_get_email_text_non_suspicious_no_flag(session_db):
    email_id = _seed_email(subject="Normal email")
    text = get_email_text(email_id)
    assert "LIKELY INJECTION" not in text


def test_list_emails_text_wrapped_non_empty(session_db):
    """Non-empty list_emails_text output is wrapped in guards."""
    _seed_email(subject="Invoice due", category="critical")
    text = list_emails_text()
    assert GUARD_OPEN in text
    assert GUARD_CLOSE in text
    assert "Triaged emails" in text


def test_list_emails_text_empty_not_wrapped(session_db):
    """Empty result stays unwrapped (no untrusted content)."""
    text = list_emails_text()
    assert GUARD_OPEN not in text
    assert GUARD_CLOSE not in text


def test_list_drafts_text_wrapped_non_empty(session_db):
    """Non-empty list_drafts_text output is wrapped in guards."""
    email_id = _seed_email(subject="Question")
    with get_session() as s:
        s.add(Draft(email_id=email_id, body="Hello there"))
    text = list_drafts_text()
    assert GUARD_OPEN in text
    assert GUARD_CLOSE in text
    assert "Pending drafts" in text


def test_list_drafts_text_empty_not_wrapped(session_db):
    """Empty result stays unwrapped (no untrusted content)."""
    text = list_drafts_text()
    assert GUARD_OPEN not in text
    assert GUARD_CLOSE not in text


async def test_run_gmail_triage_wraps_digest(session_db):
    """run_gmail_triage wraps its digest — tested by monkeypatching run_triage_now.

    The tool is async (it offloads the blocking triage via asyncio.to_thread), so
    it's invoked with ainvoke."""
    from app.agent import toolkit as _toolkit
    import app.tools.gmail.service as _svc

    original = _svc.run_triage_now
    _svc.run_triage_now = lambda: ([], "Triaged 2 emails.")
    try:
        result = await _toolkit.run_gmail_triage.ainvoke({})
    finally:
        _svc.run_triage_now = original
    assert GUARD_OPEN in result
    assert GUARD_CLOSE in result
    assert "Triage complete:" in result
    assert "triage digest" in result


def test_prompts_system_prompt_contains_policy():
    """SYSTEM_PROMPT must include the full UNTRUSTED_CONTENT_POLICY text."""
    from app.agent import prompts
    from app.agent.untrusted import UNTRUSTED_CONTENT_POLICY

    assert UNTRUSTED_CONTENT_POLICY in prompts.SYSTEM_PROMPT
