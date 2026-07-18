# "Sent with rotom" email footer — design

**Date:** 2026-06-13
**Status:** Designed, not implemented

## Summary

Append a subtle, clickable "Sent with rotom" attribution footer to outgoing
emails. The link is a real anchor tag, so the message must carry an HTML part —
today all mail is sent as `text/plain`. We make the MIME builder emit
`multipart/alternative` (plain-text + HTML) **only when the footer is on**, so
when it's off the wire format is byte-for-byte unchanged.

This is attribution/branding, **distinct from and below** the user's personal
sign-off. Reply and outreach drafts already end with an LLM-generated sign-off
(e.g. "Thanks, <name>", driven by `user_signature`) baked into `draft.body`. The
rotom footer is appended *beneath* that at send/save time and is **never stored**
in `draft.body`.

Whether the footer is applied is decided **per send/save** by a dashboard switch.
A global config sets the switch's default state and serves as the fallback for
non-dashboard (agent/programmatic) sends. The switch state is not persisted —
it's read from the UI and passed in the send/save request only.

## Decisions (locked)

- **Scope:** all sent emails — replies *and* outreach.
- **Control:** per-draft switch in the dashboard (no label; hover tooltip explains
  it's the "Sent with rotom" footer). The switch initializes to the global default
  on page load: global on → switch on, global off → switch off. State is **not
  persisted** anywhere — only read at click time and sent with the request.
- **Send paths:** both direct Send *and* Save-to-Gmail-draft. The footer decision
  is passed into both; the MIME-build chokepoint applies it.
- **Mechanism:** inline-styled HTML `<a>` anchor (no image, no tracking pixel, no
  link shortener) with a clean plain-text fallback. Subtle/muted styling.
- **Prerequisite:** a footer can only render if `EMAIL_FOOTER_URL` is configured
  (no URL → nothing to link → no footer, regardless of the switch).

## Architecture

The footer applies at one chokepoint — `build_mime()` in
`api/app/tools/gmail/client.py`, called by both `GmailAccount.send_message()` and
`GmailAccount.create_gmail_draft()`. `build_mime` stays settings-agnostic: it
takes an explicit `footer_url` and emits the footer iff it's non-empty.

The *decision* of whether to footer flows from the dashboard switch through the
send/save request into the route, which resolves the effective `footer_url` and
passes it down. Footer string construction lives in a new, dependency-free module
`api/app/tools/gmail/footer.py` so it's unit-testable in isolation.

### Effective-footer resolution (in the route)

```
rotom_footer  = request body field (bool | None; None when caller omits it)
use_footer    = rotom_footer if rotom_footer is not None else settings.email_footer_enabled
footer_url    = settings.email_footer_url if (use_footer and settings.email_footer_url) else ""
```

So the dashboard switch (always sends an explicit bool) wins; programmatic callers
that omit the field fall back to the global default; and an unconfigured URL
disables the footer unconditionally.

### Data flow

```
[dashboard] Switch state ─┐
                          ▼
draft-composer.tsx → sendDraft / saveToGmailAction (lib/actions.ts)
                          │  passes rotomFooter bool
                          ▼
            postDraftAction(id,"send",footer) / saveToGmail(id,footer)  (lib/api.ts)
                          │  POST body { "rotom_footer": <bool> }
                          ▼
        POST /api/drafts/{id}/send  |  /save-to-gmail   (routes.py)
                          │  resolve footer_url (see above)
                          ▼
   account.send_message / create_gmail_draft ──▶ build_mime(..., footer_url=...)
                          │
                          ├── footer_url == ""  → MIMEText(body)        (UNCHANGED — text/plain)
                          └── footer_url truthy → multipart/alternative:
                                   ├── text/plain : body + plain_footer(url)
                                   └── text/html  : html_body(body, url)
                          ▼
                 (+ attachments → wrap alternative in multipart/mixed)
                          ▼
                 base64url(raw) → Gmail API
```

## Components

### `api/app/tools/gmail/footer.py` (new)

Pure functions, no imports beyond `html` from stdlib:

- `plain_footer(url: str) -> str` → `"\n\nSent with rotom · {url}"`.
- `html_body(body: str, url: str) -> str`
  HTML-escapes `body` (`html.escape`), converts newlines to `<br>`, wraps in a
  minimal inline-styled `<div>`, and appends the muted anchor footer. All styling
  inline (clients strip `<style>`/`<head>`). `url` is escaped with
  `html.escape(url, quote=True)` before going in `href`.

  Footer markup (subtle, muted gray):
  ```html
  <div style="margin-top:24px;color:#9ca3af;font-size:12px;">Sent with <a href="{url}" style="color:#9ca3af;text-decoration:underline;">rotom</a></div>
  ```

### `build_mime()` — `api/app/tools/gmail/client.py` (modified)

New keyword arg `footer_url: str = ""`. Behavior:

- `footer_url == ""`: build exactly as today (`MIMEText(body)`, or
  `MIMEMultipart()` + `MIMEText(body)` when attachments). No change.
- `footer_url` truthy: build a `multipart/alternative` of `MIMEText(plain,
  "plain")` + `MIMEText(html, "html")`. If there are attachments, nest that
  alternative inside a `multipart/mixed` outer alongside the attachment parts.

Headers (`To`, `Subject`, `In-Reply-To`, `References`) are set on the outermost
part after the body is assembled. The `Re:` subject-prefix logic is unchanged.

```
no attachments, footer on:        with attachments, footer on:
multipart/alternative             multipart/mixed
├── text/plain                    ├── multipart/alternative
└── text/html                     │   ├── text/plain
                                  │   └── text/html
                                  └── application/* (attachment)
```

### `GmailAccount.send_message` / `create_gmail_draft` — `client.py` (modified)

Add a `footer_url: str = ""` kwarg to both and forward it to `build_mime`. They
do **not** read settings — the route resolves `footer_url` and passes it in,
keeping these methods and `build_mime` fully unit-testable.

### `api/app/config.py` (modified)

Add two settings under "Drafts / Outreach":
```python
email_footer_enabled: bool = True        # EMAIL_FOOTER_ENABLED — default state of the dashboard switch
email_footer_url: str = ""               # EMAIL_FOOTER_URL — link target for the footer anchor
```
`email_footer_url` is the hard prerequisite (empty → no footer ever).
`email_footer_enabled` is the **default switch state** + the fallback for
programmatic sends. Document both in `.env.example`.

### `api/app/api/routes.py` (modified)

- **Request body model** (shared by both endpoints):
  ```python
  class FooterOption(BaseModel):
      rotom_footer: bool | None = None
  ```
- `send_draft` and `save_to_gmail` gain a body param
  `opts: FooterOption = FooterOption()` (FastAPI: optional body, defaults when the
  caller sends none — preserves backward compatibility). Each resolves
  `footer_url` via the resolution rule above and passes it to
  `send_message` / `create_gmail_draft`.
- **`_draft_json`** gains one field: `rotom_footer_default` =
  `settings.email_footer_enabled and bool(settings.email_footer_url)`. This is the
  initial switch state for the dashboard. (Global value surfaced on the draft for
  a single fetch; acceptable given the dashboard always loads a draft first.)

### Frontend — `web/` (modified)

- **`web/components/ui/switch.tsx`** (new): standard shadcn Switch (Radix-based).
  Generate via `npx shadcn@latest add switch` or hand-author to match existing
  `ui/` components.
- **`web/lib/api.ts`:**
  - `DraftItem` gains `rotom_footer_default: boolean`.
  - `postDraftAction(id, action, rotomFooter?)` — when `action === "send"` and
    `rotomFooter !== undefined`, POST body `{ rotom_footer: rotomFooter }`;
    otherwise no body (so `discard` is untouched).
  - `saveToGmail(id, rotomFooter?)` — POST body `{ rotom_footer: rotomFooter }`
    when provided.
- **`web/lib/actions.ts`:** `sendDraft` and `saveToGmailAction` take an extra
  `rotomFooter: boolean` and thread it to `postDraftAction` / `saveToGmail`.
- **`web/components/draft-composer.tsx`:** add a small unlabeled `Switch`
  (controlled state initialized from `draft.rotom_footer_default`) wrapped in a
  `Tooltip` reading e.g. "Append a 'Sent with rotom' footer to this email." Pass
  the current switch value into the Send and Save-to-Gmail calls.

## Error handling

- Empty/whitespace `email_footer_url`, or switch off → footer skipped, message is
  `text/plain` exactly as today.
- Footer construction is pure string work — no I/O, no defensive try/except; a bug
  should surface in tests, not be swallowed at send time.
- No new failure modes in the send path; existing `routes.py` send/save error
  handling already covers a raising `build_mime`.

## Testing

`api/tests/test_email_footer.py` (new), pure + MIME-level, no network:

- `plain_footer` includes the URL and the "Sent with rotom" phrasing.
- `html_body` escapes HTML (`<script>` in body → `&lt;script&gt;`), converts
  newlines to `<br>`, contains exactly one `<a href="...">` with the configured URL.
- `build_mime(footer_url="")` → parsed message content type is `text/plain`
  (regression guard: off = unchanged).
- `build_mime(footer_url=url)` no attachments → `multipart/alternative` with a
  `text/plain` and a `text/html` part; html contains the anchor, plain contains the URL.
- `build_mime(footer_url=url, attachments=[file])` → `multipart/mixed` whose first
  part is `multipart/alternative` and which also carries the attachment.

Route-level tests (extend existing draft route tests):
- POST send / save-to-gmail with `{"rotom_footer": true}` (URL configured) → the
  Gmail client is called with a non-empty `footer_url`; with `{"rotom_footer":
  false}` → empty `footer_url`; with no body → falls back to `email_footer_enabled`.
- `_draft_json` exposes `rotom_footer_default` reflecting the settings.

Frontend: type-check (`tsc`) clean; switch renders and threads the boolean
through. No automated UI test required.

Tests decode the base64url output and parse with `email.message_from_bytes`.

## Out of scope

- **Persisting** the switch state (it's read from the UI per action only).
- Storing the footer in `draft.body` (added at send/save time).
- Configurable footer *text* — phrasing is fixed; only the URL is configurable. (YAGNI.)
- Open/click tracking.
