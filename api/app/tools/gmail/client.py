"""Gmail access: multi-account fetch of unread mail and threaded reply sending.

Auth model (same pattern as gmail-summarizer): one OAuth client app,
one refresh token per account from `auth_setup.py`.
Scopes: gmail.readonly (fetch) + gmail.send (replies sent from the dashboard).
"""

import base64
import logging
import os
import time
from datetime import datetime, timezone
import mimetypes
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.mime.text import MIMEText

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose",
]

BODY_LIMIT = 4000  # chars of body text kept for classification/drafting


def build_query(lookback_hours: int, now: int | None = None) -> str:
    """Gmail search query for triage: unread inbox mail within the lookback window.

    Gmail's `newer_than:` only supports day granularity, so hour-level lookback
    uses `after:` with a unix timestamp instead.
    """
    after = (now if now is not None else int(time.time())) - lookback_hours * 3600
    return f"in:inbox after:{after}"


def _decode_part(data: str) -> str:
    return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")


def _extract_text(payload: dict) -> str:
    """Pull the best-effort plain-text body out of a Gmail payload tree."""
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return _decode_part(payload["body"]["data"])
    for part in payload.get("parts", []) or []:
        text = _extract_text(part)
        if text:
            return text
    return ""


def parse_message(detail: dict, account: str, body_limit: int = BODY_LIMIT) -> dict:
    """Normalize a Gmail API messages.get response into a flat email dict."""
    payload = detail.get("payload", {})
    headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
    received_at = None
    if detail.get("internalDate"):
        received_at = datetime.fromtimestamp(int(detail["internalDate"]) / 1000, tz=timezone.utc)
    return {
        "account": account,
        "message_id": detail.get("id", ""),
        "thread_id": detail.get("threadId", ""),
        "sender": headers.get("from", ""),
        "subject": headers.get("subject", ""),
        "snippet": detail.get("snippet", ""),
        "body": _extract_text(payload)[:body_limit],
        "rfc_message_id": headers.get("message-id", ""),
        "references": headers.get("references", ""),
        "received_at": received_at,
    }


def build_mime(to, subject, body, attachments=(), in_reply_to="", references="", footer_url=""):
    if subject and not subject.lower().startswith("re:") and in_reply_to:
        subject = f"Re: {subject}"

    if footer_url:
        from app.tools.gmail.footer import plain_footer, html_body
        content = MIMEMultipart("alternative")
        content.attach(MIMEText(body + plain_footer(footer_url), "plain", "utf-8"))
        content.attach(MIMEText(html_body(body, footer_url), "html", "utf-8"))
    else:
        content = MIMEText(body)

    if attachments:
        outer = MIMEMultipart()  # multipart/mixed
        outer.attach(content)
        for path in attachments:
            with open(path, "rb") as fh:
                part = MIMEApplication(fh.read(), Name=os.path.basename(path))
            part["Content-Disposition"] = f'attachment; filename="{os.path.basename(path)}"'
            outer.attach(part)
    else:
        outer = content

    outer["To"] = to
    outer["Subject"] = subject
    if in_reply_to:
        outer["In-Reply-To"] = in_reply_to
        outer["References"] = (f"{references} {in_reply_to}").strip() if in_reply_to not in references else references
    return base64.urlsafe_b64encode(outer.as_bytes()).decode()

def build_reply_mime(to: str, subject: str, body: str, rfc_message_id: str, references: str) -> str:
    """Build a base64url-encoded RFC 2822 reply, threaded onto the original message."""
    return build_mime(to, subject, body, in_reply_to=rfc_message_id, references=references)


class GmailAccount:
    """One authenticated Gmail account."""

    def __init__(self, account: str, client_id: str, client_secret: str, refresh_token: str,
                 lookback_hours: int = 48):
        self.account = account
        self.lookback_hours = lookback_hours
        self._creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            client_id=client_id,
            client_secret=client_secret,
            token_uri="https://oauth2.googleapis.com/token",
            scopes=SCOPES,
        )
        self._service = None

    @property
    def service(self):
        if self._service is None:
            self._creds.refresh(Request())
            self._service = build("gmail", "v1", credentials=self._creds, cache_discovery=False)
        return self._service

    def fetch_unread(self, max_results: int = 50) -> list[dict]:
        """Fetch unread inbox messages, newest first."""
        result = (
            self.service.users()
            .messages()
            .list(userId="me", q=build_query(self.lookback_hours), maxResults=max_results)
            .execute()
        )
        emails = []
        for ref in result.get("messages", []):
            detail = (
                self.service.users()
                .messages()
                .get(userId="me", id=ref["id"], format="full")
                .execute()
            )
            emails.append(parse_message(detail, account=self.account))
        return emails

    def send_reply(self, thread_id: str, to: str, subject: str, body: str,
                   rfc_message_id: str = "", references: str = "") -> dict:
        """Send a reply into an existing thread. Returns the Gmail API response."""
        return self.send_message(to, subject, body, thread_id=thread_id, in_reply_to=rfc_message_id, references=references)

    def send_message(self, to, subject, body, attachments=(), thread_id=None,
                     in_reply_to="", references="", footer_url=""):
        raw = build_mime(to, subject, body, attachments, in_reply_to, references, footer_url=footer_url)
        msg = {"raw": raw}
        if thread_id:
            msg["threadId"] = thread_id
        return self.service.users().messages().send(userId="me", body=msg).execute()

    def create_gmail_draft(self, to, subject, body, attachments=(), thread_id=None,
                           in_reply_to="", references="", gmail_draft_id=None, footer_url=""):
        from googleapiclient.errors import HttpError
        raw = build_mime(to, subject, body, attachments, in_reply_to, references, footer_url=footer_url)
        message = {"raw": raw}
        if thread_id:
            message["threadId"] = thread_id
        body_obj = {"message": message}
        drafts = self.service.users().drafts()
        if gmail_draft_id:
            try:
                return drafts.update(userId="me", id=gmail_draft_id, body=body_obj).execute()
            except HttpError as e:
                if e.resp.status == 404:
                    return drafts.create(userId="me", body=body_obj).execute()
                raise
        return drafts.create(userId="me", body=body_obj).execute()

    def delete_gmail_draft(self, gmail_draft_id):
        self.service.users().drafts().delete(userId="me", id=gmail_draft_id).execute()


def load_accounts(settings) -> list[GmailAccount]:
    """Build GmailAccount instances from settings + GMAIL_<NAME>_REFRESH_TOKEN env vars."""
    accounts = []
    extras = settings.model_extra or {}
    for name in settings.account_names:
        env_key = f"GMAIL_{name.upper().replace('-', '_')}_REFRESH_TOKEN"
        # Real env vars win (docker/CI); fall back to .env-file extras (local).
        token = os.environ.get(env_key, "") or str(extras.get(env_key.lower(), "") or "")
        if not token:
            logger.warning("No refresh token for account %r (missing %s); skipping", name, env_key)
            continue
        accounts.append(GmailAccount(name, settings.gmail_client_id, settings.gmail_client_secret, token,
                                     lookback_hours=settings.gmail_triage_lookback_hours))
    return accounts
