# rotom docs

One folder per shipped component. Each folder contains:

- **README.md** — how the component works *in this repo*: design decisions, key files,
  gotchas we hit so you don't re-hit them.
- **PROMPT.md** — a self-contained generation prompt. Paste it into an AI coding agent
  (Claude Code, Copilot, etc.) and it should be able to build an equivalent component
  from scratch, including the edge cases we learned the hard way.

Cross-cutting prompts (not tied to one feature) live in [`prompts/`](./prompts/):

| Prompt | Use it to generate |
|---|---|
| [`prompts/design.md`](./prompts/design.md) | The dashboard's visual language (dark, zinc, shadcn) |
| [`prompts/frontend.md`](./prompts/frontend.md) | Next.js / shadcn code in this codebase's style |
| [`prompts/backend.md`](./prompts/backend.md) | Python services matching this codebase's patterns |
| [`prompts/security.md`](./prompts/security.md) | Guardrails for any new agent tool or pipeline |

## Components

| Component | Docs |
|---|---|
| Core architecture (one process: FastAPI + Telegram + scheduler + SQLite) | [`architecture/`](./architecture/) |
| Gmail triage pipeline (fetch → dedup → screen → rules → classify → draft → digest) | [`gmail-triage/`](./gmail-triage/) |
| Telegram chat agent (LangGraph, persistent threads) | [`telegram-agent/`](./telegram-agent/) |
| Dashboard (Next.js, email triage UI, HITL draft send) | [`dashboard/`](./dashboard/) |
| Conversational Draft Composer (chat + preview, attachments, Gmail integration) | [`draft-composer/`](./draft-composer/) |
| Reminders & NL scheduling (countdown tiles, chat bar, cron shorthands) | [`reminders/`](./reminders/) |
| Workflows (Python functions on self-hosted Inngest; cron + event triggers, step retries, dashboard :8288) | [`workflows/`](./workflows/) |
| Guardrails (prompt-injection detection in the triage pipeline; heuristics + LLM judge + quarantine) | [`guardrails/`](./guardrails/) |
| Observability (runs + LLM usage/latency + centralized logs; pluggable sink, `record_run` seam, dashboard Runs/Usage/Logs) | [`observability/`](./observability/) |

## Designed, not yet built

Specs/plans live in [`superpowers/specs/`](./superpowers/specs/) and
[`superpowers/plans/`](./superpowers/plans/). A component folder here is added when the
feature ships (its build plan's final task).

| In design | Where |
|---|---|
| Coding agent (issue → containerized Claude Code → draft PR → CI-fix → review) | [spec](./superpowers/specs/2026-06-08-coding-agent-design.md) · [plan](./superpowers/plans/2026-06-08-coding-agent.md) |
| Unify run sources (one `RunLog` across engines: source/parent facets, auto-nesting, interrupted-run reaper, Inngest tracking) | [spec](./superpowers/specs/2026-06-10-unify-run-sources-design.md) |

When a new feature ships (see `PLAN.md`), add its folder here in the same shape.
