"""Tests for the FastAPI routes: auth, drafts CRUD, send flow."""

import pytest
from fastapi.testclient import TestClient

from app.api.routes import create_app
from app.store.db import Draft, DraftStatus, Email, get_session
from tests.conftest import make_email

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class FakeAccount:
    def __init__(self):
        self.sent: list[dict] = []
        self.saved: list[dict] = []

    def send_message(self, to, subject, body, attachments=(), thread_id=None,
                     in_reply_to="", references="", footer_url=""):
        self.sent.append({"to": to, "thread_id": thread_id, "body": body, "footer_url": footer_url})

    def create_gmail_draft(self, to, subject, body, attachments=(), thread_id=None,
                           in_reply_to="", references="", gmail_draft_id=None, footer_url=""):
        self.saved.append({"to": to, "body": body, "footer_url": footer_url})
        return {"id": "gd-123"}

    def delete_gmail_draft(self, gmail_draft_id):
        pass


def _settings_with(**overrides):
    from app.config import Settings
    return Settings(api_token=TOKEN, **overrides)


@pytest.fixture()
def client(session_db, monkeypatch):
    app = create_app(api_token=TOKEN)
    account = FakeAccount()
    monkeypatch.setattr("app.api.routes.get_gmail_account", lambda name: account)
    c = TestClient(app)
    c.sender = account
    return c


def _seed(category="needs_reply", with_draft=True) -> tuple[int, int | None]:
    data = make_email()
    with get_session() as s:
        email = Email(
            account=data["account"], message_id=data["message_id"], thread_id=data["thread_id"],
            sender=data["sender"], subject=data["subject"], snippet=data["snippet"],
            body="full body", category=category, urgency=2, reason="test",
            rfc_message_id="<m1@mail>", references="",
        )
        s.add(email)
        s.flush()
        email_id = email.id
        draft_id = None
        if with_draft:
            draft = Draft(email_id=email_id, body="draft body")
            s.add(draft)
            s.flush()
            draft_id = draft.id
    return email_id, draft_id


def test_requires_auth(client):
    assert client.get("/api/emails").status_code == 401
    assert client.get("/api/emails", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_empty_configured_token_is_not_fail_open(session_db):
    # A misconfigured deploy with an empty token must NOT accept "Bearer " (empty secret).
    app = create_app(api_token="")
    c = TestClient(app)
    assert c.get("/api/emails", headers={"Authorization": "Bearer "}).status_code == 401
    assert c.get("/api/emails", headers={"Authorization": "Bearer"}).status_code == 401


def test_health_open(client):
    assert client.get("/api/health").status_code == 200


def test_list_emails(client):
    _seed()
    resp = client.get("/api/emails", headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["subject"] == "Hello"
    assert data[0]["category"] == "needs_reply"


def test_list_emails_multi_category_filter(client):
    """category accepts a comma-separated list — used for 'action required' view."""
    for i, cat in enumerate(["critical", "needs_reply", "fyi", "skip"]):
        data = make_email(message_id=f"m{i}")
        with get_session() as s:
            s.add(Email(account=data["account"], message_id=data["message_id"],
                        subject=f"subj-{cat}", category=cat))
    resp = client.get("/api/emails?category=critical,needs_reply", headers=AUTH)
    assert resp.status_code == 200
    cats = {e["category"] for e in resp.json()}
    assert cats == {"critical", "needs_reply"}


def test_list_emails_suspicious_filter(client):
    """suspicious=true returns only flagged emails, and the JSON exposes the flag."""
    flagged = make_email(message_id="m-bad")
    normal = make_email(message_id="m-ok")
    with get_session() as s:
        s.add(Email(account=flagged["account"], message_id=flagged["message_id"],
                    subject="injection attempt", category="skip", suspicious=True))
        s.add(Email(account=normal["account"], message_id=normal["message_id"],
                    subject="normal email", category="fyi", suspicious=False))
    resp = client.get("/api/emails?suspicious=true", headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["subject"] == "injection attempt"
    assert data[0]["suspicious"] is True


def test_list_drafts_includes_email_context(client):
    _seed()
    resp = client.get("/api/drafts", headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["body"] == "draft body"
    assert data[0]["email"]["subject"] == "Hello"


def test_get_draft(client):
    _, draft_id = _seed()
    resp = client.get(f"/api/drafts/{draft_id}", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["email"]["body"] == "full body"


def test_get_draft_404(client):
    assert client.get("/api/drafts/999", headers=AUTH).status_code == 404


def test_update_draft_body(client):
    _, draft_id = _seed()
    resp = client.patch(f"/api/drafts/{draft_id}", json={"body": "edited"}, headers=AUTH)
    assert resp.status_code == 200
    with get_session() as s:
        assert s.get(Draft, draft_id).body == "edited"


def test_update_draft_blank_recipient_stored_as_null(client):
    # "" and whitespace normalize to NULL — NULL is the single "unset" sentinel
    # so the recipient/account fall back to the source email.
    _, draft_id = _seed()
    resp = client.patch(f"/api/drafts/{draft_id}", json={"to_addr": "  ", "account": ""}, headers=AUTH)
    assert resp.status_code == 200
    with get_session() as s:
        draft = s.get(Draft, draft_id)
        assert draft.to_addr is None
        assert draft.account is None


def test_send_draft(client):
    _, draft_id = _seed()
    resp = client.post(f"/api/drafts/{draft_id}/send", headers=AUTH)
    assert resp.status_code == 200
    assert len(client.sender.sent) == 1
    assert client.sender.sent[0]["body"] == "draft body"
    with get_session() as s:
        draft = s.get(Draft, draft_id)
        assert draft.status == DraftStatus.SENT
        assert draft.sent_at is not None


def test_send_already_sent_draft_409(client):
    _, draft_id = _seed()
    client.post(f"/api/drafts/{draft_id}/send", headers=AUTH)
    resp = client.post(f"/api/drafts/{draft_id}/send", headers=AUTH)
    assert resp.status_code == 409
    assert len(client.sender.sent) == 1  # not sent twice


def test_send_failure_reverts_to_pending(client):
    # A failed Gmail send must leave the draft retryable (PENDING), not stuck.
    _, draft_id = _seed()

    def boom(**kwargs):
        raise RuntimeError("gmail down")

    client.sender.send_message = boom
    resp = client.post(f"/api/drafts/{draft_id}/send", headers=AUTH)
    assert resp.status_code == 502
    with get_session() as s:
        assert s.get(Draft, draft_id).status == DraftStatus.PENDING


def test_discard_draft(client):
    _, draft_id = _seed()
    resp = client.post(f"/api/drafts/{draft_id}/discard", headers=AUTH)
    assert resp.status_code == 200
    with get_session() as s:
        assert s.get(Draft, draft_id).status == DraftStatus.DISCARDED


def test_send_discarded_draft_409(client):
    _, draft_id = _seed()
    client.post(f"/api/drafts/{draft_id}/discard", headers=AUTH)
    assert client.post(f"/api/drafts/{draft_id}/send", headers=AUTH).status_code == 409

def test_create_outreach_draft(client):
    r = client.post("/api/drafts", json={"kind": "outreach"}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["kind"] == "outreach" and r.json()["status"] == "pending"

def test_post_message_runs_composer(client, monkeypatch):
    from app.tools.drafts import composer
    # Stub the model factory so the route doesn't construct a real provider client
    # (which needs an API key and isn't present in CI). compose is mocked anyway.
    monkeypatch.setattr("app.llm.provider.get_chat_model", lambda role, settings=None: object())
    monkeypatch.setattr(composer, "compose",
        lambda ctx, llm: composer.ComposerResult(body="Hi", subject="Hello", to_addr="r@x.com", note="drafted"))
    did = client.post("/api/drafts", json={"kind": "outreach"}, headers=AUTH).json()["id"]
    r = client.post(f"/api/drafts/{did}/messages", json={"content": "hiring SRE at acme"}, headers=AUTH)
    j = r.json()
    assert j["body"] == "Hi" and j["subject"] == "Hello" and j["to_addr"] == "r@x.com"
    assert [m["role"] for m in j["messages"]] == ["user", "assistant"]

def test_get_attachments_hides_paths(client):
    r = client.get("/api/attachments", headers=AUTH)
    assert r.status_code == 200
    for a in r.json():
        assert set(a.keys()) == {"key", "label"}  # no "path"

def test_send_outreach_without_to_is_422(client):
    did = client.post("/api/drafts", json={"kind": "outreach"}, headers=AUTH).json()["id"]
    client.patch(f"/api/drafts/{did}", json={"body": "hi"}, headers=AUTH)
    assert client.post(f"/api/drafts/{did}/send", headers=AUTH).status_code == 422

def test_message_on_sent_draft_409(client):
    did = client.post("/api/drafts", json={"kind": "outreach"}, headers=AUTH).json()["id"]
    client.patch(f"/api/drafts/{did}", json={"body": "hi", "to_addr": "a@x.com"}, headers=AUTH)
    client.post(f"/api/drafts/{did}/send", headers=AUTH)
    assert client.post(f"/api/drafts/{did}/messages", json={"content": "x"}, headers=AUTH).status_code == 409


def test_send_with_footer_true_passes_url(client, monkeypatch):
    monkeypatch.setattr("app.config.get_settings",
                        lambda: _settings_with(email_footer_enabled=False,
                                               email_footer_url="https://r.example.com"))
    _, draft_id = _seed()
    client.post(f"/api/drafts/{draft_id}/send", headers=AUTH, json={"rotom_footer": True})
    assert client.sender.sent[-1]["footer_url"] == "https://r.example.com"


def test_send_with_footer_false_passes_empty(client, monkeypatch):
    monkeypatch.setattr("app.config.get_settings",
                        lambda: _settings_with(email_footer_enabled=True,
                                               email_footer_url="https://r.example.com"))
    _, draft_id = _seed()
    client.post(f"/api/drafts/{draft_id}/send", headers=AUTH, json={"rotom_footer": False})
    assert client.sender.sent[-1]["footer_url"] == ""


def test_send_without_field_falls_back_to_global(client, monkeypatch):
    monkeypatch.setattr("app.config.get_settings",
                        lambda: _settings_with(email_footer_enabled=True,
                                               email_footer_url="https://r.example.com"))
    _, draft_id = _seed()
    client.post(f"/api/drafts/{draft_id}/send", headers=AUTH)
    assert client.sender.sent[-1]["footer_url"] == "https://r.example.com"


def test_draft_json_exposes_rotom_footer_default(client, monkeypatch):
    monkeypatch.setattr("app.config.get_settings",
                        lambda: _settings_with(email_footer_enabled=True,
                                               email_footer_url="https://r.example.com"))
    _, draft_id = _seed()
    resp = client.get(f"/api/drafts/{draft_id}", headers=AUTH)
    assert resp.json()["rotom_footer_default"] is True
