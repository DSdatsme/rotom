# "Sent with rotom" Email Footer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Append a subtle, clickable "Sent with rotom" footer to outgoing emails, toggled per-draft by an unlabeled dashboard switch whose default comes from global config.

**Architecture:** A new pure-string module builds the footer; `build_mime()` emits `multipart/alternative` (plain + HTML) only when given a non-empty `footer_url`, otherwise stays byte-for-byte `text/plain`. The send/save routes resolve the effective `footer_url` from a request param (the switch) falling back to global config, and pass it down. The dashboard switch initializes from a `rotom_footer_default` field added to the draft JSON.

**Tech Stack:** Python 3.12, FastAPI, pydantic-settings, stdlib `email`/`html`; Next.js 16 (App Router, server actions), shadcn/ui (Radix Switch + existing Tooltip), TypeScript.

**Spec:** `docs/superpowers/specs/2026-06-13-email-footer-design.md`

**Reference — effective-footer resolution (used in Task 4):**
```
rotom_footer = request field (bool | None; None when caller omits it)
use_footer   = rotom_footer if rotom_footer is not None else settings.email_footer_enabled
footer_url   = settings.email_footer_url if (use_footer and settings.email_footer_url) else ""
```

**Notes for the implementer:**
- API tests run with `cd api && uv run pytest`. The repo already has `tests/test_gmail_client.py` (with a module-level `_decode(raw)` helper and `from email import message_from_bytes` import at top) and `tests/test_api_routes.py` (with a `client` fixture and a `FakeAccount`).
- The web app is **Next.js 16** — see `web/AGENTS.md`. Do not assume older Next.js conventions. The changes here are a new shadcn component plus prop/param threading; no routing or RSC changes.
- Never add Claude as a git co-author.

---

## File Structure

- **Create** `api/app/tools/gmail/footer.py` — pure footer string builders (`plain_footer`, `html_body`). No I/O, no settings, no MIME.
- **Modify** `api/app/tools/gmail/client.py` — `build_mime()` gains `footer_url=""`; `GmailAccount.send_message` / `create_gmail_draft` gain and forward `footer_url=""`.
- **Modify** `api/app/config.py` — add `email_footer_enabled`, `email_footer_url`.
- **Modify** `api/app/api/routes.py` — `FooterOption` body model on send + save-to-gmail; resolve `footer_url`; add `rotom_footer_default` to `_draft_json`.
- **Modify** `api/.env.example` — document the two new env vars.
- **Create** `api/tests/test_email_footer.py` — footer + build_mime MIME-level tests.
- **Modify** `api/tests/test_api_routes.py` — route tests for the footer param + `rotom_footer_default`.
- **Create** `web/components/ui/switch.tsx` — shadcn Radix Switch.
- **Modify** `web/lib/api.ts` — `DraftItem.rotom_footer_default`; footer param on `postDraftAction` + `saveToGmail`.
- **Modify** `web/lib/actions.ts` — thread `rotomFooter` through `sendDraft` + `saveToGmailAction`.
- **Modify** `web/components/draft-composer.tsx` — the switch (tooltip, no label), wired into Send + Save-to-Gmail.

---

## Task 1: Footer string builders (`footer.py`)

**Files:**
- Create: `api/app/tools/gmail/footer.py`
- Test: `api/tests/test_email_footer.py`

- [ ] **Step 1: Write the failing tests**

Create `api/tests/test_email_footer.py`:

```python
"""Tests for the 'Sent with rotom' footer builders and build_mime integration."""

import base64
from email import message_from_bytes

from app.tools.gmail.footer import plain_footer, html_body

URL = "https://rotom.example.com"


def test_plain_footer_has_phrase_and_url():
    out = plain_footer(URL)
    assert "Sent with rotom" in out
    assert URL in out
    assert out.startswith("\n\n")


def test_html_body_escapes_body_and_has_single_anchor():
    out = html_body("hi <script>alert(1)</script>\nsecond line", URL)
    assert "&lt;script&gt;" in out
    assert "<script>" not in out
    assert out.count("<a ") == 1
    assert f'href="{URL}"' in out
    assert "Sent with" in out


def test_html_body_converts_newlines_to_br():
    out = html_body("line one\nline two", URL)
    assert "<br>" in out
    assert "line one" in out and "line two" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd api && uv run pytest tests/test_email_footer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.tools.gmail.footer'`.

- [ ] **Step 3: Write the implementation**

Create `api/app/tools/gmail/footer.py`:

```python
"""Pure builders for the subtle "Sent with rotom" attribution footer.

No I/O, no settings, no MIME — just strings, so it's trivially unit-tested.
The footer is appended below the email body (which already carries the user's
personal sign-off) at send/save time; it is never stored in the draft.
"""

import html

_PHRASE = "Sent with rotom"


def plain_footer(url: str) -> str:
    """Plain-text footer line for the text/plain alternative."""
    return f"\n\n{_PHRASE} · {url}"


def html_body(body: str, url: str) -> str:
    """Render the plain-text body as a minimal HTML document with the anchor footer.

    Body is HTML-escaped and newlines become <br>. All styling is inline because
    email clients strip <style>/<head>. The footer is muted and small.
    """
    safe_body = html.escape(body).replace("\n", "<br>")
    safe_url = html.escape(url, quote=True)
    footer = (
        '<div style="margin-top:24px;color:#9ca3af;font-size:12px;">'
        f'Sent with <a href="{safe_url}" '
        'style="color:#9ca3af;text-decoration:underline;">rotom</a></div>'
    )
    return (
        '<div style="font-family:sans-serif;font-size:14px;color:#111;">'
        f"{safe_body}{footer}</div>"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd api && uv run pytest tests/test_email_footer.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add api/app/tools/gmail/footer.py api/tests/test_email_footer.py
git commit -m "feat(email): add 'Sent with rotom' footer string builders"
```

---

## Task 2: `build_mime` footer support + GmailAccount forwarding

**Files:**
- Modify: `api/app/tools/gmail/client.py:79-95` (`build_mime`), `:150-156` (`send_message`), `:158-174` (`create_gmail_draft`)
- Test: `api/tests/test_email_footer.py`

- [ ] **Step 1: Write the failing tests**

Append to `api/tests/test_email_footer.py`:

```python
def _decode(raw):
    return message_from_bytes(base64.urlsafe_b64decode(raw))


def test_build_mime_no_footer_is_plain_text():
    from app.tools.gmail.client import build_mime
    msg = _decode(build_mime("r@x.com", "Hello", "Hi there"))
    assert msg.get_content_type() == "text/plain"


def test_build_mime_with_footer_is_multipart_alternative():
    from app.tools.gmail.client import build_mime
    msg = _decode(build_mime("r@x.com", "Hello", "Hi there", footer_url=URL))
    assert msg.get_content_type() == "multipart/alternative"
    types = {p.get_content_type() for p in msg.walk()}
    assert "text/plain" in types and "text/html" in types
    html_part = next(p for p in msg.walk() if p.get_content_type() == "text/html")
    plain_part = next(p for p in msg.walk() if p.get_content_type() == "text/plain")
    assert URL in html_part.get_payload(decode=True).decode()
    assert URL in plain_part.get_payload(decode=True).decode()


def test_build_mime_with_footer_and_attachment_is_mixed(tmp_path):
    from app.tools.gmail.client import build_mime
    f = tmp_path / "resume.pdf"
    f.write_bytes(b"%PDF-1.4 fake")
    msg = _decode(build_mime("r@x.com", "Role", "See attached",
                             attachments=[str(f)], footer_url=URL))
    assert msg.get_content_type() == "multipart/mixed"
    subtypes = {p.get_content_type() for p in msg.walk()}
    assert "multipart/alternative" in subtypes
    names = [p.get_filename() for p in msg.walk() if p.get_filename()]
    assert "resume.pdf" in names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd api && uv run pytest tests/test_email_footer.py -k build_mime -v`
Expected: `test_build_mime_no_footer_is_plain_text` PASSES (current behavior), the two footer tests FAIL (`build_mime() got an unexpected keyword argument 'footer_url'`).

- [ ] **Step 3: Implement `build_mime` footer support**

Replace `build_mime` (currently `api/app/tools/gmail/client.py:79-95`) with:

```python
def build_mime(to, subject, body, attachments=(), in_reply_to="", references="", footer_url=""):
    if subject and not subject.lower().startswith("re:") and in_reply_to:
        subject = f"Re: {subject}"

    if footer_url:
        from app.tools.gmail.footer import plain_footer, html_body
        content = MIMEMultipart("alternative")
        content.attach(MIMEText(body + plain_footer(footer_url), "plain"))
        content.attach(MIMEText(html_body(body, footer_url), "html"))
    else:
        content = MIMEText(body)

    if attachments:
        outer = MIMEMultipart()  # multipart/mixed
        outer.attach(content)
        for path in attachments:
            with open(path, "rb") as fh:
                part = MIMEApplication(fh.read(), Name=os.path.basename(path))
            part["Content-Disposition"] = f'attachment; filename="{os.path.basename(path)}"'
            outer.attach(part)
    else:
        outer = content

    outer["To"] = to
    outer["Subject"] = subject
    if in_reply_to:
        outer["In-Reply-To"] = in_reply_to
        outer["References"] = (f"{references} {in_reply_to}").strip() if in_reply_to not in references else references
    return base64.urlsafe_b64encode(outer.as_bytes()).decode()
```

- [ ] **Step 4: Run the footer + existing gmail tests**

Run: `cd api && uv run pytest tests/test_email_footer.py tests/test_gmail_client.py -v`
Expected: all pass (the existing `build_mime` tests still pass — the no-footer path is unchanged).

- [ ] **Step 5: Forward `footer_url` from GmailAccount methods**

In `api/app/tools/gmail/client.py`, change `send_message` (`:150`) and `create_gmail_draft` (`:158`) signatures and their `build_mime(...)` calls to accept and pass `footer_url`.

`send_message`:
```python
    def send_message(self, to, subject, body, attachments=(), thread_id=None,
                     in_reply_to="", references="", footer_url=""):
        raw = build_mime(to, subject, body, attachments, in_reply_to, references, footer_url=footer_url)
        msg = {"raw": raw}
        if thread_id:
            msg["threadId"] = thread_id
        return self.service.users().messages().send(userId="me", body=msg).execute()
```

`create_gmail_draft`:
```python
    def create_gmail_draft(self, to, subject, body, attachments=(), thread_id=None,
                           in_reply_to="", references="", gmail_draft_id=None, footer_url=""):
        from googleapiclient.errors import HttpError
        raw = build_mime(to, subject, body, attachments, in_reply_to, references, footer_url=footer_url)
        message = {"raw": raw}
        if thread_id:
            message["threadId"] = thread_id
        body_obj = {"message": message}
        drafts = self.service.users().drafts()
        if gmail_draft_id:
            try:
                return drafts.update(userId="me", id=gmail_draft_id, body=body_obj).execute()
            except HttpError as e:
                if e.resp.status == 404:
                    return drafts.create(userId="me", body=body_obj).execute()
                raise
        return drafts.create(userId="me", body=body_obj).execute()
```

- [ ] **Step 6: Run the full gmail + footer suite**

Run: `cd api && uv run pytest tests/test_email_footer.py tests/test_gmail_client.py -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add api/app/tools/gmail/client.py api/tests/test_email_footer.py
git commit -m "feat(email): build_mime emits multipart/alternative footer when footer_url set"
```

---

## Task 3: Config settings + .env.example

**Files:**
- Modify: `api/app/config.py:103-108`
- Modify: `api/.env.example`
- Test: `api/tests/test_email_footer.py`

- [ ] **Step 1: Write the failing test**

Append to `api/tests/test_email_footer.py`:

```python
def test_settings_have_footer_defaults():
    from app.config import Settings
    s = Settings()
    assert s.email_footer_enabled is True
    assert s.email_footer_url == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && uv run pytest tests/test_email_footer.py::test_settings_have_footer_defaults -v`
Expected: FAIL with `AttributeError` / pydantic missing-field error.

- [ ] **Step 3: Add the settings**

In `api/app/config.py`, in the "Drafts / Outreach" block (currently `:103-108`), add the two fields after `soul_file`:

```python
    # --- Drafts / Outreach ---
    user_name: str = ""
    user_signature: str = ""
    outreach_account: str = ""        # empty -> first of account_names
    attachments: str = ""
    soul_file: str = ""
    # "Sent with rotom" footer. URL is the hard prerequisite (empty -> no footer
    # ever). `enabled` is the dashboard switch's default + the fallback for
    # programmatic sends that omit the per-request flag.
    email_footer_enabled: bool = True   # EMAIL_FOOTER_ENABLED
    email_footer_url: str = ""          # EMAIL_FOOTER_URL
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && uv run pytest tests/test_email_footer.py::test_settings_have_footer_defaults -v`
Expected: PASS.

- [ ] **Step 5: Document in .env.example**

In `api/.env.example`, add near the other draft/outreach vars (e.g. after `USER_SIGNATURE`):

```bash
# "Sent with rotom" email footer. Footer only renders when EMAIL_FOOTER_URL is set.
# EMAIL_FOOTER_ENABLED is the dashboard switch's default state (and the fallback
# for non-dashboard sends).
EMAIL_FOOTER_ENABLED=true
EMAIL_FOOTER_URL=
```

(If those exact var names already differ in `.env.example`, match the file's existing casing/section style — but keep the `EMAIL_FOOTER_ENABLED` / `EMAIL_FOOTER_URL` names.)

- [ ] **Step 6: Commit**

```bash
git add api/app/config.py api/.env.example api/tests/test_email_footer.py
git commit -m "feat(email): add EMAIL_FOOTER_ENABLED/EMAIL_FOOTER_URL settings"
```

---

## Task 4: Routes — footer param, resolution, and `rotom_footer_default`

**Files:**
- Modify: `api/app/api/routes.py:49-85` (`_draft_json`), `:399-447` (`save_to_gmail`), `:449-501` (`send_draft`)
- Test: `api/tests/test_api_routes.py:13-29` (FakeAccount + fixture), plus new tests

- [ ] **Step 1: Extend FakeAccount and write failing tests**

In `api/tests/test_api_routes.py`, replace the `FakeAccount` class (`:13-18`) with one that records `footer_url` and supports save-to-gmail:

```python
class FakeAccount:
    def __init__(self):
        self.sent: list[dict] = []
        self.saved: list[dict] = []

    def send_message(self, to, subject, body, attachments=(), thread_id=None,
                     in_reply_to="", references="", footer_url=""):
        self.sent.append({"to": to, "thread_id": thread_id, "body": body, "footer_url": footer_url})

    def create_gmail_draft(self, to, subject, body, attachments=(), thread_id=None,
                           in_reply_to="", references="", gmail_draft_id=None, footer_url=""):
        self.saved.append({"to": to, "body": body, "footer_url": footer_url})
        return {"id": "gd-123"}

    def delete_gmail_draft(self, gmail_draft_id):
        pass
```

Then append these tests (they reuse the existing `client` fixture and `_seed` helper; check `_seed`'s return signature in the file and call it the same way other tests do):

```python
def test_send_with_footer_true_passes_url(client, monkeypatch):
    monkeypatch.setattr("app.config.get_settings",
                        lambda: _settings_with(email_footer_enabled=False,
                                               email_footer_url="https://r.example.com"))
    draft_id, _ = _seed()
    client.post(f"/api/drafts/{draft_id}/send", headers=AUTH, json={"rotom_footer": True})
    assert client.sender.sent[-1]["footer_url"] == "https://r.example.com"


def test_send_with_footer_false_passes_empty(client, monkeypatch):
    monkeypatch.setattr("app.config.get_settings",
                        lambda: _settings_with(email_footer_enabled=True,
                                               email_footer_url="https://r.example.com"))
    draft_id, _ = _seed()
    client.post(f"/api/drafts/{draft_id}/send", headers=AUTH, json={"rotom_footer": False})
    assert client.sender.sent[-1]["footer_url"] == ""


def test_send_without_field_falls_back_to_global(client, monkeypatch):
    monkeypatch.setattr("app.config.get_settings",
                        lambda: _settings_with(email_footer_enabled=True,
                                               email_footer_url="https://r.example.com"))
    draft_id, _ = _seed()
    client.post(f"/api/drafts/{draft_id}/send", headers=AUTH)
    assert client.sender.sent[-1]["footer_url"] == "https://r.example.com"


def test_draft_json_exposes_rotom_footer_default(client, monkeypatch):
    monkeypatch.setattr("app.config.get_settings",
                        lambda: _settings_with(email_footer_enabled=True,
                                               email_footer_url="https://r.example.com"))
    draft_id, _ = _seed()
    resp = client.get(f"/api/drafts/{draft_id}", headers=AUTH)
    assert resp.json()["rotom_footer_default"] is True
```

Add this helper near the top of the test file (after the imports), building a real `Settings` with overrides so all the other settings fields still exist:

```python
def _settings_with(**overrides):
    from app.config import Settings
    return Settings(api_token=TOKEN, **overrides)
```

> Note: routes call `get_settings()` via `from app.config import get_settings` *inside* the handler, so patch `app.config.get_settings`. If a test shows the patch isn't taking effect, patch `app.api.routes.get_settings` as well — but the in-handler import resolves `app.config.get_settings` at call time, so the `app.config` patch is the correct target.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd api && uv run pytest tests/test_api_routes.py -k "footer or rotom_footer_default" -v`
Expected: FAIL — `footer_url` always `""` (param ignored) and `rotom_footer_default` KeyError.

- [ ] **Step 3: Add the `FooterOption` model**

In `api/app/api/routes.py`, near the other body models (e.g. just before `class DraftUpdate` at `:88`), add:

```python
class FooterOption(BaseModel):
    rotom_footer: bool | None = None
```

- [ ] **Step 4: Add `rotom_footer_default` to `_draft_json`**

In `_draft_json` (`:49-85`), `settings = get_settings()` is already in scope (`:57`). Add the field to the `data` dict (after `"messages": [...]`, before the closing brace at `:80`):

```python
        "rotom_footer_default": settings.email_footer_enabled and bool(settings.email_footer_url),
```

- [ ] **Step 5: Resolve and pass `footer_url` in `send_draft`**

Change `send_draft`'s signature (`:450`) to accept the body, and pass the resolved URL to `send_message`:

```python
    async def send_draft(draft_id: int, opts: FooterOption = FooterOption()) -> dict:
        from app.config import get_settings, resolve_attachments
        import json
        from app.store.db import DraftKind
```

Then, just before the `account.send_message(...)` call (`:482`), compute the URL and add it to the call:

```python
            s_cfg = get_settings()
            use_footer = opts.rotom_footer if opts.rotom_footer is not None else s_cfg.email_footer_enabled
            footer_url = s_cfg.email_footer_url if (use_footer and s_cfg.email_footer_url) else ""

            account.send_message(
                to=to_addr,
                subject=subject,
                body=draft.body,
                attachments=paths,
                thread_id=thread_id,
                in_reply_to=in_reply_to,
                references=references,
                footer_url=footer_url,
            )
```

- [ ] **Step 6: Resolve and pass `footer_url` in `save_to_gmail`**

Change `save_to_gmail`'s signature (`:400`):

```python
    async def save_to_gmail(draft_id: int, opts: FooterOption = FooterOption()) -> dict:
```

Then, just before the `account.create_gmail_draft(...)` call (`:430`), add the same resolution and pass `footer_url`:

```python
            s_cfg = get_settings()
            use_footer = opts.rotom_footer if opts.rotom_footer is not None else s_cfg.email_footer_enabled
            footer_url = s_cfg.email_footer_url if (use_footer and s_cfg.email_footer_url) else ""

            try:
                res = account.create_gmail_draft(
                    to=to_addr,
                    subject=subject,
                    body=draft.body,
                    attachments=paths,
                    thread_id=thread_id,
                    in_reply_to=in_reply_to,
                    references=references,
                    gmail_draft_id=draft.gmail_draft_id,
                    footer_url=footer_url,
                )
```

- [ ] **Step 7: Run the route tests**

Run: `cd api && uv run pytest tests/test_api_routes.py -v`
Expected: all pass (new footer tests + existing draft/send tests).

- [ ] **Step 8: Run the full API suite (regression)**

Run: `cd api && uv run pytest -q`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add api/app/api/routes.py api/tests/test_api_routes.py
git commit -m "feat(email): footer param on send/save routes + rotom_footer_default in draft json"
```

---

## Task 5: Frontend — Switch component + threading the flag

**Files:**
- Create: `web/components/ui/switch.tsx`
- Modify: `web/lib/api.ts` (`DraftItem` `:35-49`, `postDraftAction` `:124-125`, `saveToGmail` `:121-122`)
- Modify: `web/lib/actions.ts` (`sendDraft` `:58-68`, `saveToGmailAction` `:90-102`)
- Modify: `web/components/draft-composer.tsx`

- [ ] **Step 1: Add the shadcn Switch component**

Run from the `web/` directory:

```bash
cd web && npx shadcn@latest add switch
```

Expected: creates `web/components/ui/switch.tsx` and installs `@radix-ui/react-switch` if missing. If the CLI is unavailable offline, hand-author `web/components/ui/switch.tsx` matching the existing `web/components/ui/checkbox.tsx` style (Radix primitive + `cn()`); confirm the export is `Switch`.

Verify: `test -f web/components/ui/switch.tsx && echo OK`

- [ ] **Step 2: Add `rotom_footer_default` to the `DraftItem` type and footer params to the API client**

In `web/lib/api.ts`, add the field to the `DraftItem` interface (`:35-49`), after `sent_at`:

```typescript
  sent_at: string | null;
  rotom_footer_default: boolean;
  email: EmailItem | null;
```

Replace `saveToGmail` (`:121-122`) and `postDraftAction` (`:124-125`) with versions that accept the flag:

```typescript
export const saveToGmail = (id: number, rotomFooter?: boolean) =>
  apiFetch<DraftItem>(`/api/drafts/${id}/save-to-gmail`, {
    method: "POST",
    body: JSON.stringify({ rotom_footer: rotomFooter ?? null }),
  });

export const postDraftAction = (id: number, action: "send" | "discard", rotomFooter?: boolean) =>
  apiFetch<DraftItem>(`/api/drafts/${id}/${action}`, {
    method: "POST",
    ...(action === "send" ? { body: JSON.stringify({ rotom_footer: rotomFooter ?? null }) } : {}),
  });
```

(`discard` sends no body — its route takes no `FooterOption`.)

- [ ] **Step 3: Thread `rotomFooter` through the server actions**

In `web/lib/actions.ts`, update `sendDraft` (`:58`) and `saveToGmailAction` (`:90`) to take and forward the flag.

`sendDraft`:
```typescript
export async function sendDraft(id: number, update: { body?: string; subject?: string | null; to_addr?: string | null; account?: string | null; attachments?: string[] }, rotomFooter?: boolean): Promise<{ ok: boolean; error?: string }> {
  try {
    // Persist any last edits, then send — the explicit human action is the HITL gate.
    await patchDraft(id, update);
    await postDraftAction(id, "send", rotomFooter);
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "send failed" };
  }
  revalidatePath("/email/drafts");
  redirect("/email/drafts?sent=1");
}
```

`saveToGmailAction`:
```typescript
export async function saveToGmailAction(id: number, update?: { body?: string; subject?: string | null; to_addr?: string | null; account?: string | null; attachments?: string[] }, rotomFooter?: boolean): Promise<{ ok: boolean; error?: string }> {
  try {
    if (update) {
      await patchDraft(id, update);
    }
    await saveToGmail(id, rotomFooter);
    revalidatePath(`/email/drafts/${id}`);
    revalidatePath(`/drafts/${id}`);
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "save to gmail failed" };
  }
}
```

- [ ] **Step 4: Add the switch to the draft composer and wire it in**

In `web/components/draft-composer.tsx`:

a) Add imports (after the existing `ui` imports, ~`:11`):
```typescript
import { Switch } from "@/components/ui/switch";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
```

b) Add state initialized from the draft default (after the `attachments` state, ~`:18`):
```typescript
  const [rotomFooter, setRotomFooter] = useState(draft.rotom_footer_default);
```

c) In the footer's left side of the `CardFooter` (`:141-144`), place the switch next to Discard. Replace the `CardFooter` opening + Discard block so the switch sits on the left with the Discard button:

```tsx
        <CardFooter className="justify-between border-t p-4">
          <div className="flex items-center gap-3">
            <Button variant="ghost" className="text-destructive hover:text-destructive" disabled={pending} onClick={() => run(() => discardDraft(draft.id))}>
              <Trash2 className="mr-2 h-4 w-4"/> Discard
            </Button>
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="inline-flex">
                  <Switch
                    checked={rotomFooter}
                    onCheckedChange={setRotomFooter}
                    disabled={pending}
                    aria-label="Sent with rotom footer"
                  />
                </span>
              </TooltipTrigger>
              <TooltipContent>Append a &ldquo;Sent with rotom&rdquo; footer to this email</TooltipContent>
            </Tooltip>
          </div>
```

d) Pass `rotomFooter` into the Send and Save-to-Gmail handlers (`:149` and `:152`):

```tsx
            <Button variant="secondary" disabled={pending} onClick={() => run(() => saveToGmailAction(draft.id, { body, subject, to_addr: toAddr, attachments }, rotomFooter))}>
              <Mail className="mr-2 h-4 w-4"/> Save to Gmail
            </Button>
            <Button disabled={pending || !body.trim() || (draft.kind === "outreach" && !toAddr.trim())} onClick={() => run(() => sendDraft(draft.id, { body, subject, to_addr: toAddr, attachments }, rotomFooter))}>
              {pending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Send className="mr-2 h-4 w-4"/>} Send
            </Button>
```

> The draft detail page is wrapped in a `TooltipProvider` at the app shell if tooltips are already used elsewhere; if `tsc`/runtime complains that `Tooltip` needs a provider, wrap the app once in `web/app/layout.tsx` with `TooltipProvider` (check whether it's already there before adding).

- [ ] **Step 5: Type-check and lint the web app**

Run: `cd web && npx tsc --noEmit`
Expected: no errors.

Run (if the project has it): `cd web && npm run lint`
Expected: clean (or no new warnings).

- [ ] **Step 6: Commit**

```bash
git add web/components/ui/switch.tsx web/lib/api.ts web/lib/actions.ts web/components/draft-composer.tsx web/package.json web/package-lock.json
git commit -m "feat(web): per-draft 'Sent with rotom' footer switch (default from global config)"
```

---

## Task 6: Update TASKS.md

**Files:**
- Modify: `TASKS.md`

- [ ] **Step 1: Mark the feature done and fix the stale outreach note**

In `TASKS.md`, under "Near-term features", replace the email-signature line:

```markdown
- [x] **Email "Sent with rotom" footer** — implemented (2026-06-13). Multipart/alternative
      HTML footer with a clickable anchor; per-draft switch (default from global config),
      applied at send + save-to-gmail. 📄 Spec: `docs/superpowers/specs/2026-06-13-email-footer-design.md`
```

Also fix the stale recruiter-outreach status if present (outreach drafts ARE implemented; only auto-generate-from-post is v2).

- [ ] **Step 2: Commit**

```bash
git add TASKS.md
git commit -m "docs: mark 'Sent with rotom' footer done in TASKS.md"
```

---

## Manual verification (after all tasks)

1. Set `EMAIL_FOOTER_URL=https://rotom.example.com` (or any https URL) and `EMAIL_FOOTER_ENABLED=true` in `api/.env`; restart the API.
2. Open a draft in the dashboard → the switch shows **on** (matches global default). Hover → tooltip explains it.
3. "Save to Gmail" with the switch **on** → open the draft in Gmail: footer renders as a muted "Sent with rotom" line with "rotom" linked; body intact above it.
4. Toggle the switch **off**, Save to Gmail again → Gmail draft is plain, no footer.
5. Set `EMAIL_FOOTER_ENABLED=false`, reload a draft → switch shows **off** by default.
6. (Optional, sends a real email) Send a draft with the switch on → received mail shows the footer in HTML clients and a clean "Sent with rotom · <url>" line in plain-text clients.
