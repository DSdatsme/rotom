# Coding Agent (GitHub F2)

Paste a GitHub **issue URL** in chat → rotom clones the repo, a containerized Claude Code
**coder** implements the issue on a branch, opens a **draft PR**, runs a bounded CI-fix loop,
then **reviewer** + **security** agents post collated findings as a PR comment. You review and
**merge** — the merge is the only gate. rotom never merges and never pushes the default branch.

> **Status:** code complete + reviewed (2026-06-14); **not yet run end-to-end.** Needs the
> manual setup below before the first live run.

## How it works

- **Entry point** — the `work_on_issue(url)` agent tool validates the URL, refuses any repo
  not in `CODING_AGENT_REPOS`, and fires the Inngest event `workflows/code-issue.requested`.
  The tool performs no git/GitHub writes itself.
- **Orchestration** — a single Inngest workflow `code_issue` (`api/app/workflows/code_issue.py`,
  registered in `workflows/registry.py`). Each stage is a durable `ctx.step.run(...)`.
- **Inngest orchestrates; Docker isolates.** Every Claude run (coder, each fix round, each
  reviewer) executes in an ephemeral `docker run --rm` (`tools/github/sandbox.py`) mounting
  **only** a throwaway worktree (reviewers `:ro`), non-root, with mem/cpu/pids caps and a
  wall-clock timeout. Only the scoped `CLAUDE_CODE_OAUTH_TOKEN` enters the container; the `gh`
  token and host creds stay on the host (git/gh steps run host-side, `tools/github/runner.py`).
- **CI-fix loop** — after the draft PR opens, `gh pr checks --watch`; on red, resume the coder
  with the failure context → push → re-watch, up to `CODING_AGENT_MAX_FIX_ROUNDS` (default 2).
- **Boundary state** — if CI is still red after the loop (or a cap is hit): status `blocked`,
  a "cannot proceed" PR comment + Telegram alert, reviewers skipped, draft PR left open.
- **Reviewers** — once CI is green, fresh read-only Claude sessions review the final diff and
  return JSON findings (`tools/github/review.py`), collated into one PR comment.
- **State & visibility (V1)** — the `CodingRun` table owns lifecycle
  (`running → review → blocked → done`); the Inngest dashboard (:8288) holds step history; the
  Telegram bot reports progress + PR link. Per-Claude `record_run("coder"|"code_review",
  source="inngest")` captures token/latency in the usage dashboard. **No top-level run-log row
  in V1** (it would fight Inngest's replay model — see the spec's Observability section).

## Safety

Allow-listed repos only (`CODING_AGENT_REPOS`, re-checked in the workflow's `authorize` step
as defense-in-depth); **draft PR only; never the default branch; never merge**; per-run caps
(`MAX_TURNS`, `MAX_BUDGET_USD`, container timeout) bound every Claude call; the fix loop is
bounded. Untrusted code runs only inside the container — a malicious test/postinstall hook
can't read the host fs or reach host creds.

## Operator setup (required before first run)

1. **Build the sandbox image:** `docker build -f Dockerfile.coding -t rotom-coding:latest .`
   (verify: `docker run --rm rotom-coding:latest claude --version`).
2. **Env** (`.env`): `CLAUDE_CODE_OAUTH_TOKEN`, `CODING_AGENT_REPOS` (e.g. `DSdatsme/rotom`).
   Optional: `CODING_AGENT_TEST_CMD`, `CODING_AGENT_MAX_FIX_ROUNDS`, the container caps — see
   `.env.example`.
3. **`gh` authenticated on the host** with push access (ADMIN/MAINTAIN/WRITE) to those repos.
4. Docker available to the rotom process.

Without Docker / the token / an allow-listed repo the tool refuses or the workflow fails the
relevant step and reports — it never runs Claude on the host.

## Key files

- `api/app/agent/toolkit.py` — `work_on_issue` tool
- `api/app/workflows/code_issue.py` — the workflow · `workflows/registry.py` — registration
- `api/app/tools/github/issues.py` — URL parse / allow-list / prompt / PR & findings text
- `api/app/tools/github/review.py` — reviewer roster + tolerant findings parser
- `api/app/tools/github/sandbox.py` — docker/claude command builders + container runner
- `api/app/tools/github/runner.py` — host git/gh subprocess wrappers
- `api/app/store/db.py` — `CodingRun` / `CodingStatus`
- `Dockerfile.coding` + `docker/coding-claude-settings.json` — the sandbox image

📄 Spec: [`../superpowers/specs/2026-06-08-coding-agent-design.md`](../superpowers/specs/2026-06-08-coding-agent-design.md) ·
Plan: [`../superpowers/plans/2026-06-14-coding-agent.md`](../superpowers/plans/2026-06-14-coding-agent.md)
