# Guardrails — prompt-injection detection

Every triaged email is untrusted input. Before the classifier or drafter ever sees an
email, the triage pipeline runs a screening step that scores the content for
prompt-injection attempts and quarantines anything suspicious.

## What it is

`score_injection` in `api/app/tools/gmail/injection.py` runs deterministic heuristics
(no I/O, no LLM) over the subject + body of every new email. Scores map to three bands:

| Band | Score | Action |
|---|---|---|
| `clean` | < 2 | Pass to classifier as normal |
| `borderline` | 2 – 3 | Batched LLM judge decides (see below) |
| `malicious` | ≥ 4 | Quarantine immediately — no LLM call |

Thresholds are defined as `BORDERLINE_THRESHOLD = 2` and `MALICIOUS_THRESHOLD = 4`
in `injection.py`. Conservative by design: a false-positive quarantine is recoverable
(the email is still visible in the dashboard); a false-negative reaches the classifier.

## Detection flow

```
every new email (subject + body)
        │
        ▼
  score_injection()   ← pure heuristics, no LLM
        │
   ┌────┴────────────┐
 clean           borderline / malicious
   │                  │
   │          malicious? → quarantine now
   │                  │
   │          borderline → judge_injections()  ← batched LLM call (classify role)
   │                            │
   │                    is_injection?
   │                     yes │   no │
   │                   quarantine   pass
   │                  ──────────────│
   └──────────────────── classify_fn + draft_fn ──▶ normal triage
```

## Heuristics

Each fired heuristic adds **+2** to the score. Multiple heuristics stack.

| Flag | What triggers it |
|---|---|
| `instruction_override` | "ignore previous instructions", "you are now", `system:` prefix, `<\|im_start\|>` |
| `jailbreak_marker` | "developer mode", "pretend you are", "DAN" |
| `exfiltration` | "forward this email to", "reply with your", "send your API key" |
| `hidden_unicode` | Zero-width chars (U+200B/C/D, U+FEFF) or bidi-override codepoints |
| `base64_blob` | A run of ≥ 120 base64 chars in the body |
| `html_comment_instructions` | HTML comment (`<!-- ... -->`) containing injection keywords |

A single exfiltration phrase scores 2 (borderline) — the LLM judge resolves it.
Two independent signals score ≥ 4 (malicious) and skip the judge.

## What quarantine does

A quarantined email is stored with:
- `category = skip`
- `suspicious = True`
- `reason = "possible prompt injection: <flags>"`
- `urgency = 0`

It is **never** passed to `classify_fn` or `draft_fn`. A `ProcessedMessage` ledger
entry is written so re-runs skip it without reprocessing.

The triage digest gets a block near the top:

```
⚠ N email(s) quarantined as possible prompt injection
   https://dashboard/email/<id>
```

In the dashboard:
- `email.suspicious` field exposed on every email JSON response.
- `⚠ possible injection` destructive badge on the email list row and detail page.
- `suspicious` filter control (All / Suspicious only / Hide suspicious) on the email list.

## Where it runs

The screen step runs in the triage pipeline only. `service.run_triage_now` builds the
`screen_fn` closure and passes it to `run_triage(..., screen_fn=screen_fn)`. The stored
`suspicious` flag then travels to the dashboard and chat without any further gating.

## LLM judge

`judge_injections(emails, llm)` in `injection.py` sends borderline emails in one
batched structured-output call using the `classify` LLM role. The prompt wraps content
in `<untrusted_email_content>` tags and instructs the model that those tags are DATA,
not instructions.

Fail-safe defaults:

- **Missing verdict** (model omitted an index): defaults to `True` → quarantine.
- **Judge call raises** (rate limit, network error): logged, borderline emails are
  treated as clean for that run. Heuristic-malicious emails are still quarantined.

## Gotchas we hit

- **Pure-exfil-only emails score 2 (borderline)** — a single exfiltration phrase isn't
  enough to be malicious. The judge resolves the ambiguity; without the judge that email
  would be treated as clean. Don't disable the judge without adjusting the threshold.
- **Fail-safe default is quarantine, not clean** — if the LLM returns an empty verdicts
  list, every borderline email is quarantined. This is intentional; prefer
  over-quarantine to missed injections.
- **Judge LLM failure degrades gracefully** — borderline emails are treated as clean for
  that run and a `logger.exception` fires. Heuristic-malicious emails are unaffected.
- **Thresholds are tunable in `injection.py`** — adjust `BORDERLINE_THRESHOLD` /
  `MALICIOUS_THRESHOLD` / `BASE64_RUN_LEN` there, not in calling code. After changes,
  re-run the adversarial fixture tests (`api/tests/test_injection.py`).

## Key files

| File | Role |
|---|---|
| `api/app/tools/gmail/injection.py` | `score_injection`, `judge_injections`, thresholds, heuristic patterns |
| `api/app/tools/gmail/pipeline.py` | Screen step (step 3 of `run_triage`), quarantine storage, `format_digest` quarantine block |
| `api/app/tools/gmail/service.py` | `screen_fn` closure wiring heuristics + judge into the pipeline |
| `api/app/store/db.py` | `Email.suspicious` column + `_migrate` entry |
| `api/app/api/routes.py` | `_email_json` serialises `suspicious`; `?suspicious=` filter param |
| `web/lib/api.ts` | `EmailItem.suspicious: boolean`; `EmailFilters.suspicious?: string` |
| `web/components/email-table.tsx` | `⚠ possible injection` badge on list rows |
| `web/components/email-filters.tsx` | Suspicious filter control (All / Suspicious only / Hide suspicious) |
| `web/app/email/[id]/page.tsx` | `⚠ possible injection` badge on detail page |
| `api/tests/test_injection.py` | Heuristic + judge unit tests; adversarial fixture corpus |
| `api/tests/fixtures/injection/` | Six fixture emails (clean, borderline, malicious variants) |
