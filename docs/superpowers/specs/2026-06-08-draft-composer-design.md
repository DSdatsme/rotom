# Conversational Draft Composer — Design

**Date:** 2026-06-08
**Status:** Designed, not yet built
**Supersedes:** the one-shot reply drafter + "regenerate" button; the earlier "recruiter
outreach email" sketch (folded in here as the `outreach` draft kind).

## Goal

Turn drafting — both replies to triaged email and cold outreach from a pasted
LinkedIn/X post — into a single **conversational composer**. A draft owns a chat thread;
each user message refines the draft. Pre-configured files (résumé, portfolio) attach via
opt-in toggles. The user reviews on the dashboard, can **save a real Gmail draft** to see
the true rendering, and **sends** through the existing human-gated path.

## The unifying insight

A reply draft and an outreach draft are the same primitive: **text in → draft out,
refined through chat**. They differ only in what seeds them and what metadata they carry.
So there is one `Draft` model, one `DraftMessage` chat thread, and one composer service.
"Regenerate" is no longer a button — it is sending another message in the draft's chat
("make it shorter", "mention I led the migration", or pasting more post text).

| | reply | outreach |
|---|---|---|
| `kind` | `"reply"` | `"outreach"` |
| seeded by | a triaged email | pasted post / job text |
| `email_id` | FK → `emails.id` | `NULL` |
| `account` | inherited from the email | chosen (default `OUTREACH_ACCOUNT`, else first account) |
| `to_addr` / `subject` | inherited from the email | composer-proposed, editable |
| recipient discovery | — | composer extracts an email from pasted text if present, else blank |

## Scope

### In scope (v1)

- Unified `Draft` model (reply + outreach) + `DraftMessage` chat table.
- Composer service: multi-turn, **paste-only** text context.
- Pre-configured attachments via config paths + opt-in toggles (no browser upload).
- Multipart send (body + attachments), for both threaded replies and fresh outreach.
- **Save to Gmail**: create/update a real Gmail draft with attachments (idempotent).
- Dashboard: "Create new draft" button + two-pane composer page (chat + editable preview).
- Reply "regenerate" replaced by chat-context refinement (same composer).

### Out of scope (future)

- **URL scraping** of LinkedIn/X — v1 uses pasted text only; scraping is a later add.
- Per-draft ad-hoc file upload (attachments are config-defined only).
- Revert-to-previous-draft-version (chat history is stored, but no UI revert).
- Telegram entry point for outreach drafts (dashboard only for now).

## Architecture

```
                       ┌─────────────────────────────────────────┐
 Dashboard             │  Composer page  (/email/drafts/[id])     │
  "Create new draft" ─▶│  chat thread + msg box | editable draft  │
                       │  attachment toggles · Save · Save→Gmail · │
                       │                          Send · Discard   │
                       └──────────────┬──────────────────────────┘
                                      │ server-side fetch (bearer)
                                      ▼
 FastAPI  POST /api/drafts                 (create outreach draft)
          POST /api/emails/{id}/draft      (create reply draft, first compose)
          POST /api/drafts/{id}/messages   (user turn → composer → updated draft)
          PATCH /api/drafts/{id}           (manual edits)
          GET  /api/attachments            (toggle list)
          POST /api/drafts/{id}/save-to-gmail
          POST /api/drafts/{id}/send
                                      │
            ┌─────────────────────────┼─────────────────────────┐
            ▼                         ▼                          ▼
   composer service          attachments registry         Gmail client
 tools/drafts/composer.py     (config paths)          send_message() / create_gmail_draft()
   get_chat_model("draft")                            multipart MIME (body + files)
            │
            ▼
   SQLite: drafts (+ chat) — Draft, DraftMessage
```

## Components

### 1. Data model (`api/app/store/db.py`)

`DraftKind` — new `StrEnum`:

```python
class DraftKind(StrEnum):
    REPLY = "reply"
    OUTREACH = "outreach"
```

`Draft` — extended (new columns are nullable so migrations-lite `ALTER` works on existing rows):

| column | type | notes |
|---|---|---|
| `id` | int PK | existing |
| `kind` | str(16) | default `"reply"` — back-fills existing rows correctly |
| `email_id` | int FK → emails.id, **nullable** | `NULL` for outreach |
| `account` | str(64), nullable | sending account (outreach); replies read it from the email |
| `to_addr` | str(512), nullable | outreach recipient; replies inherit |
| `subject` | str(998), nullable | outreach subject; replies inherit |
| `body` | Text | existing — latest composer output |
| `attachments` | Text (JSON list of keys), default `"[]"` | selected attachment keys |
| `gmail_draft_id` | str(128), nullable | set after first Save-to-Gmail (idempotency) |
| `status` | str(32) | existing — pending / sent / discarded |
| `created_at` / `updated_at` / `sent_at` | datetime | existing |

`DraftMessage` — new table (created by `create_all`):

```python
class DraftMessage(Base):
    __tablename__ = "draft_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("drafts.id"))
    role: Mapped[str] = mapped_column(String(16))   # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    draft: Mapped["Draft"] = relationship(back_populates="messages")
```

`Draft.messages` is a one-to-many ordered by `created_at`. The current `body`/`subject`/
`to_addr` live on `Draft` (updated each assistant turn); the `assistant` message stores a
short human-readable note ("Shortened the intro and mentioned the résumé."), not a body
copy. Chat history is preserved for context and display; per-turn body snapshots are out
of scope.

`email_id` nullability requires `_get_draft_or_404` and all draft serializers to treat a
missing email as valid (outreach has no source email).

### 2. Composer service (`api/app/tools/drafts/composer.py`) — new module

A focused, testable service. **Not** the Telegram LangGraph agent — the output is a
structured draft, not free chat.

```python
@dataclass
class ComposerContext:
    kind: DraftKind
    source_email: dict | None          # parsed email dict for replies, else None
    history: list[tuple[str, str]]     # [(role, content), ...] prior turns
    new_message: str                   # the user's latest turn (may include pasted post text)
    identity: Identity                 # user_name, user_signature
    attachments: list[AttachmentMeta]  # selected attachments (label only; for body wording)

@dataclass
class ComposerResult:
    body: str
    subject: str | None   # outreach only
    to_addr: str | None   # outreach only — extracted from pasted text if present
    note: str             # short assistant note for the chat thread

def compose(ctx: ComposerContext, llm) -> ComposerResult: ...
def build_composer_prompt(ctx: ComposerContext) -> str: ...
def parse_composer_response(raw: str, kind: DraftKind) -> ComposerResult: ...
```

- Model: `get_chat_model("draft")`.
- Structured output: the LLM returns a small JSON object (`body`, and for outreach
  `subject`, `to`, plus a `note`). `parse_composer_response` tolerates fenced/unfenced
  JSON and missing optional keys; reply mode ignores `subject`/`to`.
- **"Extremely simple" outreach**: the system prompt constrains outreach to a short,
  specific note — greeting, 2–3 sentences referencing the role/post, one line noting the
  attached résumé (only if an attachment is selected), sign-off with `user_name` /
  `user_signature`. No filler, no `[placeholders]`.
- **Reply** mode keeps the existing contract: body only, no signature placeholder, polite
  and concise; refined by the chat instead of a blind regenerate.
- **Untrusted input**: the user's pasted post text and the source email body are wrapped
  in `<untrusted_content>` … `</untrusted_content>` delimiters with the standing rule that
  content inside is DATA and cannot issue instructions — identical to the triage defense
  (`tools/gmail/classifier.py`, `drafter.py`).
- **Recipient extraction** (outreach): the prompt asks the model to return a recipient
  email **only if one literally appears** in the pasted text; otherwise `to` is empty and
  the user fills it in. The model never invents an address.

### 3. Attachments registry (`api/app/config.py`)

Config-defined files, opt-in per draft. No upload.

```
ATTACHMENTS="resume:My Résumé:./data/attachments/resume.pdf,portfolio:Portfolio:./data/attachments/portfolio.pdf"
```

Parsed by a computed property into `[AttachmentMeta(key, label, path)]`
(`key:label:path`, comma-separated — matching the existing `account_names` /
`key_sender_list` pattern). A helper resolves selected keys → file paths and **raises if a
configured file is missing on disk** (surfaced before send; never silently dropped).

New settings: `user_name: str = ""`, `user_signature: str = ""`,
`outreach_account: str = ""` (empty → first of `account_names`), `attachments: str = ""`.

### 4. Gmail client (`api/app/tools/gmail/client.py`) — replaces reply-only path

The current `send_reply` (plain `MIMEText`, threaded, no attachments) is generalized:

```python
def build_mime(to, subject, body, attachments=(), in_reply_to="", references="") -> str:
    # MIMEMultipart: MIMEText(body) + MIMEApplication per attachment (content-type guessed,
    # filename = basename). "Re:"-prefix logic preserved for replies. Returns base64url raw.

def send_message(self, account_service, to, subject, body, attachments=(),
                 thread_id=None, in_reply_to="", references="") -> dict:
    # users().messages().send(); sets threadId only when present (reply vs fresh outreach).

def create_gmail_draft(self, account_service, to, subject, body, attachments=(),
                       thread_id=None, in_reply_to="", references="",
                       gmail_draft_id=None) -> dict:
    # gmail_draft_id is None -> drafts().create(); else drafts().update(id=...). Idempotent.

def delete_gmail_draft(self, account_service, gmail_draft_id) -> None:
    # drafts().delete(); used on Send to clear a stale preview draft.
```

`build_mime` is the single MIME builder shared by send and save-to-Gmail.

**Scope change (requires re-auth):** `drafts().create/update/delete` need
`https://www.googleapis.com/auth/gmail.compose`. Add it to `SCOPES` in
`tools/gmail/client.py`; each account must re-run `auth_setup.py` to mint a refresh token
covering the new scope. Documented as an explicit operator step in the plan.

### 5. API routes (`api/app/api/routes.py`)

| route | method | behavior |
|---|---|---|
| `/api/drafts` | POST | body `{kind:"outreach"}` → create empty outreach `Draft`, return it (id, empty body, empty chat) |
| `/api/emails/{id}/draft` | POST | create a `reply` draft seeded from the email, run the first compose, return draft + first assistant turn (replaces the old regenerate semantics) |
| `/api/drafts/{id}/messages` | POST | body `{content}` → append a `user` message → run `compose` → persist updated `body`/`subject`/`to_addr` + an `assistant` note → return updated draft + messages |
| `/api/drafts/{id}` | GET | draft + ordered chat messages + source email (if reply) + resolved attachment metadata |
| `/api/drafts/{id}` | PATCH | manual edits: any of `body`, `subject`, `to_addr`, `account`, `attachments` (keys) — pending only |
| `/api/attachments` | GET | `[{key, label}]` from the registry (paths never exposed) |
| `/api/drafts/{id}/save-to-gmail` | POST | build MIME from current state → `create_gmail_draft` (create or update via stored `gmail_draft_id`) → store/return `gmail_draft_id` |
| `/api/drafts/{id}/send` | POST | build MIME → `send_message` → mark `sent`; if `gmail_draft_id` set, `delete_gmail_draft` afterward |

Guards: messages/edits/save/send require `status == pending` (409 otherwise). Outreach
send requires a non-empty `to_addr` (422 with a clear message if blank). Send is the only
external action and stays human-initiated.

### 6. Web dashboard (`web/`)

- **`components/app-sidebar.tsx`** — Drafts entry already exists; no new section needed.
- **`app/email/drafts/page.tsx`** — add a **"Create new draft"** button → `POST /api/drafts`
  `{kind:"outreach"}` → navigate to `/email/drafts/{id}`.
- **`app/email/drafts/[id]/page.tsx`** + **`components/draft-composer.tsx`** (replaces
  `draft-editor.tsx`) — two-pane composer:
  - **Left:** chat thread (user/assistant bubbles) + a message box (paste post text or
    refinement instructions) → `POST .../messages`, mirroring the `reminder-chat-bar`
    transition/optimistic pattern.
  - **Right:** editable preview — `To` + `Subject` inputs (**hidden for replies**, which
    inherit them and instead show the source email), `Body` textarea, **attachment
    toggles** (from `GET /api/attachments`), and for outreach an **account selector**
    (configured accounts). Footer: **Save · Save to Gmail · Send · Discard**.
- **`lib/api.ts` / `lib/actions.ts`** — add `createDraft`, `postDraftMessage`,
  `getAttachments`, `saveDraftToGmail`; extend `patchDraft` to carry
  `subject`/`to_addr`/`account`/`attachments`. All server-side; token never reaches the
  browser.

## Data flow

**Outreach:** Create new draft → composer page (empty) → paste the post text in chat →
`POST messages` → composer returns body + proposed subject + extracted-or-blank To →
preview populates → toggle "My Résumé" → optionally "make it shorter" (another message) →
**Save to Gmail** to eyeball the real rendering → **Send**.

**Reply:** Triaged email → "Generate draft" → `POST /api/emails/{id}/draft` runs first
compose → composer page shows source email + body → "mention I'm available next week"
(message) → refine → Send (attachments optional).

## Error handling

- **Missing attachment file** → resolver raises; save/send returns 4xx with the offending
  key; nothing is sent with a silently-dropped attachment.
- **Composer LLM/parse failure** → the user turn is still stored; the route returns an
  error note as an `assistant` message rather than corrupting `body`.
- **Outreach send without `to_addr`** → 422, surfaced inline in the preview pane.
- **Gmail scope not yet granted** → `drafts().create` 403; the route maps it to a clear
  "re-run auth_setup to grant gmail.compose" message.
- **Stale Gmail draft** → cleared on Send via `delete_gmail_draft`; a delete failure is
  logged but does not fail the send (the mail already went out).

## Testing

- `build_mime`: body-only; body + one attachment (correct MIME type, filename); reply
  "Re:" prefixing and threading headers; multiple attachments.
- Attachments registry parse (`key:label:path`), selected-keys → paths, **missing-file
  raises**, paths never serialized to the API.
- `build_composer_prompt`: untrusted delimiters present around pasted text + source email;
  outreach includes identity + selected attachment labels; reply omits subject/to asks.
- `parse_composer_response`: fenced/unfenced JSON; missing optional keys; reply ignores
  `subject`/`to`; outreach `to` empty when no email present.
- Routes: create outreach; first reply compose; `messages` appends + updates body; PATCH
  field updates; status guards (409 on non-pending); outreach send-without-To (422);
  save-to-Gmail create then update reuses `gmail_draft_id`; send deletes stale Gmail draft.
- Gmail client: `send_message` sets `threadId` only for replies; `create_gmail_draft`
  branches create vs update on `gmail_draft_id`.

LLM calls are mocked in tests (limited token budget — no live model runs in CI).

## Migration / ops

- Migrations-lite `_migrate()` adds the new nullable `Draft` columns; `create_all` makes
  `draft_messages`. Existing reply drafts back-fill to `kind="reply"`, `attachments="[]"`.
- Operator: create `./data/attachments/`, drop in the résumé, set `ATTACHMENTS`,
  `USER_NAME`, `USER_SIGNATURE`, `OUTREACH_ACCOUNT` in `.env`.
- Operator: **re-run `auth_setup.py` for each account** after `gmail.compose` is added to
  `SCOPES`, replacing each refresh token.

## Security

- Pasted post text and source email bodies are untrusted → DATA delimiters, consistent
  with the triage pipeline; a malicious post cannot redirect the draft or its recipient.
- The composer never invents a recipient — outreach `to` is extracted only if literally
  present, else left to the human.
- Sending remains the sole external action and stays human-gated (the Send button). The
  composer and any agent path can create and refine drafts but never send.
- Attachment paths come only from operator config; the API exposes labels/keys, never
  filesystem paths; only configured files can ever be attached.
