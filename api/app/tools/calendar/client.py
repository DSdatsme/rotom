"""Google Calendar access: multi-account, primary calendar only.

Auth model: same OAuth client + refresh token per account as tools/gmail/client.py — the
token now covers both Gmail and Calendar scopes (see tools/gmail/auth_setup.py). Scope is
calendar.events (read/write) rather than calendar.readonly so a future create/update-event
feature needs no further re-auth, even though this module only reads in v1.
"""

import logging
import os
from datetime import datetime

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


class CalendarAccount:
    """One authenticated account's primary calendar."""

    def __init__(self, account: str, client_id: str, client_secret: str, refresh_token: str):
        self.account = account
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
            self._service = build("calendar", "v3", credentials=self._creds, cache_discovery=False)
        return self._service

    def list_events(self, time_min: datetime, time_max: datetime) -> list[dict]:
        """Raw Calendar API event resources for the primary calendar in [time_min, time_max)."""
        result = (
            self.service.events()
            .list(
                calendarId="primary",
                timeMin=time_min.isoformat(),
                timeMax=time_max.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        return result.get("items", [])


def load_accounts(settings) -> list[CalendarAccount]:
    """Build CalendarAccount instances from the same GMAIL_<NAME>_REFRESH_TOKEN env vars
    tools/gmail/client.py uses — one shared per-account token, now scoped for Calendar too."""
    accounts = []
    extras = settings.model_extra or {}
    for name in settings.account_names:
        env_key = f"GMAIL_{name.upper().replace('-', '_')}_REFRESH_TOKEN"
        token = os.environ.get(env_key, "") or str(extras.get(env_key.lower(), "") or "")
        if not token:
            logger.warning("No refresh token for calendar account %r (missing %s); skipping", name, env_key)
            continue
        accounts.append(CalendarAccount(name, settings.gmail_client_id, settings.gmail_client_secret, token))
    return accounts
