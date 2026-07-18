"""Tests for pure Gmail helpers: message parsing and reply MIME building."""

import base64
from email import message_from_bytes

from app.tools.gmail.client import build_reply_mime, parse_message


def _gmail_detail(headers: dict[str, str], snippet: str = "snip", body_text: str = "") -> dict:
    """Build a fake Gmail API messages.get response."""
    payload: dict = {
        "headers": [{"name": k, "value": v} for k, v in headers.items()],
        "mimeType": "text/plain",
    }
    if body_text:
        payload["body"] = {"data": base64.urlsafe_b64encode(body_text.encode()).decode()}
    return {
        "id": "msg123",
        "threadId": "thr456",
        "snippet": snippet,
        "internalDate": "1718000000000",  # ms epoch
        "payload": payload,
    }


class TestParseMessage:
    def test_extracts_core_fields(self):
        detail = _gmail_detail(
            {"From": "Alice <alice@example.com>", "Subject": "Invoice due", "Message-ID": "<abc@mail>"},
            snippet="please pay",
            body_text="Please pay the invoice by Friday.",
        )
        email = parse_message(detail, account="personal")
        assert email["account"] == "personal"
        assert email["message_id"] == "msg123"
        assert email["thread_id"] == "thr456"
        assert email["sender"] == "Alice <alice@example.com>"
        assert email["subject"] == "Invoice due"
        assert email["snippet"] == "please pay"
        assert "Please pay the invoice" in email["body"]
        assert email["rfc_message_id"] == "<abc@mail>"
        assert email["received_at"] is not None

    def test_missing_headers_default_empty(self):
        email = parse_message(_gmail_detail({}), account="work")
        assert email["sender"] == ""
        assert email["subject"] == ""
        assert email["rfc_message_id"] == ""

    def test_extracts_body_from_multipart(self):
        text = "nested plain text body"
        detail = {
            "id": "m1",
            "threadId": "t1",
            "snippet": "s",
            "internalDate": "1718000000000",
            "payload": {
                "headers": [],
                "mimeType": "multipart/alternative",
                "parts": [
                    {"mimeType": "text/html", "body": {"data": base64.urlsafe_b64encode(b"<b>html</b>").decode()}},
                    {"mimeType": "text/plain", "body": {"data": base64.urlsafe_b64encode(text.encode()).decode()}},
                ],
            },
        }
        email = parse_message(detail, account="personal")
        assert email["body"] == text

    def test_body_truncated_to_limit(self):
        detail = _gmail_detail({"From": "a@b.c"}, body_text="x" * 10_000)
        email = parse_message(detail, account="personal", body_limit=2000)
        assert len(email["body"]) == 2000


class TestBuildQuery:
    def test_query_limits_lookback_in_hours(self):
        from app.tools.gmail.client import build_query

        # 25h before a fixed "now" → after: that exact unix timestamp
        assert build_query(25, now=1_000_000_000) == "in:inbox after:999910000"

    def test_load_accounts_passes_lookback(self, monkeypatch):
        from app.config import Settings
        from app.tools.gmail.client import load_accounts

        monkeypatch.setenv("GMAIL_WORK_REFRESH_TOKEN", "tok")
        s = Settings(
            gmail_client_id="cid", gmail_client_secret="sec", gmail_accounts="work",
            gmail_triage_lookback_hours=25, _env_file=None,
        )
        accounts = load_accounts(s)
        assert accounts[0].lookback_hours == 25


class TestLoadAccounts:
    def test_token_from_dotenv_extras(self):
        """Tokens defined only in the .env file (not os.environ) must be found."""
        from app.config import Settings
        from app.tools.gmail.client import load_accounts

        s = Settings(
            gmail_client_id="cid",
            gmail_client_secret="sec",
            gmail_accounts="main",
            _env_file=None,
            **{"gmail_main_refresh_token": "tok-from-dotenv"},
        )
        accounts = load_accounts(s)
        assert len(accounts) == 1
        assert accounts[0].account == "main"

    def test_token_from_os_environ(self, monkeypatch):
        from app.config import Settings
        from app.tools.gmail.client import load_accounts

        monkeypatch.setenv("GMAIL_WORK_REFRESH_TOKEN", "tok-from-env")
        s = Settings(
            gmail_client_id="cid", gmail_client_secret="sec", gmail_accounts="work", _env_file=None
        )
        assert len(load_accounts(s)) == 1

    def test_missing_token_skipped(self):
        from app.config import Settings
        from app.tools.gmail.client import load_accounts

        s = Settings(
            gmail_client_id="cid", gmail_client_secret="sec", gmail_accounts="ghost", _env_file=None
        )
        assert load_accounts(s) == []


class TestBuildReplyMime:
    def _decode(self, raw: str):
        return message_from_bytes(base64.urlsafe_b64decode(raw))

    def test_builds_threaded_reply(self):
        raw = build_reply_mime(
            to="Alice <alice@example.com>",
            subject="Invoice due",
            body="On it, paying today.",
            rfc_message_id="<abc@mail>",
            references="<root@mail> <abc@mail>",
        )
        msg = self._decode(raw)
        assert msg["To"] == "Alice <alice@example.com>"
        assert msg["Subject"] == "Re: Invoice due"
        assert msg["In-Reply-To"] == "<abc@mail>"
        assert msg["References"] == "<root@mail> <abc@mail>"
        assert "On it, paying today." in msg.get_payload()

    def test_does_not_double_re_prefix(self):
        raw = build_reply_mime(to="a@b.c", subject="Re: hello", body="hi", rfc_message_id="<x>", references="")
        assert self._decode(raw)["Subject"] == "Re: hello"

    def test_no_threading_headers_when_missing(self):
        raw = build_reply_mime(to="a@b.c", subject="hello", body="hi", rfc_message_id="", references="")
        msg = self._decode(raw)
        assert msg["In-Reply-To"] is None
        assert msg["References"] is None

def _decode(raw): return message_from_bytes(base64.urlsafe_b64decode(raw))

def test_build_mime_plain_body():
    from app.tools.gmail.client import build_mime
    msg = _decode(build_mime("r@x.com", "Hello", "Hi there"))
    assert msg["To"] == "r@x.com" and msg["Subject"] == "Hello"
    assert "Hi there" in msg.get_payload(decode=False) or msg.is_multipart()

def test_build_mime_with_attachment(tmp_path):
    from app.tools.gmail.client import build_mime
    f = tmp_path / "resume.pdf"; f.write_bytes(b"%PDF-1.4 fake")
    msg = _decode(build_mime("r@x.com", "Role", "See attached", attachments=[str(f)]))
    assert msg.is_multipart()
    names = [p.get_filename() for p in msg.walk() if p.get_filename()]
    assert "resume.pdf" in names

def test_build_mime_reply_prefixes_re_and_threads():
    from app.tools.gmail.client import build_mime
    msg = _decode(build_mime("r@x.com", "Question", "Reply", in_reply_to="<m1@x>", references="<m0@x>"))
    assert msg["Subject"].lower().startswith("re:")
    assert msg["In-Reply-To"] == "<m1@x>"

def test_compose_scope_present():
    from app.tools.gmail.client import SCOPES
    assert any("gmail.compose" in s for s in SCOPES)
