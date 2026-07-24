# Calendar Integration (Dashboard Week View) — Design Spec

**Date:** 2026-07-25
**Status:** Approved for implementation (v1)
**Owner:** Darshit

---

## 1. Context & goal

Today the dashboard shows email and reminders, but calendar events (spread across every
Gmail-linked Google account) require checking each account's calendar separately. There is no
unified view.

**Goal (v1):** a new `/calendar` dashboard page showing a Google-Calendar-style week grid,
merging events from every account in `GMAIL_ACCOUNTS` into one view, live-fetched from the
Google Calendar API on every page load/navigation (no local caching, no sync job).

**Explicitly v1 only:** read-only display. No event creation/editing, no Telegram involvement
(no digest folding, no chat query), no secondary/shared calendars — primary calendar per
account only.

### Non-goals (deferred to V2 — see §10)
- Creating/editing events from the dashboard or chat, with a HITL gate.
- Secondary/shared calendars.
- Per-account opt-out of calendar.
- Folding today's agenda into the Telegram digest or a chat tool.

---

## 2. Auth model

Reuses the existing per-account OAuth pattern (`tools/gmail/client.py`'s `GmailAccount` /
`load_accounts`) — **same refresh token per account**, no new env vars, no new per-account
config. The token just needs a wider scope grant.

**Scope added:** `https://www.googleapis.com/auth/calendar.events` (read/write on events, not
full calendar management — least privilege that still covers the deferred create/update
feature, so that feature needs **zero additional re-auth** later even though v1 only reads).

`auth_setup.py` is modified to request the union of Gmail + Calendar scopes:

```python
from app.tools.gmail.client import SCOPES as GMAIL_SCOPES
from app.tools.calendar.client import SCOPES as CALENDAR_SCOPES

SCOPES = GMAIL_SCOPES + CALENDAR_SCOPES
```

Each account needs a **one-time, owner-driven re-auth** (re-run `auth_setup.py <account>`,
replace `GMAIL_<NAME>_REFRESH_TOKEN` in `.env`) — the same operational step already used once
for the `gmail.compose` scope addition. This is a manual prerequisite, not automated.

---

## 3. Architecture

```
api/app/tools/calendar/
  __init__.py
  client.py     # CalendarAccount, load_accounts, SCOPES        (NEW)
  service.py    # normalize + merge + sort across accounts      (NEW)

api/app/api/routes.py         # GET /api/calendar/events         (MODIFY)
api/app/tools/gmail/auth_setup.py  # combined scopes             (MODIFY)

web/app/calendar/page.tsx           # server component, week view  (NEW)
web/components/calendar-grid.tsx    # presentational grid          (NEW)
web/lib/api.ts                      # getCalendarEvents()           (MODIFY)
web/components/app-shell.tsx        # nav entry                     (MODIFY)
```

No new DB table, no new cron job, no new proxy/polling route — every page load/navigation is a
fresh live fetch, matching the "live fetch" decision (arbitrary date navigation just changes
what range gets requested; there's nothing to invalidate).

---

## 4. Component specs

### 4.1 `app/tools/calendar/client.py` (NEW)

```python
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

class CalendarAccount:
    """One authenticated account's primary calendar. Same refresh token as GmailAccount
    for this account — the OAuth grant now covers both Gmail and Calendar scopes."""

    def __init__(self, account: str, client_id: str, client_secret: str, refresh_token: str):
        ...  # same Credentials(...) shape as GmailAccount, scopes=SCOPES

    @property
    def service(self):
        ...  # build("calendar", "v3", credentials=self._creds, cache_discovery=False)

    def list_events(self, time_min: datetime, time_max: datetime) -> list[dict]:
        """Raw Calendar API event resources for the primary calendar in [time_min, time_max)."""
        return (
            self.service.events()
            .list(calendarId="primary", timeMin=..., timeMax=..., singleEvents=True,
                  orderBy="startTime")
            .execute()
            .get("items", [])
        )


def load_accounts(settings) -> list[CalendarAccount]:
    """Same GMAIL_<NAME>_REFRESH_TOKEN env vars as tools/gmail/client.py's load_accounts —
    one account list, one token per account, shared across both tools."""
    ...
```

### 4.2 `app/tools/calendar/service.py` (NEW)

```python
def _normalize_event(raw: dict, account: str) -> dict:
    """Flatten a Calendar API event resource into a flat dict:
    {account, event_id, title, start, end, all_day, location}.
    All-day events (raw['start']['date'], no 'dateTime') set all_day=True and start/end
    as date-only strings; timed events carry full RFC3339 datetimes."""
    ...


def list_events_for_range(
    accounts: list[CalendarAccount], time_min: datetime, time_max: datetime
) -> tuple[list[dict], list[dict]]:
    """Fetch + normalize + merge + sort events across all accounts.

    Never raises: one account's failure (expired/missing token, API error) is caught,
    logged, and reported in the returned errors list — the other accounts' events are
    still returned. Returns (events_sorted_by_start, errors)."""
    events, errors = [], []
    for acc in accounts:
        try:
            events.extend(_normalize_event(e, acc.account) for e in acc.list_events(time_min, time_max))
        except Exception as e:
            logger.exception("calendar fetch failed for account %r", acc.account)
            errors.append({"account": acc.account, "message": str(e)})
    events.sort(key=lambda e: e["start"])
    return events, errors
```

### 4.3 `app/api/routes.py` (MODIFY) — new route

```python
@app.get("/api/calendar/events", dependencies=[Depends(require_auth)])
def get_calendar_events(start: str, end: str):
    """start/end: YYYY-MM-DD, inclusive calendar-day range, interpreted in settings.timezone.
    Sync def — blocking Google SDK calls run in FastAPI's threadpool (one-event-loop rule)."""
    settings = get_settings()
    # Google's timeMax is exclusive: time_min = start 00:00 local, time_max = (end + 1 day) 00:00 local,
    # so events on the `end` date itself are still included.
    time_min, time_max = _day_range_to_utc(start, end, settings.timezone)
    accounts = calendar_client.load_accounts(settings)
    events, errors = list_events_for_range(accounts, time_min, time_max)
    return {"events": events, "errors": errors}
```

Response shape:
```json
{
  "events": [
    {"account": "personal", "event_id": "abc123", "title": "Dentist",
     "start": "2026-07-28T13:00:00+05:30", "end": "2026-07-28T14:00:00+05:30",
     "all_day": false, "location": "Downtown Clinic"}
  ],
  "errors": [
    {"account": "work2", "message": "refresh failed — needs re-auth"}
  ]
}
```

The `errors` array is how a partial failure (one account's token stale) surfaces to the
frontend as a non-blocking banner instead of a broken page.

### 4.4 `web/lib/api.ts` (MODIFY)

```ts
export type CalendarEvent = {
  account: string; eventId: string; title: string;
  start: string; end: string; allDay: boolean; location: string | null;
};

export async function getCalendarEvents(
  start: string, end: string
): Promise<{ events: CalendarEvent[]; errors: { account: string; message: string }[] }> {
  ...  // same fetch-with-bearer-token pattern as getReminders/getEmails
}
```

### 4.5 `web/app/calendar/page.tsx` (NEW)

Server component, `export const dynamic = "force-dynamic"` (same pattern as the reminders
page). Reads an optional `?start=YYYY-MM-DD` search param (any date, not necessarily a
Monday); computes the Mon–Sun week containing that date (or containing *today* if absent) in
`settings.timezone`; fetches that week's events; renders `<CalendarGrid>`. Prev/Next/Today are
plain `<Link>`s that change `?start=` — no client polling needed, each navigation is a fresh
server-side render, consistent with how this isn't live-updating data.

### 4.6 `web/components/calendar-grid.tsx` (NEW)

Presentational, Google-Calendar-style: 7 day columns × hour rows (24h, scrollable, initial
scroll position near the morning so a typical day is in view without scrolling), a separate
all-day row per day above the hourly grid, event chips positioned/sized by start/end time and
colored per account (a small fixed palette cycling deterministically by account name, with a
legend). Renders the `errors` array as a small dismissable banner ("personal2: calendar
unavailable — needs re-auth") without blocking the rest of the grid. Exact visual details
(chip styling, spacing, palette) follow the existing Base UI + Tailwind + `globals.css`
semantic-class conventions — left to implementation, not over-specified here.

### 4.7 `web/components/app-shell.tsx` (MODIFY)

Add a "Calendar" nav entry alongside Email/Reminders/Observability.

---

## 5. Data flow

```
User navigates (Prev/Next/Today or first load)
  → URL ?start= changes
  → page.tsx (RSC) computes the Mon–Sun week
  → getCalendarEvents(start, end) → GET /api/calendar/events
  → route computes UTC time_min/time_max from settings.timezone
  → load_accounts(settings) → one CalendarAccount per GMAIL_ACCOUNTS entry
  → list_events_for_range: one live Calendar API call per account, merged, sorted
  → JSON {events, errors} → CalendarGrid renders
```

Nothing is persisted. Every load is live truth from Google. An account with a stale/missing
token degrades to an error-banner entry, not a broken page.

---

## 6. Error handling

- **Per-account fetch failure** (expired refresh token, transient API error, rate limit): caught
  in `list_events_for_range`, logged (`logger.exception`), reported in `errors`; other accounts'
  events are unaffected.
- **No configured accounts at all**: `load_accounts` returns `[]` (mirrors `tools/gmail/client.py`
  behavior) → empty `events`, empty `errors` → grid renders empty, no error banner (there's
  nothing wrong, just nothing configured).
- **All-day events**: detected via `raw['start']['date']` (no `'dateTime'` key) — rendered in the
  all-day row, never given an hourly slot.
- **Timezone**: all range boundaries and grid hour labels use `settings.timezone`
  (`Asia/Kolkata` today), matching the existing reminder/triage convention — never host-local or
  UTC.
- **Malformed `start`/`end` query params**: 422 via FastAPI's own parameter validation (both are
  required, plain strings parsed to dates in the handler; an unparsable date raises a `ValueError`
  the handler converts to a `400`).

---

## 7. Testing

### Backend (`api/tests/`) — Calendar faked the same way Gmail/LLM are faked today
- `_normalize_event`: a timed event, an all-day event, an event missing `location`.
- `list_events_for_range`: merges + sorts across 2 fake accounts; one account's `list_events`
  raising is caught and appears in `errors` while the other account's events still come back;
  empty `accounts` list → `([], [])`.
- Route test: fake `load_accounts` and Calendar client, assert `GET /api/calendar/events?start=&end=`
  returns the merged JSON shape; missing `start`/`end` → 422; malformed date string → 400.
- Timezone boundary test: a given `start`/`end` day range converts to the correct UTC
  `time_min`/`time_max` for a non-UTC `settings.timezone`.

### Frontend
No existing unit test framework for `web/` — verify with `npm run lint` plus a manual browser
pass: load `/calendar`, confirm events from ≥2 re-authed accounts appear merged and correctly
colored, Prev/Next/Today navigation works, and an account with a deliberately-broken token shows
the error banner without breaking the rest of the grid.

---

## 8. Deferred to V2 (recorded in `TODO.md`)

- Create/update events from chat, with a HITL gate (scope is already granted in v1 — this needs
  **no further re-auth**).
- Secondary/shared calendars beyond each account's primary.
- Per-account opt-out of calendar.
- Folding today's agenda into the Telegram digest or exposing it as a chat tool.

---

## 9. File-by-file change list (for the implementer)

**New**
- `api/app/tools/calendar/__init__.py`
- `api/app/tools/calendar/client.py` — `CalendarAccount`, `load_accounts`, `SCOPES`.
- `api/app/tools/calendar/service.py` — `_normalize_event`, `list_events_for_range`.
- `api/tests/test_calendar_client.py`, `api/tests/test_calendar_service.py`,
  test coverage for the new route (new file or folded into the existing routes test file).
- `web/app/calendar/page.tsx`
- `web/components/calendar-grid.tsx`

**Modify**
- `api/app/tools/gmail/auth_setup.py` — combined `GMAIL_SCOPES + CALENDAR_SCOPES`.
- `api/app/api/routes.py` — `GET /api/calendar/events`.
- `web/lib/api.ts` — `getCalendarEvents`, `CalendarEvent` type.
- `web/components/app-shell.tsx` — "Calendar" nav entry.
- `TODO.md` — mark the Calendar v1 item done; move create/edit + digest/chat items to a
  "Calendar V2" sub-list.
- `AGENTS.md` — add `tools/calendar/` to the repo layout list.

**Acceptance:** `uv run pytest` green; `npm run lint` green; manually confirmed in browser —
`/calendar` loads the current week, shows events merged from all re-authed accounts, Prev/Next/
Today navigation works, and a deliberately-broken account token shows a non-blocking error
banner instead of breaking the page.
