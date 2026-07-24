# Calendar Integration (Dashboard Week View) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new `/calendar` dashboard page showing a Google-Calendar-style week grid that merges
events from every Gmail-linked account's primary calendar, live-fetched from the Google Calendar
API on every page load/navigation.

**Architecture:** `api/app/tools/calendar/` mirrors the existing `tools/gmail/` multi-account
pattern (same refresh token per account, now scoped for Calendar too) — a `client.py` for
per-account Calendar API access and a `service.py` that merges + sorts + resiliently handles
per-account failures. One new FastAPI route returns merged JSON; the dashboard renders it as an
absolutely-positioned hour-by-day grid. No new DB table, no cron job, no caching.

**Tech Stack:** FastAPI (existing `google-api-python-client`/`google-auth` — no new dependency),
pytest with faked Calendar responses, Next.js 16 App Router server component + Tailwind/Base UI.

Spec: `docs/superpowers/specs/2026-07-25-calendar-integration-design.md`

## Global Constraints

- No new pip/npm dependencies — `google-api-python-client`, `google-auth`, `google-auth-oauthlib`
  are already in `api/pyproject.toml` (used by `tools/gmail/`).
- No new DB table, no new APScheduler cron job — every request is a live Calendar API fetch.
- Reuse `GMAIL_<NAME>_REFRESH_TOKEN` env vars — no new per-account config. The OAuth scope
  granted is `https://www.googleapis.com/auth/calendar.events` (covers a future write feature
  with zero further re-auth), even though v1 code only reads.
- One event loop (`AGENTS.md`): every blocking Google SDK call in a route handler must go through
  `await asyncio.to_thread(...)` — never called directly from `async def`. All routes in
  `api/app/api/routes.py` are `async def`; follow that, don't introduce a lone `sync def` route.
- JSON field names are snake_case end-to-end, matching every existing `web/lib/api.ts` interface
  (`to_addr`, `gmail_draft_id`, `fire_at`, etc.) — no camelCase translation layer.
- No frontend unit test framework exists in `web/` — frontend tasks are verified with
  `npm run lint` plus a manual browser pass, not automated tests.
- Never add an AI co-author / "Co-Authored-By" line to any commit (repo-wide rule).
- **Deviation from the written spec, flagged for visibility:** the spec's §4.3 described
  `start`/`end` as always-required query params with the frontend computing "today" itself.
  This plan makes both **optional**, with the **backend** computing "today's week" using
  `settings.timezone` and echoing the resolved `range_start`/`range_end` back in the response.
  Reason: this repo already has a known, unresolved bug (`TODO.md`'s "UTC-correct timestamps"
  item) from computing "now" in JS with the wrong timezone assumption; keeping all
  timezone-sensitive date math in Python (which already does this correctly elsewhere via
  `zoneinfo`) avoids repeating that exact mistake. The frontend only ever does timezone-agnostic
  calendar-date arithmetic (add/subtract N days on a `YYYY-MM-DD` string), never "what is today."

---

### Task 1: `tools/calendar/client.py` — per-account Calendar API access

**Files:**
- Create: `api/app/tools/calendar/__init__.py` (empty, matches `api/app/tools/gmail/__init__.py`)
- Create: `api/app/tools/calendar/client.py`
- Test: `api/tests/test_calendar_client.py`

**Interfaces:**
- Produces: `CalendarAccount(account: str, client_id: str, client_secret: str, refresh_token: str)`
  with `.account: str` and `.list_events(time_min: datetime, time_max: datetime) -> list[dict]`
  (raw Calendar API event resources). `load_accounts(settings) -> list[CalendarAccount]`.
  `SCOPES: list[str]`.

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_calendar_client.py
"""Tests for Calendar API account loading and event fetching."""

from datetime import datetime, timezone


class _FakeEventsList:
    def __init__(self, items):
        self._items = items

    def execute(self):
        return {"items": self._items}


class _FakeEvents:
    def __init__(self, items, captured):
        self._items = items
        self._captured = captured

    def list(self, **kwargs):
        self._captured.update(kwargs)
        return _FakeEventsList(self._items)


class _FakeService:
    def __init__(self, items, captured):
        self._items = items
        self._captured = captured

    def events(self):
        return _FakeEvents(self._items, self._captured)


def test_calendar_scope_present():
    from app.tools.calendar.client import SCOPES

    assert any("calendar.events" in s for s in SCOPES)


def test_list_events_passes_time_range_and_returns_items():
    from app.tools.calendar.client import CalendarAccount

    acc = CalendarAccount("work", "cid", "sec", "tok")
    captured: dict = {}
    acc._service = _FakeService([{"id": "e1"}], captured)

    time_min = datetime(2026, 7, 28, tzinfo=timezone.utc)
    time_max = datetime(2026, 8, 4, tzinfo=timezone.utc)
    events = acc.list_events(time_min, time_max)

    assert events == [{"id": "e1"}]
    assert captured["calendarId"] == "primary"
    assert captured["timeMin"] == time_min.isoformat()
    assert captured["timeMax"] == time_max.isoformat()
    assert captured["singleEvents"] is True
    assert captured["orderBy"] == "startTime"


class TestLoadAccounts:
    def test_token_from_dotenv_extras(self):
        from app.config import Settings
        from app.tools.calendar.client import load_accounts

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
        from app.tools.calendar.client import load_accounts

        monkeypatch.setenv("GMAIL_WORK_REFRESH_TOKEN", "tok-from-env")
        s = Settings(
            gmail_client_id="cid", gmail_client_secret="sec", gmail_accounts="work", _env_file=None
        )
        assert len(load_accounts(s)) == 1

    def test_missing_token_skipped(self):
        from app.config import Settings
        from app.tools.calendar.client import load_accounts

        s = Settings(
            gmail_client_id="cid", gmail_client_secret="sec", gmail_accounts="ghost", _env_file=None
        )
        assert load_accounts(s) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd api && uv run pytest tests/test_calendar_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.tools.calendar'`

- [ ] **Step 3: Write the implementation**

```python
# api/app/tools/calendar/__init__.py
```
(empty file)

```python
# api/app/tools/calendar/client.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && uv run pytest tests/test_calendar_client.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add api/app/tools/calendar/__init__.py api/app/tools/calendar/client.py api/tests/test_calendar_client.py
git commit -m "feat(calendar): add per-account Calendar API client"
```

---

### Task 2: `tools/calendar/service.py` — normalize, merge, sort across accounts

**Files:**
- Create: `api/app/tools/calendar/service.py`
- Test: `api/tests/test_calendar_service.py`

**Interfaces:**
- Consumes: `CalendarAccount` from Task 1 — only `.account: str` and
  `.list_events(time_min, time_max) -> list[dict]` are used, so tests fake it directly (no
  dependency on Task 1's test doubles).
- Produces: `list_events_for_range(accounts: list, time_min: datetime, time_max: datetime) ->
  tuple[list[dict], list[dict]]` returning `(events, errors)`. Each event dict:
  `{account, event_id, title, start, end, all_day, location}`. Each error dict:
  `{account, message}`.

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_calendar_service.py
"""Tests for merging/normalizing Calendar events across accounts."""

import pytest


class _FakeAccount:
    def __init__(self, account, events=None, error=None):
        self.account = account
        self._events = events or []
        self._error = error

    def list_events(self, time_min, time_max):
        if self._error:
            raise self._error
        return self._events


def _timed_event(event_id="e1", title="Standup", start="2026-07-28T09:00:00+05:30",
                  end="2026-07-28T09:30:00+05:30", location=None):
    ev = {"id": event_id, "summary": title,
          "start": {"dateTime": start}, "end": {"dateTime": end}}
    if location:
        ev["location"] = location
    return ev


def _all_day_event(event_id="e2", title="Diwali", start="2026-11-08", end="2026-11-09"):
    return {"id": event_id, "summary": title, "start": {"date": start}, "end": {"date": end}}


class TestNormalizeEvent:
    def test_timed_event(self):
        from app.tools.calendar.service import _normalize_event

        norm = _normalize_event(_timed_event(location="Downtown Clinic"), account="personal")
        assert norm == {
            "account": "personal", "event_id": "e1", "title": "Standup",
            "start": "2026-07-28T09:00:00+05:30", "end": "2026-07-28T09:30:00+05:30",
            "all_day": False, "location": "Downtown Clinic",
        }

    def test_all_day_event(self):
        from app.tools.calendar.service import _normalize_event

        norm = _normalize_event(_all_day_event(), account="personal")
        assert norm["all_day"] is True
        assert norm["start"] == "2026-11-08"
        assert norm["end"] == "2026-11-09"

    def test_missing_location_is_none(self):
        from app.tools.calendar.service import _normalize_event

        norm = _normalize_event(_timed_event(), account="personal")
        assert norm["location"] is None

    def test_missing_title_defaults(self):
        from app.tools.calendar.service import _normalize_event

        ev = {"id": "e3", "start": {"dateTime": "2026-07-28T09:00:00+05:30"},
              "end": {"dateTime": "2026-07-28T09:30:00+05:30"}}
        norm = _normalize_event(ev, account="personal")
        assert norm["title"] == "(no title)"


class TestListEventsForRange:
    def test_merges_and_sorts_across_accounts(self):
        from app.tools.calendar.service import list_events_for_range

        accounts = [
            _FakeAccount("work", events=[_timed_event(event_id="w1", start="2026-07-28T13:00:00+05:30",
                                                        end="2026-07-28T14:00:00+05:30")]),
            _FakeAccount("personal", events=[_timed_event(event_id="p1", start="2026-07-28T09:00:00+05:30",
                                                            end="2026-07-28T09:30:00+05:30")]),
        ]
        events, errors = list_events_for_range(accounts, None, None)
        assert errors == []
        assert [e["event_id"] for e in events] == ["p1", "w1"]  # sorted by start, not account order
        assert [e["account"] for e in events] == ["personal", "work"]

    def test_one_account_error_does_not_drop_others(self):
        from app.tools.calendar.service import list_events_for_range

        accounts = [
            _FakeAccount("broken", error=RuntimeError("token expired")),
            _FakeAccount("ok", events=[_timed_event(event_id="ok1")]),
        ]
        events, errors = list_events_for_range(accounts, None, None)
        assert [e["event_id"] for e in events] == ["ok1"]
        assert errors == [{"account": "broken", "message": "token expired"}]

    def test_empty_accounts_returns_empty(self):
        from app.tools.calendar.service import list_events_for_range

        assert list_events_for_range([], None, None) == ([], [])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd api && uv run pytest tests/test_calendar_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.tools.calendar.service'`

- [ ] **Step 3: Write the implementation**

```python
# api/app/tools/calendar/service.py
"""Merge calendar events across all accounts into one sorted, resilient list."""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def _normalize_event(raw: dict, account: str) -> dict:
    """Flatten a Calendar API event resource into a flat display dict.

    All-day events carry date-only start/end (Google's end.date is exclusive of the last
    day — multi-day all-day spanning is not rendered in v1, only the start day)."""
    start = raw.get("start", {})
    end = raw.get("end", {})
    all_day = "date" in start and "dateTime" not in start
    return {
        "account": account,
        "event_id": raw.get("id", ""),
        "title": raw.get("summary") or "(no title)",
        "start": start.get("date") if all_day else start.get("dateTime", ""),
        "end": end.get("date") if all_day else end.get("dateTime", ""),
        "all_day": all_day,
        "location": raw.get("location") or None,
    }


def list_events_for_range(accounts: list, time_min: datetime, time_max: datetime) -> tuple[list[dict], list[dict]]:
    """Fetch + normalize + merge + sort events across all accounts.

    Never raises: one account's failure is caught, logged, and reported in the returned
    errors list — the other accounts' events are still returned.
    """
    events: list[dict] = []
    errors: list[dict] = []
    for acc in accounts:
        try:
            raw_events = acc.list_events(time_min, time_max)
        except Exception as exc:
            logger.exception("calendar fetch failed for account %r", acc.account)
            errors.append({"account": acc.account, "message": str(exc)})
            continue
        events.extend(_normalize_event(e, acc.account) for e in raw_events)
    events.sort(key=lambda e: e["start"])
    return events, errors
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && uv run pytest tests/test_calendar_service.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add api/app/tools/calendar/service.py api/tests/test_calendar_service.py
git commit -m "feat(calendar): merge and normalize events across accounts"
```

---

### Task 3: Extend OAuth scopes for re-auth (`tools/gmail/auth_setup.py`)

**Files:**
- Modify: `api/app/tools/gmail/auth_setup.py`
- Test: `api/tests/test_gmail_client.py` (add one test to the existing file)

**Interfaces:**
- Consumes: `SCOPES` from `app.tools.gmail.client` (existing) and `SCOPES` from
  `app.tools.calendar.client` (Task 1).
- Produces: `auth_setup.SCOPES` — the combined list used by the one-time OAuth consent flow.

- [ ] **Step 1: Write the failing test**

Add to the bottom of `api/tests/test_gmail_client.py` (same file that already has
`test_compose_scope_present`, keeping all scope-list assertions together):

```python
def test_auth_setup_requests_calendar_scope_too():
    from app.tools.gmail.auth_setup import SCOPES

    assert any("gmail.readonly" in s for s in SCOPES)
    assert any("calendar.events" in s for s in SCOPES)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && uv run pytest tests/test_gmail_client.py::test_auth_setup_requests_calendar_scope_too -v`
Expected: FAIL — `auth_setup.SCOPES` doesn't yet include the calendar scope (currently
`auth_setup.py` only re-exports `gmail.client.SCOPES`).

- [ ] **Step 3: Write the implementation**

In `api/app/tools/gmail/auth_setup.py`, replace the import line:

```python
from app.tools.gmail.client import SCOPES
```

with:

```python
from app.tools.calendar.client import SCOPES as CALENDAR_SCOPES
from app.tools.gmail.client import SCOPES as GMAIL_SCOPES

SCOPES = GMAIL_SCOPES + CALENDAR_SCOPES
```

Also update the module docstring's second line to mention both scopes are requested, and the
final printed instructions stay accurate (the refresh token now grants Gmail + Calendar
access). Full updated file:

```python
"""One-time OAuth setup per account (Gmail + Calendar share one refresh token).

Run locally (opens a browser for consent):

    uv run python -m app.tools.gmail.auth_setup <account-name>

Prints the GMAIL_<NAME>_REFRESH_TOKEN line to add to your .env.
Requires GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET in the environment or .env.
"""

import sys

from google_auth_oauthlib.flow import InstalledAppFlow

from app.config import get_settings
from app.tools.calendar.client import SCOPES as CALENDAR_SCOPES
from app.tools.gmail.client import SCOPES as GMAIL_SCOPES

SCOPES = GMAIL_SCOPES + CALENDAR_SCOPES


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python -m app.tools.gmail.auth_setup <account-name>")
        sys.exit(1)
    account = sys.argv[1]
    settings = get_settings()
    if not settings.gmail_client_id or not settings.gmail_client_secret:
        print("GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET must be set (env or .env)")
        sys.exit(1)

    flow = InstalledAppFlow.from_client_config(
        {
            "installed": {
                "client_id": settings.gmail_client_id,
                "client_secret": settings.gmail_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        },
        scopes=SCOPES,
    )
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    env_name = account.upper().replace("-", "_")
    print(f"\nAdd this to your .env:\n\nGMAIL_{env_name}_REFRESH_TOKEN={creds.refresh_token}\n")
    print(f'And ensure "{account}" is listed in GMAIL_ACCOUNTS.')


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && uv run pytest tests/test_gmail_client.py -v`
Expected: PASS (all existing tests + the new one, including `test_compose_scope_present` still
passing since `gmail.client.SCOPES` itself is untouched)

- [ ] **Step 5: Commit**

```bash
git add api/app/tools/gmail/auth_setup.py api/tests/test_gmail_client.py
git commit -m "feat(calendar): request calendar.events scope during account re-auth"
```

**Operational note (not a code step):** each account needs a one-time manual re-auth —
`cd api && uv run python -m app.tools.gmail.auth_setup <account-name>` — before its calendar
will actually return data. Until an account is re-authed, `list_events` will fail for it with an
auth error, which Task 2's `list_events_for_range` already turns into a per-account entry in
`errors` rather than a crash.

---

### Task 4: `GET /api/calendar/events` route

**Files:**
- Modify: `api/app/api/routes.py`
- Test: `api/tests/test_calendar_route.py`

**Interfaces:**
- Consumes: `app.tools.calendar.client.load_accounts` (Task 1),
  `app.tools.calendar.service.list_events_for_range` (Task 2).
- Produces: `GET /api/calendar/events?start=YYYY-MM-DD&end=YYYY-MM-DD` (both optional),
  bearer-gated, returning
  `{"range_start": "YYYY-MM-DD", "range_end": "YYYY-MM-DD", "events": [...], "errors": [...]}`.

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_calendar_route.py
"""Tests for GET /api/calendar/events."""

import pytest
from fastapi.testclient import TestClient

from app.api.routes import create_app

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class _FakeAccount:
    def __init__(self, account, events=None, error=None):
        self.account = account
        self._events = events or []
        self._error = error

    def list_events(self, time_min, time_max):
        if self._error:
            raise self._error
        return self._events


def _timed_event(event_id, title, start, end):
    return {"id": event_id, "summary": title, "start": {"dateTime": start}, "end": {"dateTime": end}}


@pytest.fixture()
def client(session_db):
    app = create_app(api_token=TOKEN)
    return TestClient(app)


def test_requires_auth(client):
    assert client.get("/api/calendar/events?start=2026-07-28&end=2026-07-28").status_code == 401


def test_merges_accounts_for_explicit_range(client, monkeypatch):
    monkeypatch.setattr(
        "app.tools.calendar.client.load_accounts",
        lambda settings: [
            _FakeAccount("work", events=[_timed_event("w1", "Standup",
                          "2026-07-28T09:00:00+05:30", "2026-07-28T09:30:00+05:30")]),
            _FakeAccount("personal", events=[_timed_event("p1", "Dentist",
                          "2026-07-28T13:00:00+05:30", "2026-07-28T14:00:00+05:30")]),
        ],
    )
    resp = client.get("/api/calendar/events?start=2026-07-28&end=2026-07-28", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["range_start"] == "2026-07-28"
    assert body["range_end"] == "2026-07-28"
    assert [e["account"] for e in body["events"]] == ["work", "personal"]
    assert body["errors"] == []


def test_one_account_error_is_reported_not_fatal(client, monkeypatch):
    monkeypatch.setattr(
        "app.tools.calendar.client.load_accounts",
        lambda settings: [
            _FakeAccount("broken", error=RuntimeError("token expired")),
            _FakeAccount("ok", events=[_timed_event("ok1", "Standup",
                          "2026-07-28T09:00:00+05:30", "2026-07-28T09:30:00+05:30")]),
        ],
    )
    resp = client.get("/api/calendar/events?start=2026-07-28&end=2026-07-28", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["events"]) == 1
    assert body["errors"] == [{"account": "broken", "message": "token expired"}]


def test_no_params_defaults_to_current_week_monday_start(client, monkeypatch):
    monkeypatch.setattr("app.tools.calendar.client.load_accounts", lambda settings: [])
    resp = client.get("/api/calendar/events", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    from datetime import date
    assert date.fromisoformat(body["range_start"]).weekday() == 0  # Monday
    assert (date.fromisoformat(body["range_end"]) - date.fromisoformat(body["range_start"])).days == 6


def test_arbitrary_start_snaps_to_containing_week(client, monkeypatch):
    monkeypatch.setattr("app.tools.calendar.client.load_accounts", lambda settings: [])
    # 2026-07-30 is a Thursday; the containing week starts Monday 2026-07-27.
    resp = client.get("/api/calendar/events?start=2026-07-30", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["range_start"] == "2026-07-27"
    assert body["range_end"] == "2026-08-02"


def test_bad_date_is_422(client):
    resp = client.get("/api/calendar/events?start=not-a-date&end=2026-07-28", headers=AUTH)
    assert resp.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd api && uv run pytest tests/test_calendar_route.py -v`
Expected: FAIL with 404 (route doesn't exist yet)

- [ ] **Step 3: Write the implementation**

In `api/app/api/routes.py`, add this route inside `create_app`, immediately after the existing
`cancel_reminder_route` handler (around line 618, right before the `SoulUpdate` class) so
Calendar sits next to Reminders — both are "Workspace" nav items:

```python
    @app.get("/api/calendar/events", dependencies=[Depends(require_auth)])
    async def get_calendar_events(start: str | None = None, end: str | None = None) -> dict:
        import asyncio
        from zoneinfo import ZoneInfo

        from app.config import get_settings
        from app.tools.calendar.client import load_accounts as load_calendar_accounts
        from app.tools.calendar.service import list_events_for_range

        settings = get_settings()
        zone = ZoneInfo(settings.timezone)

        range_start = _parse_date(start).date() if start else datetime.now(zone).date()
        range_start -= timedelta(days=range_start.weekday())  # snap back to the week's Monday
        range_end = _parse_date(end).date() if end else range_start + timedelta(days=6)

        time_min = datetime.combine(range_start, datetime.min.time(), tzinfo=zone)
        time_max = datetime.combine(range_end + timedelta(days=1), datetime.min.time(), tzinfo=zone)

        accounts = load_calendar_accounts(settings)
        events, errors = await asyncio.to_thread(list_events_for_range, accounts, time_min, time_max)
        return {
            "range_start": range_start.isoformat(),
            "range_end": range_end.isoformat(),
            "events": events,
            "errors": errors,
        }
```

This reuses the existing `_parse_date` helper (defined earlier in `create_app`, already used by
the `/api/emails` date filters) for 422-on-bad-date behavior — no new date-parsing helper needed.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && uv run pytest tests/test_calendar_route.py -v`
Expected: PASS (6 tests)

Then run the full backend suite to confirm nothing else broke:
Run: `cd api && uv run pytest -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add api/app/api/routes.py api/tests/test_calendar_route.py
git commit -m "feat(calendar): add GET /api/calendar/events route"
```

---

### Task 5: Frontend API client + nav entry

**Files:**
- Modify: `web/lib/api.ts`
- Modify: `web/lib/nav.ts`

**Interfaces:**
- Produces: `CalendarEvent`, `CalendarEventsResponse` types and `getCalendarEvents(start？:
  string, end?: string) => Promise<CalendarEventsResponse>` for Task 6 to consume. Adds a
  `"Calendar"` entry to `NAV_SECTIONS` under the existing `"Workspace"` group (alongside
  `"Reminders"`), `href: "/calendar"`.

- [ ] **Step 1: Add the API client function**

Append to `web/lib/api.ts` (after the reminders section, before `getSoul`):

```ts
// --- calendar ---

export interface CalendarEvent {
  account: string;
  event_id: string;
  title: string;
  start: string;
  end: string;
  all_day: boolean;
  location: string | null;
}

export interface CalendarEventsResponse {
  range_start: string;
  range_end: string;
  events: CalendarEvent[];
  errors: { account: string; message: string }[];
}

export const getCalendarEvents = (start?: string, end?: string) => {
  const params = new URLSearchParams();
  if (start) params.set("start", start);
  if (end) params.set("end", end);
  const qs = params.toString();
  return apiFetch<CalendarEventsResponse>(`/api/calendar/events${qs ? `?${qs}` : ""}`);
};
```

- [ ] **Step 2: Add the nav entry**

In `web/lib/nav.ts`, change the `"Workspace"` section:

```ts
  { label: "Workspace", items: [{ title: "Reminders", href: "/reminders", icon: "Bell" }] },
```

to:

```ts
  {
    label: "Workspace",
    items: [
      { title: "Reminders", href: "/reminders", icon: "Bell" },
      { title: "Calendar", href: "/calendar", icon: "Calendar" },
    ],
  },
```

(`"Calendar"` is a valid `lucide-react` icon export, matching how other entries reference icon
names — see `Icon` usage in `app-sidebar.tsx`.)

- [ ] **Step 3: Verify — typecheck and lint**

Run: `cd web && npm run lint`
Expected: no errors (the new nav entry references `/calendar`, which doesn't exist until Task 6
— that's fine, Next.js `Link` doesn't require the target route to exist at lint time)

- [ ] **Step 4: Commit**

```bash
git add web/lib/api.ts web/lib/nav.ts
git commit -m "feat(calendar): add calendar API client and nav entry"
```

---

### Task 6: Calendar page + week grid

**Files:**
- Create: `web/lib/calendar-colors.ts`
- Create: `web/components/calendar-grid.tsx`
- Create: `web/app/calendar/page.tsx`

**Interfaces:**
- Consumes: `getCalendarEvents`, `CalendarEvent`, `CalendarEventsResponse` from Task 5.
- Produces: the `/calendar` route, rendering `<CalendarGrid weekStart={string}
  events={CalendarEvent[]} />`.

- [ ] **Step 1: Write the per-account color helper**

```ts
// web/lib/calendar-colors.ts
const PALETTE = [
  "bg-blue-500/15 text-blue-700 dark:text-blue-300",
  "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  "bg-fuchsia-500/15 text-fuchsia-700 dark:text-fuchsia-300",
  "bg-cyan-500/15 text-cyan-700 dark:text-cyan-300",
];

/** Deterministic color per account name, so the same account always renders the same color. */
export function colorForAccount(account: string): string {
  let hash = 0;
  for (let i = 0; i < account.length; i++) {
    hash = (hash * 31 + account.charCodeAt(i)) % PALETTE.length;
  }
  return PALETTE[hash];
}
```

- [ ] **Step 2: Write the grid component**

```tsx
// web/components/calendar-grid.tsx
import type { CalendarEvent } from "@/lib/api";
import { colorForAccount } from "@/lib/calendar-colors";

const HOUR_HEIGHT = 48; // px per hour row
const DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function dateForDayOffset(weekStart: string, offset: number): string {
  const d = new Date(`${weekStart}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + offset);
  return d.toISOString().slice(0, 10);
}

// Read the wall-clock time straight out of the ISO string's own text — never construct a
// Date and call .getHours(), which would reinterpret it in the server's local timezone.
function minutesSinceMidnight(iso: string): number {
  const [h, m] = iso.slice(11, 16).split(":").map(Number);
  return h * 60 + m;
}

export function CalendarGrid({ weekStart, events }: { weekStart: string; events: CalendarEvent[] }) {
  const days = Array.from({ length: 7 }, (_, i) => dateForDayOffset(weekStart, i));

  const timedByDay = new Map<string, CalendarEvent[]>();
  const allDayByDay = new Map<string, CalendarEvent[]>();
  for (const day of days) {
    timedByDay.set(day, []);
    allDayByDay.set(day, []);
  }
  for (const ev of events) {
    const day = ev.start.slice(0, 10);
    const bucket = ev.all_day ? allDayByDay : timedByDay;
    bucket.get(day)?.push(ev);
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <div className="grid grid-cols-[3.5rem_repeat(7,1fr)] border-b border-border">
        <div />
        {days.map((day, i) => (
          <div key={day} className="border-l border-border px-2 py-2 text-center text-sm font-medium">
            {DAY_LABELS[i]} <span className="text-muted-foreground">{day.slice(5)}</span>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-[3.5rem_repeat(7,1fr)] border-b border-border">
        <div className="px-2 py-1 text-right text-xs text-muted-foreground">All day</div>
        {days.map((day) => (
          <div key={day} className="flex flex-col gap-1 border-l border-border p-1">
            {allDayByDay.get(day)!.map((ev) => (
              <span
                key={`${ev.account}-${ev.event_id}`}
                className={`truncate rounded px-1.5 py-0.5 text-xs ${colorForAccount(ev.account)}`}
                title={`${ev.title} (${ev.account})`}
              >
                {ev.title}
              </span>
            ))}
          </div>
        ))}
      </div>

      <div className="grid grid-cols-[3.5rem_repeat(7,1fr)]">
        <div>
          {Array.from({ length: 24 }, (_, h) => (
            <div
              key={h}
              style={{ height: HOUR_HEIGHT }}
              className="border-t border-border px-2 text-right text-xs text-muted-foreground"
            >
              {h === 0 ? "" : `${h}:00`}
            </div>
          ))}
        </div>
        {days.map((day) => (
          <div key={day} className="relative border-l border-border">
            {Array.from({ length: 24 }, (_, h) => (
              <div key={h} style={{ height: HOUR_HEIGHT }} className="border-t border-border" />
            ))}
            {timedByDay.get(day)!.map((ev) => {
              const startMin = minutesSinceMidnight(ev.start);
              let durationMin = minutesSinceMidnight(ev.end) - startMin;
              if (durationMin <= 0) durationMin = 24 * 60 - startMin; // crosses midnight: simplify to day's end
              const top = (startMin / 60) * HOUR_HEIGHT;
              const height = Math.max((durationMin / 60) * HOUR_HEIGHT, 18);
              return (
                <div
                  key={`${ev.account}-${ev.event_id}`}
                  className={`absolute right-0.5 left-0.5 overflow-hidden rounded px-1 text-xs ${colorForAccount(ev.account)}`}
                  style={{ top, height }}
                  title={`${ev.title} (${ev.account})${ev.location ? " · " + ev.location : ""}`}
                >
                  {ev.title}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Write the page**

```tsx
// web/app/calendar/page.tsx
import Link from "next/link";

import { getCalendarEvents } from "@/lib/api";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { CalendarGrid } from "@/components/calendar-grid";

export const dynamic = "force-dynamic";

function addDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

export default async function CalendarPage({
  searchParams,
}: {
  searchParams: Promise<{ start?: string }>;
}) {
  const { start } = await searchParams;
  let data;
  try {
    data = await getCalendarEvents(start);
  } catch (e) {
    return (
      <Alert variant="destructive">
        <AlertTitle>API unreachable</AlertTitle>
        <AlertDescription>{e instanceof Error ? e.message : "unknown error"}</AlertDescription>
      </Alert>
    );
  }

  const { range_start, range_end, events, errors } = data;
  const prevStart = addDays(range_start, -7);
  const nextStart = addDays(range_start, 7);

  return (
    <div className="flex min-h-[calc(100vh-6rem)] flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Calendar</h1>
          <p className="text-sm text-muted-foreground">
            {range_start} – {range_end} · merged across all accounts
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" render={<Link href={`/calendar?start=${prevStart}`} />}>
            ← Prev
          </Button>
          <Button variant="outline" size="sm" render={<Link href="/calendar" />}>
            Today
          </Button>
          <Button variant="outline" size="sm" render={<Link href={`/calendar?start=${nextStart}`} />}>
            Next →
          </Button>
        </div>
      </div>

      {errors.length > 0 && (
        <Alert variant="destructive">
          <AlertTitle>Some accounts couldn&apos;t be loaded</AlertTitle>
          <AlertDescription>
            {errors.map((e) => `${e.account}: ${e.message}`).join(" · ")}
          </AlertDescription>
        </Alert>
      )}

      <CalendarGrid weekStart={range_start} events={events} />
    </div>
  );
}
```

- [ ] **Step 4: Verify — lint, build, and manual browser check**

Run: `cd web && npm run lint`
Expected: no errors

Run: `make dev` (or `cd api && uv run python -m app.main` + `cd web && npm run dev` in separate
terminals), then in a browser:
1. Navigate to `http://localhost:3000/calendar` (or `:3001` if `:3000` is taken).
2. With **no accounts re-authed yet** (Task 3's operational step not yet done), confirm the page
   still renders — an empty grid plus an error banner naming each configured account (since
   `list_events` will fail with an auth error for every account until re-auth happens). This is
   the expected degraded state, not a bug.
3. Confirm Prev / Today / Next change the URL's `?start=` and the header date range updates.
4. **After** re-authing at least one account (`uv run python -m app.tools.gmail.auth_setup
   <account>`, update `.env`, restart the API), reload `/calendar` and confirm real events
   appear positioned at the correct hour and colored consistently per account.

- [ ] **Step 5: Commit**

```bash
git add web/lib/calendar-colors.ts web/components/calendar-grid.tsx web/app/calendar/page.tsx
git commit -m "feat(calendar): add dashboard week view"
```

---

### Task 7: Docs — `TODO.md` and `AGENTS.md`

**Files:**
- Modify: `TODO.md`
- Modify: `AGENTS.md`

- [ ] **Step 1: Update `TODO.md`**

Replace the existing Calendar bullet (under "Iteration 4 — More tools"):

```markdown
- [ ] **Calendar** (`tools/calendar/`): interact with Google Calendar for the same Gmail
      accounts — read upcoming events / agenda into digests, create/update events from chat
      with a HITL gate (writes always confirmed). Reuses the existing per-account OAuth
      (add the `calendar`/`calendar.events` scope → triggers a per-account re-auth, same as
      the draft-composer `gmail.compose` change). Multi-account, like triage. Brainstorm
      before building.
```

with:

```markdown
- [x] **Calendar v1 — dashboard week view** (`tools/calendar/`): merged read-only week grid
      across all Gmail-linked accounts' primary calendars, live-fetched from the Calendar API
      (no caching/sync job). Scope granted is `calendar.events` (read/write), so Calendar V2
      needs no further re-auth. Spec:
      `docs/superpowers/specs/2026-07-25-calendar-integration-design.md`.
  - [ ] **Calendar V2** — create/update events from chat with a HITL gate; secondary/shared
        calendars beyond each account's primary; per-account opt-out; fold today's agenda into
        the Telegram digest or expose it as a chat tool.
```

- [ ] **Step 2: Update `AGENTS.md`**

In the repo layout block, change:

```
    tools/gmail/          # client, pipeline (fetch→dedup→classify→store→digest→draft), injection
    tools/reminders/      # NL recurrence → cron
```

to:

```
    tools/gmail/          # client, pipeline (fetch→dedup→classify→store→digest→draft), injection
    tools/calendar/       # multi-account week-view event fetch (read-only v1; scope already covers a future write feature)
    tools/reminders/      # NL recurrence → cron
```

- [ ] **Step 3: Commit**

```bash
git add TODO.md AGENTS.md
git commit -m "docs: record calendar v1 as shipped, defer v2 items"
```
