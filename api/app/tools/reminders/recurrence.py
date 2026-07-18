"""Recurrence normalization: human shorthands → crontab, no LLM involved.

"everyday", "weekdays", "every monday" … are derived deterministically from the
reminder's fire time. Raw 5-field cron passes through (validated). Generated crons
always use day NAMES — APScheduler's from_crontab reads numeric day-of-week as
0=Monday while standard cron is 1=Monday, so names are the only safe form.
"""

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger

from app.store.db import as_utc

DAY_ABBR = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]  # datetime.weekday() order
DAY_ALIASES = {
    "monday": "mon", "tuesday": "tue", "wednesday": "wed", "thursday": "thu",
    "friday": "fri", "saturday": "sat", "sunday": "sun",
    "mon": "mon", "tue": "tue", "wed": "wed", "thu": "thu", "fri": "fri", "sat": "sat", "sun": "sun",
}

_HELP = 'Try "everyday", "weekdays", "weekends", "weekly", "monthly", "every monday", or 5-field cron like "30 9 * * mon-fri".'


def normalize_recurrence(expr: str, fire_at: datetime, tz: str) -> str:
    """Return a crontab string for a shorthand or raw-cron expression ("" stays "")."""
    e = " ".join(expr.strip().lower().split())
    if not e:
        return ""
    local = as_utc(fire_at).astimezone(ZoneInfo(tz))
    m, h = local.minute, local.hour

    if e in ("everyday", "daily", "every day"):
        return f"{m} {h} * * *"
    if e in ("weekdays", "every weekday", "weekday"):
        return f"{m} {h} * * mon-fri"
    if e in ("weekends", "every weekend", "weekend"):
        return f"{m} {h} * * sat,sun"
    if e in ("weekly", "every week"):
        return f"{m} {h} * * {DAY_ABBR[local.weekday()]}"
    if e in ("monthly", "every month"):
        # Clamp to 28 so the reminder fires every month — a day of 29/30/31 would
        # silently skip the short months (Feb always; Apr/Jun/Sep/Nov for 31).
        return f"{m} {h} {min(local.day, 28)} * *"
    if e in ("hourly", "every hour"):
        return f"{m} * * * *"

    day = re.fullmatch(r"(?:every |on )?([a-z]+?)s?", e)
    if day and day.group(1) in DAY_ALIASES:
        return f"{m} {h} * * {DAY_ALIASES[day.group(1)]}"

    # Raw cron passthrough — validate it parses.
    fields = e.split()
    if len(fields) == 5 and any(ch.isdigit() for ch in fields[4]):
        # APScheduler's from_crontab reads a NUMERIC day-of-week as 0=Monday, while
        # standard cron uses 1=Monday — so a numeric DOW fires one day off. Names are
        # the only safe form; reject digits in the DOW field rather than fire wrongly.
        raise ValueError(
            f"Numeric day-of-week in {expr!r} is ambiguous (APScheduler reads 0=Monday). "
            f"Use day names, e.g. 'mon', 'mon-fri'. {_HELP}"
        )
    try:
        CronTrigger.from_crontab(e, timezone=tz)
    except ValueError:
        raise ValueError(f"Could not understand recurrence {expr!r}. {_HELP}")
    return e
