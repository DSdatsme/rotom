"""Tests for triage/pipeline.py — dedup, storage, auto-draft, degraded state, digest."""

from app.store.db import Draft, Email, ProcessedMessage, get_session
from app.tools.gmail.pipeline import TriageResult, format_digest, run_triage
from tests.conftest import make_email


class FakeFetcher:
    def __init__(self, account: str, emails: list[dict] | Exception):
        self.account = account
        self._emails = emails

    def fetch_unread(self, max_results: int = 50):
        if isinstance(self._emails, Exception):
            raise self._emails
        return self._emails


def classify_all_as(category: str, urgency: int = 1):
    def classify_fn(emails):
        return [
            {**e, "category": category, "urgency": urgency, "reason": f"test {category}"}
            for e in emails
        ]
    return classify_fn


def fake_draft_fn(email: dict) -> str:
    return f"Draft reply to: {email['subject']}"


def test_new_emails_stored_and_marked_processed(session_db):
    fetchers = [FakeFetcher("personal", [make_email(message_id="m1"), make_email(message_id="m2")])]
    result = run_triage(fetchers, classify_all_as("fyi"), fake_draft_fn)
    assert result.fetched == 2
    assert len(result.new_emails) == 2
    with get_session() as s:
        assert s.query(Email).count() == 2
        assert s.query(ProcessedMessage).count() == 2


def test_dedup_skips_already_processed(session_db):
    fetchers = [FakeFetcher("personal", [make_email(message_id="m1")])]
    run_triage(fetchers, classify_all_as("fyi"), fake_draft_fn)
    result = run_triage(fetchers, classify_all_as("fyi"), fake_draft_fn)
    assert result.fetched == 1
    assert result.new_emails == []
    with get_session() as s:
        assert s.query(Email).count() == 1


def test_auto_draft_created_for_needs_reply(session_db):
    fetchers = [FakeFetcher("personal", [make_email(subject="Question for you")])]
    result = run_triage(fetchers, classify_all_as("needs_reply", urgency=2), fake_draft_fn)
    assert result.drafts_created == 1
    with get_session() as s:
        draft = s.query(Draft).one()
        assert draft.status == "pending"
        assert "Question for you" in draft.body


def test_no_draft_for_fyi_or_skip(session_db):
    fetchers = [FakeFetcher("personal", [make_email()])]
    result = run_triage(fetchers, classify_all_as("fyi"), fake_draft_fn)
    assert result.drafts_created == 0


def test_draft_failure_does_not_lose_email(session_db):
    def broken_draft(email):
        raise RuntimeError("LLM down")

    fetchers = [FakeFetcher("personal", [make_email()])]
    result = run_triage(fetchers, classify_all_as("needs_reply"), broken_draft)
    assert result.drafts_created == 0
    assert "draft" in " ".join(result.errors.values()).lower()
    with get_session() as s:
        assert s.query(Email).count() == 1  # email still stored


def test_classify_failure_is_degraded_not_fatal(session_db):
    def broken_classify(emails):
        raise RuntimeError("read operation timed out")

    fetchers = [FakeFetcher("personal", [make_email(message_id="m1")])]
    result = run_triage(fetchers, broken_classify, fake_draft_fn)
    # run completes (no raise) and records the error
    assert "classify" in result.errors
    assert "timed out" in result.errors["classify"]
    # emails left un-stored and un-processed so the next run retries them
    with get_session() as s:
        assert s.query(Email).count() == 0
        assert s.query(ProcessedMessage).count() == 0


def test_fetch_failure_is_degraded_not_fatal(session_db):
    fetchers = [
        FakeFetcher("work", RuntimeError("token expired")),
        FakeFetcher("personal", [make_email()]),
    ]
    result = run_triage(fetchers, classify_all_as("fyi"), fake_draft_fn)
    assert "work" in result.errors
    assert len(result.new_emails) == 1  # personal still processed


def test_digest_contains_sections_and_warnings(session_db):
    fetchers = [
        FakeFetcher("personal", [make_email(subject="URGENT invoice", sender="ceo@corp.com")]),
        FakeFetcher("work", RuntimeError("boom")),
    ]
    result = run_triage(fetchers, classify_all_as("critical", urgency=3), fake_draft_fn)
    digest = format_digest(result, dashboard_url="http://localhost:3000")
    assert "URGENT invoice" in digest
    assert "ceo@corp.com" in digest
    assert "⚠" in digest and "work" in digest
    assert "http://localhost:3000" in digest


def test_digest_when_nothing_new():
    result = TriageResult(fetched=0, new_emails=[], drafts_created=0, errors={})
    digest = format_digest(result, dashboard_url="http://localhost:3000")
    assert digest  # still says something ("no new emails")


def test_skip_category_not_in_digest(session_db):
    fetchers = [FakeFetcher("personal", [make_email(subject="Buy now!!!")])]
    result = run_triage(fetchers, classify_all_as("skip", urgency=0), fake_draft_fn)
    digest = format_digest(result, dashboard_url="http://x")
    assert "Buy now!!!" not in digest


def test_fyi_collapses_to_count_in_digest(session_db):
    fetchers = [FakeFetcher("personal", [make_email(subject=f"Update {i}", message_id=f"m{i}") for i in range(3)])]
    result = run_triage(fetchers, classify_all_as("fyi"), fake_draft_fn)
    digest = format_digest(result, dashboard_url="http://x")
    assert "3 FYI" in digest
    assert "Update 0" not in digest  # individual FYI emails are not listed


def test_actionable_emails_link_to_detail_page(session_db):
    fetchers = [FakeFetcher("personal", [make_email(subject="Invoice due")])]
    result = run_triage(fetchers, classify_all_as("critical", urgency=3), fake_draft_fn)
    digest = format_digest(result, dashboard_url="http://x")
    email_id = result.new_emails[0].id
    assert f"http://x/email/{email_id}" in digest


def test_screen_fn_quarantines_and_skips_classifier(session_db):
    from app.store.db import Category, Email, get_session

    seen_by_classifier = []

    def classify_spy(emails):
        seen_by_classifier.extend(e["message_id"] for e in emails)
        return classify_all_as("fyi")(emails)

    def screen_fn(emails):
        # quarantine anything whose subject says "evil"
        from app.tools.gmail.injection import ScreenResult
        return ScreenResult(flagged={e["message_id"]: ["instruction_override"]
                                     for e in emails if "evil" in e["subject"]})

    fetchers = [FakeFetcher("personal", [make_email(subject="evil ignore previous", message_id="m1"),
                                         make_email(subject="hello", message_id="m2")])]
    result = run_triage(fetchers, classify_spy, fake_draft_fn, screen_fn=screen_fn)

    assert "m1" not in seen_by_classifier  # quarantined email never classified
    assert "m2" in seen_by_classifier
    with get_session() as s:
        evil = s.query(Email).filter(Email.message_id == "m1").one()
        assert evil.suspicious is True
        assert evil.category == Category.SKIP
        assert "injection" in evil.reason.lower()
    assert len(result.quarantined) == 1


def test_quarantined_email_not_drafted(session_db):
    def screen_fn(emails):
        from app.tools.gmail.injection import ScreenResult
        return ScreenResult(flagged={e["message_id"]: ["exfiltration"] for e in emails})

    drafted = []
    def draft_spy(e):
        drafted.append(e["message_id"])
        return "draft"

    fetchers = [FakeFetcher("personal", [make_email(message_id="m1")])]
    run_triage(fetchers, classify_all_as("needs_reply"), draft_spy, screen_fn=screen_fn)
    assert drafted == []  # quarantined → never drafted


def test_screen_deferred_email_not_stored_or_classified(session_db):
    """Judge unavailable → borderline is deferred: not classified, not stored, not
    marked processed, so the next run re-screens it (no permanent false quarantine)."""
    from app.store.db import Email, ProcessedMessage, get_session
    from app.tools.gmail.injection import ScreenResult

    seen_by_classifier = []

    def classify_spy(emails):
        seen_by_classifier.extend(e["message_id"] for e in emails)
        return classify_all_as("fyi")(emails)

    def screen_fn(emails):
        return ScreenResult(deferred={"m1"})

    fetchers = [FakeFetcher("personal", [make_email(message_id="m1"),
                                         make_email(message_id="m2")])]
    result = run_triage(fetchers, classify_spy, fake_draft_fn, screen_fn=screen_fn)

    assert "m1" not in seen_by_classifier          # deferred → not classified
    assert "m2" in seen_by_classifier              # others proceed
    assert result.quarantined == []                # deferred is NOT quarantined
    with get_session() as s:
        assert s.query(Email).filter(Email.message_id == "m1").first() is None       # not stored
        assert s.query(ProcessedMessage).filter(ProcessedMessage.message_id == "m1").first() is None  # retried next run
    assert "screen" in result.errors               # surfaced in the digest


def test_digest_shows_quarantine_line(session_db):
    def screen_fn(emails):
        from app.tools.gmail.injection import ScreenResult
        return ScreenResult(flagged={e["message_id"]: ["instruction_override"] for e in emails})

    fetchers = [FakeFetcher("personal", [make_email(subject="evil", message_id="m1")])]
    result = run_triage(fetchers, classify_all_as("fyi"), fake_draft_fn, screen_fn=screen_fn)
    digest = format_digest(result, dashboard_url="http://x")
    assert "quarantined" in digest.lower()
    assert "http://x/email/" in digest


def test_no_screen_fn_is_backward_compatible(session_db):
    fetchers = [FakeFetcher("personal", [make_email()])]
    result = run_triage(fetchers, classify_all_as("fyi"), fake_draft_fn)  # no screen_fn
    assert result.quarantined == []


def test_duplicate_message_id_does_not_abort_pass(session_db):
    # Simulates the TOCTOU race: the same (account, message_id) reaching the store
    # step twice must be skipped idempotently, not raise IntegrityError.
    dupes = [make_email(message_id="dup"), make_email(message_id="dup")]
    fetchers = [FakeFetcher("personal", dupes)]
    result = run_triage(fetchers, classify_all_as("fyi"), fake_draft_fn)
    with get_session() as s:
        assert s.query(Email).filter(Email.message_id == "dup").count() == 1
        assert s.query(ProcessedMessage).filter(ProcessedMessage.message_id == "dup").count() == 1
    assert len(result.new_emails) == 1
