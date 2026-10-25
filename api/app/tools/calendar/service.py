"""Merge calendar events across all accounts into one sorted, resilient list."""

import logging
from datetime import date, datetime, timezone, tzinfo

logger = logging.getLogger(__name__)


def _normalize_event(raw: dict, account: str) -> dict:
    """Flatten a Calendar API event resource into a flat display dict.

    All-day events carry date-only start/end (Google's end.date is exclusive of the last
    day — multi-day all-day spanning is not rendered in v1, only the start day).
    `declined` is True when the account owner declined the invite (their own attendee
    entry, `self: true`, has responseStatus "declined")."""
    start = raw.get("start", {})
    end = raw.get("end", {})
    all_day = "date" in start and "dateTime" not in start
    declined = any(
        a.get("self") and a.get("responseStatus") == "declined" for a in raw.get("attendees") or []
    )
    return {
        "account": account,
        "event_id": raw.get("id", ""),
        "title": raw.get("summary") or "(no title)",
        "start": start.get("date") if all_day else start.get("dateTime", ""),
        "end": end.get("date") if all_day else end.get("dateTime", ""),
        "all_day": all_day,
        "location": raw.get("location") or None,
        "declined": declined,
    }


def _sort_key(event: dict) -> datetime:
    """Compute an absolute-instant sort key for a normalized event.

    Timed events carry an ISO 8601 string with a UTC offset (or 'Z'); it's parsed into an
    aware datetime and normalized to UTC so events from accounts with different calendar
    timezones compare correctly. All-day events carry a date-only string — treated as
    midnight UTC of that date, a reasonable v1 convention since the frontend already renders
    all-day events in a separate row from timed ones.

    Never raises: a malformed `start` (empty string, unparseable text, wrong type — e.g. a
    raw Calendar API event with no `date`/`dateTime`, which `_normalize_event` turns into
    `start=""`) falls back to `datetime.max` in UTC, sorting the event to the end instead of
    blowing up `events.sort()` and discarding every account's already-collected results.
    """
    value = event["start"]
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return datetime.max.replace(tzinfo=timezone.utc)
    if event["all_day"]:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def list_events_for_range(
    accounts: list, time_min: datetime, time_max: datetime, tz_name: str
) -> tuple[list[dict], list[dict]]:
    """Fetch + normalize + merge + sort events across all accounts.

    `tz_name` is passed through to each account's `list_events` so the Calendar API
    responds in a known timezone (see `client.CalendarAccount.list_events`).

    Never raises: one account's failure — whether fetching or normalizing its events —
    is caught, logged, and reported in the returned errors list — the other accounts'
    events are still returned.
    """
    events: list[dict] = []
    errors: list[dict] = []
    for acc in accounts:
        try:
            raw_events = acc.list_events(time_min, time_max, tz_name)
            events.extend(_normalize_event(e, acc.account) for e in raw_events)
        except Exception as exc:
            logger.exception("calendar fetch failed for account %r", acc.account)
            errors.append({"account": acc.account, "message": str(exc)})
            continue
    events.sort(key=_sort_key)
    return events, errors


def _parse_local(value: str, tz: tzinfo | None) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed.astimezone(tz) if tz is not None else parsed


def _time_label(event: dict, today: date, tz: tzinfo | None) -> str:
    """"HH:MM" in `tz` for an event starting today. An event that started before today
    (overnight, or multi-day) shows when it ends instead, so it can't read as a start
    time today."""
    start = _parse_local(event["start"], tz)
    if start is None:
        return "--:--"
    if start.date() >= today:
        return f"{start:%H:%M}"
    end = _parse_local(event["end"], tz)
    if end is not None and end.date() == today:
        return f"until {end:%H:%M}"
    return "ongoing"


def format_daily_brief(
    events: list[dict],
    errors: list[dict],
    today: date,
    *,
    tz: tzinfo | None = None,
    accounts_checked: int | None = None,
) -> str:
    """Plain-text daily brief for Telegram. All-day events come first, then timed events in
    the order given (list_events_for_range output is already chronological); declined
    invites are left out. Times are shown in `tz` (the owner's zone).

    `accounts_checked` (how many accounts were queried) lets an unreadable calendar say so
    instead of passing for an empty day: zero accounts, or every account failing, gives a
    warning in place of the agenda. Otherwise a non-empty errors list appends one terse
    footnote — never the raw per-account error text, which is dashboard-appropriate
    detail, not Telegram brevity."""
    header = f"📅 Today — {today:%a %b} {today.day}"
    if accounts_checked == 0:
        return f"{header}\n\n⚠ No calendar accounts connected."
    if accounts_checked is not None and errors and len(errors) >= accounts_checked:
        return f"{header}\n\n⚠ Couldn't read your calendar today."

    shown = [ev for ev in events if not ev.get("declined")]
    all_day = [ev for ev in shown if ev["all_day"]]
    timed = [ev for ev in shown if not ev["all_day"]]
    lines = [f"{ev['title']} [{ev['account']}]" for ev in all_day]
    lines += [f"{_time_label(ev, today, tz)} {ev['title']} [{ev['account']}]" for ev in timed]
    body = "\n".join(lines) if lines else "Nothing on the calendar today."
    text = f"{header}\n\n{body}"
    if errors:
        n = len(errors)
        text += f"\n\n⚠ {n} account{'s' if n != 1 else ''} unavailable"
    return text
