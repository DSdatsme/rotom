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

    def list_events(self, time_min, time_max, tz_name):
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


def test_timezone_boundary_conversion_for_non_utc_settings_timezone(client, monkeypatch):
    """A given start/end day range must convert to the correct UTC-offset time_min/time_max
    for the configured (non-UTC) settings.timezone — default is Asia/Kolkata, +05:30."""
    from app.config import get_settings

    assert get_settings().timezone == "Asia/Kolkata"

    captured: dict = {}

    class _CapturingAccount:
        account = "personal"

        def list_events(self, time_min, time_max, tz_name):
            captured["time_min"] = time_min
            captured["time_max"] = time_max
            captured["tz_name"] = tz_name
            return []

    monkeypatch.setattr(
        "app.tools.calendar.client.load_accounts", lambda settings: [_CapturingAccount()]
    )
    resp = client.get("/api/calendar/events?start=2026-07-27&end=2026-08-02", headers=AUTH)
    assert resp.status_code == 200

    assert captured["tz_name"] == "Asia/Kolkata"
    assert captured["time_min"].isoformat() == "2026-07-27T00:00:00+05:30"
    # end is inclusive, so time_max is midnight of the day AFTER end
    assert captured["time_max"].isoformat() == "2026-08-03T00:00:00+05:30"
