"""Tests for merging/normalizing Calendar events across accounts."""

from datetime import date
from zoneinfo import ZoneInfo

from app.tools.calendar.service import (
    _normalize_event, format_daily_brief, list_events_for_range,
)


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
        norm = _normalize_event(_timed_event(location="Downtown Clinic"), account="personal")
        assert norm == {
            "account": "personal", "event_id": "e1", "title": "Standup",
            "start": "2026-07-28T09:00:00+05:30", "end": "2026-07-28T09:30:00+05:30",
            "all_day": False, "location": "Downtown Clinic", "declined": False,
        }

    def test_declined_only_when_the_owner_declined(self):
        ev = _timed_event()
        ev["attendees"] = [{"email": "boss@x", "responseStatus": "declined"},
                           {"email": "me@x", "self": True, "responseStatus": "accepted"}]
        assert _normalize_event(ev, account="work")["declined"] is False
        ev["attendees"][1]["responseStatus"] = "declined"
        assert _normalize_event(ev, account="work")["declined"] is True

    def test_all_day_event(self):
        norm = _normalize_event(_all_day_event(), account="personal")
        assert norm["all_day"] is True
        assert norm["start"] == "2026-11-08"
        assert norm["end"] == "2026-11-09"

    def test_missing_location_is_none(self):
        norm = _normalize_event(_timed_event(), account="personal")
        assert norm["location"] is None

    def test_missing_title_defaults(self):
        ev = {"id": "e3", "start": {"dateTime": "2026-07-28T09:00:00+05:30"},
              "end": {"dateTime": "2026-07-28T09:30:00+05:30"}}
        norm = _normalize_event(ev, account="personal")
        assert norm["title"] == "(no title)"


class TestListEventsForRange:
    def test_merges_and_sorts_across_accounts(self):
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
        accounts = [
            _FakeAccount("broken", error=RuntimeError("token expired")),
            _FakeAccount("ok", events=[_timed_event(event_id="ok1")]),
        ]
        events, errors = list_events_for_range(accounts, None, None, "Asia/Kolkata")
        assert [e["event_id"] for e in events] == ["ok1"]
        assert errors == [{"account": "broken", "message": "token expired"}]

    def test_empty_accounts_returns_empty(self):
        assert list_events_for_range([], None, None, "Asia/Kolkata") == ([], [])

    def test_sorts_by_absolute_instant_not_raw_string(self):
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


class TestFormatDailyBrief:
    def test_no_events(self):
        text = format_daily_brief([], [], date(2026, 7, 28))
        assert text == "📅 Today — Tue Jul 28\n\nNothing on the calendar today."

    def test_single_timed_event(self):
        events = [{"account": "work", "title": "Standup", "start": "2026-07-28T09:00:00+05:30",
                   "end": "2026-07-28T09:30:00+05:30", "all_day": False, "event_id": "e1",
                   "location": None}]
        text = format_daily_brief(events, [], date(2026, 7, 28))
        assert "09:00 Standup [work]" in text

    def test_all_day_event_has_no_time_prefix(self):
        events = [{"account": "personal", "title": "Diwali", "start": "2026-07-28",
                   "end": "2026-07-29", "all_day": True, "event_id": "e2", "location": None}]
        text = format_daily_brief(events, [], date(2026, 7, 28))
        assert text == "📅 Today — Tue Jul 28\n\nDiwali [personal]"

    def test_errors_append_terse_footnote_not_raw_text(self):
        text = format_daily_brief([], [{"account": "broken", "message": "invalid_scope: Bad Request"}],
                                   date(2026, 7, 28))
        assert "⚠ 1 account unavailable" in text
        assert "invalid_scope" not in text  # raw error text stays out of Telegram

    def test_multiple_accounts_pluralizes_footnote(self):
        text = format_daily_brief(
            [], [{"account": "a", "message": "x"}, {"account": "b", "message": "y"}], date(2026, 7, 28)
        )
        assert "⚠ 2 accounts unavailable" in text

    def test_multiple_events_preserve_input_order(self):
        events = [
            {"account": "work", "title": "Standup", "start": "2026-07-28T09:00:00+05:30",
             "end": "2026-07-28T09:30:00+05:30", "all_day": False, "event_id": "e1", "location": None},
            {"account": "personal", "title": "Dentist", "start": "2026-07-28T13:00:00+05:30",
             "end": "2026-07-28T14:00:00+05:30", "all_day": False, "event_id": "e2", "location": None},
        ]
        text = format_daily_brief(events, [], date(2026, 7, 28))
        assert text.index("09:00 Standup") < text.index("13:00 Dentist")

    def test_all_day_events_come_first_even_after_an_early_timed_event(self):
        # list_events_for_range sorts all-day events at midnight UTC, i.e. 05:30 IST — after
        # a 04:30 IST flight. The brief still lists the all-day event first.
        ist = ZoneInfo("Asia/Kolkata")
        events = [
            {"account": "p", "title": "Early flight", "start": "2026-07-28T04:30:00+05:30",
             "end": "2026-07-28T07:00:00+05:30", "all_day": False},
            {"account": "p", "title": "Diwali", "start": "2026-07-28", "end": "2026-07-29",
             "all_day": True},
            {"account": "p", "title": "Standup", "start": "2026-07-28T09:00:00+05:30",
             "end": "2026-07-28T09:30:00+05:30", "all_day": False},
        ]
        text = format_daily_brief(events, [], date(2026, 7, 28), tz=ist)
        assert text.split("\n\n")[1].splitlines() == [
            "Diwali [p]", "04:30 Early flight [p]", "09:00 Standup [p]",
        ]

    def test_times_are_shown_in_the_owners_zone(self):
        events = [{"account": "w", "title": "Sync", "start": "2026-07-28T03:30:00Z",
                   "end": "2026-07-28T04:00:00Z", "all_day": False}]
        text = format_daily_brief(events, [], date(2026, 7, 28), tz=ZoneInfo("Asia/Kolkata"))
        assert "09:00 Sync [w]" in text

    def test_event_that_started_yesterday_shows_its_end(self):
        ist = ZoneInfo("Asia/Kolkata")
        events = [
            {"account": "p", "title": "Red-eye", "start": "2026-07-27T22:00:00+05:30",
             "end": "2026-07-28T06:00:00+05:30", "all_day": False},
            {"account": "p", "title": "Conference", "start": "2026-07-27T09:00:00+05:30",
             "end": "2026-07-29T18:00:00+05:30", "all_day": False},
        ]
        text = format_daily_brief(events, [], date(2026, 7, 28), tz=ist)
        assert "until 06:00 Red-eye [p]" in text
        assert "ongoing Conference [p]" in text
        assert "22:00" not in text

    def test_declined_invites_are_left_out(self):
        events = [
            {"account": "w", "title": "Optional sync", "start": "2026-07-28T10:00:00+05:30",
             "end": "2026-07-28T10:30:00+05:30", "all_day": False, "declined": True},
        ]
        text = format_daily_brief(events, [], date(2026, 7, 28))
        assert "Optional sync" not in text
        assert "Nothing on the calendar today." in text

    def test_every_account_failing_is_not_an_empty_day(self):
        errors = [{"account": "a", "message": "invalid_grant"}, {"account": "b", "message": "x"}]
        text = format_daily_brief([], errors, date(2026, 7, 28), accounts_checked=2)
        assert text == "📅 Today — Tue Jul 28\n\n⚠ Couldn't read your calendar today."

    def test_no_accounts_connected_is_not_an_empty_day(self):
        text = format_daily_brief([], [], date(2026, 7, 28), accounts_checked=0)
        assert text == "📅 Today — Tue Jul 28\n\n⚠ No calendar accounts connected."

    def test_some_accounts_failing_still_shows_the_agenda(self):
        events = [{"account": "a", "title": "Standup", "start": "2026-07-28T09:00:00+05:30",
                   "end": "2026-07-28T09:30:00+05:30", "all_day": False}]
        text = format_daily_brief(events, [{"account": "b", "message": "x"}], date(2026, 7, 28),
                                  accounts_checked=2)
        assert "09:00 Standup [a]" in text
        assert text.endswith("⚠ 1 account unavailable")
