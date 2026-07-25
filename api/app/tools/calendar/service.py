"""Merge calendar events across all accounts into one sorted, resilient list."""

import logging
from datetime import datetime, timezone

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
