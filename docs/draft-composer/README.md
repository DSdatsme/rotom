# Conversational Draft Composer

The draft composer provides a two-pane UI (chat + editable preview) to incrementally refine email replies and cold outreach.

## How it works

- **Architecture**: A `Draft` owns a conversational thread (`DraftMessage`s). The user chats with an LLM agent on the left pane to iterate on the draft content shown on the right pane.
- **LLM Context**: The `ComposerContext` feeds the entire message history, identity (`USER_NAME`/`USER_SIGNATURE`), the **SOUL persona** (`_read_soul(SOUL_FILE)` — a markdown voice/persona file editable in the dashboard at `/soul`), available attachments, and the original source email (for replies).
- **Recipient extraction (outreach)**: the model may extract a recipient from pasted content *even if obfuscated* (e.g. `jon at example dot com` → `jon@example.com`) — useful for a HN/job post — but **never fabricates** one. The `To` field stays editable and send is human-gated.
- **Save to Gmail**: builds a multipart MIME draft and upserts it via the Gmail API (`gmail.compose` scope). Re-saving **patches the local draft first**, then updates the stored `gmail_draft_id`; if that Gmail draft was deleted server-side (404), it **recreates and re-persists** the new id. Send deletes the stale Gmail draft.
- **"Sent with rotom" footer**: a subtle, clickable attribution footer appended to outgoing mail at **send/save time** (never stored in `draft.body`, distinct from the LLM-generated `USER_SIGNATURE` sign-off). When on, `build_mime` emits `multipart/alternative` — a plain-text part (`body` + `Sent with rotom · <url>`) and an HTML part (escaped body + an inline-styled `<a>`); when off it stays byte-for-byte `text/plain`. A footer renders only if `EMAIL_FOOTER_URL` is set. The dashboard composer shows an **unlabeled switch** (tooltip on hover) initialized from the global default (`EMAIL_FOOTER_ENABLED`); its state is **not persisted** — it rides along the send/save request as `rotom_footer`, the route resolves the effective URL (`_resolve_footer_url`) and passes it to the MIME builder. Programmatic/agent sends omit the flag and fall back to the global default. Draft JSON exposes `rotom_footer_default` so the switch initializes correctly.
- **Untrusted Content**: Pasted outreach text and incoming emails are bounded by `<untrusted_content>` delimiters to prevent prompt injection.
- **Attachments**: Defined purely in `.env`. They appear as checkboxes in the UI.
- **Rendering**: the composer is instructed to use `\n\n` paragraphs and the UI renders chat + preview with `whitespace-pre-wrap`, so multi-paragraph drafts keep their breaks.
- **Listing**: outreach drafts have no source email, so the drafts query uses an **outer join** (`email_id` nullable) and the home "Drafts" count filters to `kind === "reply"`.
- **Interactive, not a tracked run**: chat-message composes record LLM usage as *adhoc* (and surface in the Logs explorer) but don't create observability run rows; a compose error shows **inline in the chat** rather than as a 500. Only draft *regeneration* is a tracked run. See [`../observability/`](../observability/).

## Key Files
- `api/app/store/db.py`: `Draft` and `DraftMessage` models
- `api/app/tools/drafts/composer.py`: The LLM orchestration for generating drafts
- `api/app/tools/gmail/client.py`: Multipart MIME builder and Gmail API clients (`build_mime(..., footer_url=…)`)
- `api/app/tools/gmail/footer.py`: pure `plain_footer` / `html_body` builders for the footer
- `api/app/api/routes.py`: `_resolve_footer_url` + `rotom_footer` on the send/save endpoints
- `web/components/draft-composer.tsx`: Two-pane UI component (+ the footer switch)
- `web/components/ui/switch.tsx`: base-ui Switch used for the footer toggle

## Gotchas & Operator Setup
If running this for the first time:
1. Ensure your `.env` contains `USER_NAME`, `USER_SIGNATURE`, `OUTREACH_ACCOUNT`, `SOUL_FILE` (e.g. `./data/SOUL.md`), and `ATTACHMENTS` (e.g. `resume:./data/attachments/resume.pdf`).
   - For the "Sent with rotom" footer, set `EMAIL_FOOTER_URL` (e.g. your rotom site) — empty means no footer regardless of the switch. `EMAIL_FOOTER_ENABLED` (default `true`) is the switch's default state.
2. Make sure any attachment files referenced actually exist on disk (`mkdir -p data/attachments`).
3. **Re-run `auth_setup.py`** for each Gmail account to grant the new `gmail.compose` scope! Without this, the Gmail API will return 403s when saving to Gmail.
