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
