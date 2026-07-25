"""Tests for merging/normalizing Calendar events across accounts."""

import pytest


class _FakeAccount:
    def __init__(self, account, events=None, error=None):
        self.account = account
        self._events = events or []
        self._error = error

    def list_events(self, time_min, time_max, tz_name):
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
        events, errors = list_events_for_range(accounts, None, None, "Asia/Kolkata")
        assert errors == []
        assert [e["event_id"] for e in events] == ["p1", "w1"]  # sorted by start, not account order
        assert [e["account"] for e in events] == ["personal", "work"]

    def test_one_account_error_does_not_drop_others(self):
        from app.tools.calendar.service import list_events_for_range

        accounts = [
            _FakeAccount("broken", error=RuntimeError("token expired")),
            _FakeAccount("ok", events=[_timed_event(event_id="ok1")]),
        ]
        events, errors = list_events_for_range(accounts, None, None, "Asia/Kolkata")
        assert [e["event_id"] for e in events] == ["ok1"]
        assert errors == [{"account": "broken", "message": "token expired"}]

    def test_empty_accounts_returns_empty(self):
        from app.tools.calendar.service import list_events_for_range

        assert list_events_for_range([], None, None, "Asia/Kolkata") == ([], [])

    def test_sorts_by_absolute_instant_not_raw_string(self):
        from app.tools.calendar.service import list_events_for_range

        accounts = [
            # 05:00 UTC — string-sorts first ("...T05..." < "...T09...")
            _FakeAccount("a", events=[_timed_event(event_id="a1", start="2026-07-28T05:00:00+00:00",
                                                    end="2026-07-28T05:30:00+00:00")]),
            # 09:00+05:30 == 03:30 UTC — actually earlier in real time
            _FakeAccount("b", events=[_timed_event(event_id="b1", start="2026-07-28T09:00:00+05:30",
                                                    end="2026-07-28T09:30:00+05:30")]),
        ]
        events, errors = list_events_for_range(accounts, None, None, "Asia/Kolkata")
        assert errors == []
        assert [e["event_id"] for e in events] == ["b1", "a1"]

    def test_normalization_failure_for_one_account_does_not_drop_others(self):
        from app.tools.calendar.service import list_events_for_range

        accounts = [
            _FakeAccount("broken", events=[{"id": "bad", "start": None, "end": None}]),
            _FakeAccount("ok", events=[_timed_event(event_id="ok1")]),
        ]
        events, errors = list_events_for_range(accounts, None, None, "Asia/Kolkata")
        assert [e["event_id"] for e in events] == ["ok1"]
        assert len(errors) == 1
        assert errors[0]["account"] == "broken"

    def test_malformed_start_does_not_crash_sort_and_sorts_last(self):
        """A raw event with `"start": {}` (present but empty — no `date`/`dateTime`)
        normalizes cleanly to `start=""` (no exception in _normalize_event), but that empty
        string is not a parseable ISO datetime. The sort step must not let that crash take
        down the whole response — the malformed event should still show up, pushed to the
        end, alongside every well-formed event from every account."""
        from app.tools.calendar.service import list_events_for_range

        malformed = {"id": "bad-start", "summary": "Ghost event", "start": {}, "end": {}}
        accounts = [
            _FakeAccount("work", events=[
                _timed_event(event_id="w1", start="2026-07-28T13:00:00+05:30",
                             end="2026-07-28T14:00:00+05:30"),
                malformed,
            ]),
            _FakeAccount("personal", events=[_timed_event(event_id="p1", start="2026-07-28T09:00:00+05:30",
                                                            end="2026-07-28T09:30:00+05:30")]),
        ]
        events, errors = list_events_for_range(accounts, None, None, "Asia/Kolkata")
        assert errors == []
        assert [e["event_id"] for e in events] == ["p1", "w1", "bad-start"]
