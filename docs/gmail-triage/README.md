# Gmail triage

Deterministic pipeline over N Gmail accounts: fetch → dedup → **screen** → rules →
classify → store → auto-draft → digest. Triggered by cron (`GMAIL_TRIAGE_CRON`) or from
chat (`run_gmail_triage` agent tool). Lives in `api/app/tools/gmail/`.

## Flow

1. **Fetch** (`client.py`) — per account, query `in:inbox after:<epoch>` where epoch =
   now − `GMAIL_TRIAGE_LOOKBACK_HOURS`. Gmail's `newer_than:` is day-granular only, so
   hour-level lookback uses `after:` with a unix timestamp. Per-account failures are
   collected, never fatal (degraded-state reporting).
2. **Dedup** (`pipeline.py`) — `(account, message_id)` checked against the
   `processed_messages` ledger **before any LLM call**. Replies in old threads have new
   message ids, so they are triaged; literal re-fetches cost nothing.
3. **Screen** (`injection.py`, the `screen_fn` dependency) — prompt-injection guardrail:
   heuristics score each email, borderline cases go to a batched LLM judge, flagged mail
   is **quarantined** (`category=skip`, `suspicious=True`) and bypasses classify + draft.
   Full details in [`docs/guardrails/`](../guardrails/).
4. **Rules** (`classifier.py`) — deterministic, zero tokens:
   `KEY_SENDERS` substring on sender → critical; `EXCLUDED_TOPICS` substring on
   subject+sender (NOT body — footer false positives) → skip.
5. **Classify** — ONE batched LLM call for the ambiguous rest, structured output
   (`BatchClassification`), categories critical/needs_reply/fyi/skip + urgency 0–3 +
   one-line reason. Bodies wrapped in `<untrusted_email_content>` tags.
6. **Store** — Email rows + ledger entries in one session.
7. **Auto-draft** — needs_reply emails get a reply draft (draft-role model), saved as
   `Draft(status=pending)`. Draft failures degrade; the email is still stored.
8. **Digest** — Telegram message: a `⚠ N quarantined` line for flagged mail, then
   critical/needs_reply listed with dashboard deep links, fyi/skip collapsed to counts,
   per-account errors as ⚠ lines.

## Auth

One GCP OAuth client (readonly + send scopes); one refresh token per account from
`auth_setup.py`, stored as `GMAIL_<NAME>_REFRESH_TOKEN`. Consent-screen branding is
project-level. Refresh tokens are bound to the client ID.

## Gotchas we hit

- Dedup must run **before** classification or you pay LLM costs on every run.
- Don't lazy-load relationships on detached ORM rows (digest builds from
  `TriageResult.drafted_email_ids`, not `email.drafts`).
- `References` header on replies: only append the message id if not already present.
- Groq `llama-3.1-8b-instant` emits malformed tool calls — use `llama-3.3-70b-versatile`.

## Key files

`client.py` (fetch/send/MIME) · `auth_setup.py` (one-time OAuth CLI) ·
`classifier.py` · `drafter.py` · `pipeline.py` (run_triage + format_digest) ·
`service.py` (wires settings+LLMs, used by cron and agent tool)
