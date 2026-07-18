# Security Policy

## Reporting a vulnerability

Please report security issues **privately** via GitHub's
[**Report a vulnerability**](https://github.com/DSdatsme/rotom/security/advisories/new)
(Security → Advisories). Don't open a public issue for anything security-sensitive.

You can expect an initial response within a few days.

## Security model

rotom is a **single-user** personal assistant. A few properties are intentional
(not bugs):

- **No login UI / RBAC / multi-tenancy.** It's meant to run as one owner's
  private instance. The JSON API is guarded by a single static bearer token
  (`API_TOKEN`), compared in constant time.
- **The agent never sends email on its own.** It classifies, summarizes, and
  drafts; email is only sent when the owner presses **Send** in the dashboard
  (the human-in-the-loop gate).
- **Email content is untrusted input.** It's fenced as untrusted data before it
  reaches any LLM and screened for prompt injection. Any instruction found
  inside an email/issue/document is treated as data, never as a command.
- **All secrets live in `.env`** (gitignored). `.env.example` documents every
  variable with placeholders only. The app refuses to start on a blank/placeholder
  `API_TOKEN`.
- **State lives in `./data`** (a local SQLite file + SOUL/attachments), which is
  gitignored and never committed.

## Hardening notes for self-hosters

- Keep `.env` out of version control and off shared machines.
- Put the API and dashboard behind your own network boundary; they bind to
  `127.0.0.1` in `docker-compose.yml` by default.
- If you enable the optional coding agent, review the sandbox egress setting
  (`CODING_AGENT_SANDBOX_NETWORK`) before granting it network access.
