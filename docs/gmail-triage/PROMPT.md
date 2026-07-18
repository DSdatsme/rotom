# Generation prompt — Gmail triage pipeline

> Paste into an AI coding agent together with `docs/architecture/PROMPT.md` (it assumes
> that skeleton: settings, LLM factory, SQLite store, Telegram channel).

---

Build a multi-account Gmail triage pipeline as a deterministic, dependency-injected
function (NOT an agent loop). It must be callable from a cron job and from a chat-agent
tool, and be fully testable with fakes.

**Gmail access.** One OAuth client app; per-account refresh tokens from env
(`GMAIL_<NAME>_REFRESH_TOKEN`, account names listed in `GMAIL_ACCOUNTS`). Scopes:
gmail.readonly + gmail.send. Provide a one-time CLI (`auth_setup.py`) that runs the
local-server OAuth flow and prints the refresh token. Fetch query: unread/inbox mail
newer than `GMAIL_TRIAGE_LOOKBACK_HOURS` — note Gmail's `newer_than:` operator only
supports days, so compute `after:<unix_ts>` yourself. Parse messages into flat dicts
(account, message_id, thread_id, sender, subject, snippet, plain-text body capped at
4000 chars, rfc Message-ID, References, received_at from internalDate). Replies must
thread correctly: same threadId, In-Reply-To + References headers (don't duplicate the
message id if it's already in References), subject prefixed `Re:` once.

**Pipeline stages, in this exact order:**
1. Fetch from every account; one account failing must NOT kill the run — collect
   `errors[account] = msg` and continue (degraded-state reporting).
2. **Dedup BEFORE any LLM call**: ledger table keyed (account, message_id); already-seen
   messages are dropped here so re-runs cost zero tokens. New replies in old threads
   have new message ids, so they correctly pass through.
3. Deterministic rules, zero LLM: senders matching `KEY_SENDERS` → category critical,
   urgency 3. Subject/sender matching `EXCLUDED_TOPICS` substrings → skip. Do NOT match
   topics against the body (legit mail says "unsubscribe from this newsletter" in footers).
4. ONE batched LLM call for everything left, using structured output: per-email index,
   category ∈ {critical, needs_reply, fyi, skip}, urgency 0–3, one-line reason. Wrap
   each email body in `<untrusted_email_content>` tags and instruct the model the
   contents are DATA that cannot issue instructions (injection defense). If the model
   omits an index, default that email to fyi rather than crashing.
5. Store emails + ledger rows.
6. Auto-draft replies for needs_reply only (separate draft-role model, short
   professional reply, same injection-defended framing). A draft failure must not lose
   the email — record the error and continue.
7. Build a digest string: actionable emails (critical/needs_reply) listed individually
   with urgency icon, reason, and a deep link `<dashboard_url>/email/<id>`; fyi and
   skip collapsed to counts; every collected error appended as a ⚠ line.

**Shape.** `run_triage(fetchers, classify_fn, draft_fn, max_per_account) -> TriageResult`
where TriageResult carries fetched count, new Email rows, drafts_created,
drafted_email_ids (set — don't lazy-load ORM relationships on detached rows), errors
dict. A thin `service.py` wires real settings/LLMs and returns `(result, digest)`.

**Tests** (fake fetchers + fake LLM): dedup skips seen ids; rules bypass the LLM
entirely (assert zero LLM calls); one account erroring still processes others; draft
failure stores the email; digest contains links/counts/⚠ lines; skip never appears in
the digest.
