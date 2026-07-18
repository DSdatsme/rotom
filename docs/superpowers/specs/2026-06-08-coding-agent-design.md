# Coding agent (GitHub, Iteration 4 / Feature 2) — design

Date: 2026-06-08 · Status: approved · Part of the GitHub track (see decomposition below)

## The GitHub track (context)

The GitHub work decomposes into independent features. This spec covers **F2 only**.

- **F0 — GitHub foundation:** thin `gh`/`git`/REST helpers. Built as part of F2 (no
  standalone REST client needed for V1 — `gh` CLI + `git` cover it).
- **F1 — Issue creation from chat** (gated write): separate, later.
- **F2 — Coding agent** (this spec): paste an issue link → multi-agent pipeline →
  draft PR you review and merge.
- **F3 — Repo activity watch:** separate, later.

## What F2 V1 does

You paste a GitHub issue URL to the Telegram bot. rotom clones the repo, a **coder**
(Claude Code headless) implements the issue on a branch, opens a **draft PR**, watches
the PR's CI checks and feeds failures back to the coder to fix (bounded), then two
independent **reviewer agents** (general + security) review the final diff and post their
findings as a PR comment. You review and **merge** — the merge is the only gate. rotom
never merges and never pushes to the default branch.

## Decisions (from brainstorming)

| Topic | Decision |
|---|---|
| Coding engine | Claude Code headless via `CLAUDE_CODE_OAUTH_TOKEN` (subscription; separate Agent-SDK credit pool). No `--bare` (it can't use the OAuth token). |
| Entry point | Paste issue URL in chat → `work_on_issue(url)` agent tool fires an Inngest event (`inngest_client.send_sync(inngest.Event(name="workflows/code-issue.requested", data={"url": url}))`, mirroring the existing `run_workflow` tool). Agent performs no git/GitHub writes itself. |
| Orchestration | A single Inngest workflow defined with `@inngest_client.create_function` and registered in `workflows/registry.py` (`WORKFLOW_FUNCTIONS`); each stage a retriable `ctx.step.run(...)`; run history in the Inngest dashboard (dev mode, :8288). |
| Agents | Coder (full context, resumable, Read/Edit/Bash) + reviewer + security (each a *fresh* `claude` session, read-only, diff-scoped). Roster is config-driven. |
| CI loop | After the PR opens, poll `gh pr checks`; on red, resume the coder with the failure logs → fix → push → re-watch, up to `CODING_AGENT_MAX_FIX_ROUNDS` (default 2). |
| Findings | Reviewers run after CI settles; findings collated into one PR comment via `gh pr comment`. Comment-only — you decide; merge is the gate. |
| Boundary reached | Caps hit (fix rounds, turns, budget, timeout) → terminal state: Telegram alert **and** a PR comment that rotom cannot proceed and needs a human. |
| Visibility | Telegram (progress + PR link + final status); Inngest dashboard for steps; `CodingRun` table for coding lifecycle. Per-Claude-call `record_run` for token/latency only — **no** top-level run-log row in V1 (see Observability). No custom rotom dashboard section in V1. |
| Resumability | Persistent per-issue worktree + a `CodingRun` row storing `claude_session_id` — required in V1 for the CI-fix loop, and reused by V2 re-work + the future dashboard. |
| **Isolation** | **Every Claude run (coder + reviewers) executes inside an ephemeral Docker container**, never as a bare host subprocess. Inngest orchestrates; Docker isolates (the two compose — Inngest gives durability, not a security boundary). Native Claude Code sandbox enabled *inside* the container as defense-in-depth. |
| Safety | Allow-listed repos only; draft PR only; never default branch; never merge; per-run caps; worktree cleanup on merge/close. |

## Pipeline (Inngest workflow `code_issue`)

The workflow function (`fn_id="code-issue"`) triggers on `inngest.TriggerEvent(event="workflows/code-issue.requested")` and is added to `WORKFLOW_FUNCTIONS` in `workflows/registry.py` so `inngest.fast_api.serve()` picks it up — same wiring as `morning_digest`. Each stage below is a `ctx.step.run(...)` (durable + retriable). Host-side `gh`/`git` calls and the `docker run` invocations live in helper modules (`runner.py`, `sandbox.py`) and are awaited from inside steps; the engine itself stays the thin async orchestrator that `morning_digest` already demonstrates.

```
parse+authorize → fetch issue → prepare worktree → CODER → commit + push → open draft PR
        │
        ▼  CI-fix loop  (≤ CODING_AGENT_MAX_FIX_ROUNDS, default 2)
   watch PR checks (gh pr checks --watch, bounded by CODING_AGENT_TIMEOUT)
        ├─ green → exit loop
        └─ red  → resume CODER with failing-check logs → commit → push → re-watch
        │
        ▼  (code stable — review what will actually merge)
   reviewer ─┐  parallel · fresh sessions · read-only · over the final diff
   security ─┤→ synthesize → gh pr comment (collated, severity-tagged findings)
        │
        ▼
   report to Telegram (PR link + final CI status)
```

**Host vs. container split (see Isolation below):** the workflow runs in rotom's process
on the host. Git/GitHub stages (clone, branch, commit, push, `gh` issue/PR/checks/comment)
run **on the host** so the `gh` token never leaves it. The Claude-execution stages (coder,
fix rounds, reviewers) run **inside an ephemeral `docker run --rm` container** — the
container creation IS those steps, not a separate step.

Stages:
1. **parse+authorize** — extract `owner/repo/number` from the URL; **reject if
   `owner/repo` not in `CODING_AGENT_REPOS`** (refuse by construction; never starts a run).
   Also verify **push access** to the repo (`gh repo view --json viewerPermission` →
   ADMIN/MAINTAIN/WRITE); if you lack write, abort immediately with "no push access to
   <repo>; fork-based contribution is not supported in V1" (works for your own + org +
   external-org repos where you're a write collaborator; pure no-write forks are V2).
2. **fetch issue** — `gh issue view <url> --json title,body,comments`; build the task prompt.
3. **prepare worktree** — `gh repo clone owner/repo` into
   `$CODING_AGENT_WORKTREE_DIR/<org>/<repo>/<issue>/` (e.g. `data/coding/DSdatsme/rotom/12/`;
   gh token handles private-repo auth); branch `rotom/issue-<n>-<slug>` off the default
   branch; write the `CodingRun` row (status=running).
4. **coder** — via `run_claude_in_container` (container, worktree mounted rw): `claude -p
   "<task prompt>" --output-format json --allowedTools "Read,Edit,Bash" --permission-mode
   acceptEdits --max-turns $MAX_TURNS --max-budget-usd $MAX_BUDGET`,
   `CLAUDE_CODE_OAUTH_TOKEN` in the container env, `docker run` wall-clock timeout
   `$TIMEOUT`. Capture `session_id` → `CodingRun.claude_session_id`. If
   `CODING_AGENT_TEST_CMD` is set, the prompt instructs the coder to make it pass; the
   coder is also told to keep changes scoped to the issue.
5. **commit + push** — ensure changes committed (coder usually auto-commits; otherwise
   commit with a generated message), push the branch.
6. **open draft PR** — `gh pr create --draft --base <default> --head <branch>` with a body
   that links the issue and marks it rotom-generated. Store `pr_url`.
7. **CI-fix loop** — host `gh pr checks <pr> --watch` (bounded by `$TIMEOUT`). Green → exit.
   Red → `run_claude_in_container(..., resume=<session_id>)` with the failing-check logs as
   the prompt (same worktree + session dir mounted), then host commit + push + re-watch.
   Repeat ≤ `CODING_AGENT_MAX_FIX_ROUNDS`.
8. **reviewers** (parallel) — for each entry in the reviewer roster,
   `run_claude_in_container(..., read_only=True)` (worktree mounted `:ro`, fresh session,
   NO `--resume`): `claude -p "<lens prompt + the diff>" --output-format json --allowedTools
   "Read,Bash(git diff*)"` (NO Edit — independent fresh eyes). Returns severity-tagged findings.
9. **synthesize + comment** — collate findings into one markdown comment; `gh pr comment <pr>`.
10. **report** — Telegram: PR link + final CI status.

**Boundary terminal state:** if the fix loop hits `MAX_FIX_ROUNDS` with CI still red, or
any cap (turns/budget/timeout) is exhausted: **skip the reviewer stage** (blocked code
isn't mergeable, no point reviewing it), set `CodingRun.status=blocked`, post a PR comment
"⚠ rotom stopped — <reason> (e.g. CI still failing after 2 fix rounds). Manual
intervention needed." and send the same alert to Telegram. The draft PR stays open for a
human to take over. (The reviewer + findings-comment stage runs only when CI settles green.)

## Observability (run tracking)

rotom has a run-tracking seam (`app.observability.sink.record_run`, backed by `RunLog` in `app/store/observability.py`), used by the scheduler (`gmail_triage`, `reminder_fire`) and the dashboard's `draft_generation`. **It does not fit an Inngest workflow's top level, and V1 deliberately does not wrap the workflow in it.**

**Why not wrap the workflow body.** `record_run` is a **sync** contextmanager built for a continuous in-process span (it sets a `current_run_id` ContextVar and starts a 60s heartbeat *thread*). An Inngest workflow is durable via **replay** — the engine re-invokes the function from the top on each step boundary, short-circuiting completed `ctx.step.run(...)` calls with memoized results. A `with record_run(...)` around the body would therefore re-enter on every replay (a new `RunLog` row + start per step), spawn a fresh heartbeat thread per HTTP callback that can't span the suspended gaps, and lean on a ContextVar that doesn't survive suspension. The shipped `morning_digest` workflow uses no `record_run` for exactly this reason.

**V1 — track at two honest layers:**

- **Top level → `CodingRun` table + Inngest dashboard.** `CodingRun` already is the coding lifecycle store (`status: running→review→blocked→done→failed`, `pr_url`, `claude_session_id`, timestamps); the Inngest dashboard (:8288) holds step-level history. No top-level `record_run`/`RunLog` row in V1 — it would be a redundant row fighting the replay model.
- **Wrap only the synchronous Claude calls.** Each `run_claude_in_container(...)` (coder, each fix round, each reviewer) is a genuine single-shot blocking span inside its step — wrap *those* in `record_run("coder" | "code_review", source="inngest")`. That is where the seam earns its keep: per-Claude-call **latency + token usage** flow into the existing usage dashboard. In V1 these are standalone runs (the ContextVar can't nest them under a parent across step boundaries — acceptable).

**Deferred to V2 (see "Out of scope" + the roadmap's "first-class Inngest run tracking"):** a single unified top-level `RunLog` row for the whole `code_issue` run. When built, do it via the **sink primitives at step granularity**, not the contextmanager — `start_run(RunStart) -> id` in `ctx.step.run("obs-start", …)` and `finish_run(id, status, …)` in `ctx.step.run("obs-finish", …)`, keyed on the Inngest run id (`external_id`) so it's idempotent across replays. (Nesting the per-Claude runs under it would also require adding an explicit `parent_run_id=` argument to `record_run`/`start_run`, which the seam lacks today.)

## Isolation / sandboxing (V1)

Claude runs on untrusted code, so every Claude invocation is contained. **Inngest does
not provide isolation** (it orchestrates host code); **Docker provides the boundary**, and
the two compose — an Inngest execution step launches `docker run --rm`.

- **Ephemeral container per Claude run** (coder, each fix round, each reviewer):
  `docker run --rm` against a prebuilt sandbox image; created and destroyed within the step.
- **Only the worktree is mounted** (`-v <worktree>:/work`, `cwd=/work`); the rest of the
  host filesystem is invisible. Reviewers mount it **read-only** (`:ro`).
- **A per-run session dir is mounted** (e.g. `-v <run>/claude-home:/home/agent/.claude`)
  so `--resume` works across the coder's containers (initial + fix rounds).
- **Tokens:** only the scoped `CLAUDE_CODE_OAUTH_TOKEN` is passed into the container. The
  `gh` token and all host creds stay on the host (git/gh steps are host-side). Env is
  scrubbed (`CLAUDE_CODE_SUBPROCESS_ENV_SCRUB`).
- **Defense-in-depth inside:** the container also enables Claude Code's native sandbox
  (`sandbox.enabled`, `failIfUnavailable: true`, `allowUnsandboxedCommands: false`,
  deny-read `~/`) via a baked-in `.claude/settings.json`.
- **Hardening:** non-root user, `--memory` / `--cpus` caps, `--pids-limit`, and a
  wall-clock timeout (`CODING_AGENT_TIMEOUT`) on the `docker run`. Network is allowed
  (deps, the Anthropic API); egress filtering is V2.
- **Image:** `Dockerfile.coding` — Claude Code CLI + git + common runtimes (node, python,
  build tools) so most repos' tests run; anything more, the coder installs inside (network).
- Blast radius = one container + one disposable worktree. A malicious postinstall hook or
  test command cannot read the host fs, reach host creds, or persist.
- **No host pollution (stated guarantee).** Everything the coder installs — npm/pip/uv
  packages, apt, build artifacts, language caches — lands in the container's own
  filesystem and is destroyed on `--rm`. The host's only durable footprint is the one
  prebuilt sandbox image and disposable worktrees under `CODING_AGENT_WORKTREE_DIR`. The
  coder's toolchain never enters the host environment. (If a repo installs into its own
  tree — `node_modules/`, `.venv/` — those stay confined to the mounted throwaway worktree,
  are git-ignored so they never reach a commit/PR, and are removed on worktree cleanup.)

Requires Docker available to the rotom host/process. If `docker` is missing or the run
fails to start, the workflow fails that step and reports — it never silently falls back to
running Claude on the host.

## Components / files

| File | Role |
|---|---|
| `api/app/tools/github/__init__.py` | package |
| `api/app/tools/github/issues.py` | pure helpers: `parse_issue_url`, `is_allowed_repo`, `build_task_prompt`, `build_pr_body`, `build_findings_comment` |
| `api/app/tools/github/review.py` | reviewer roster (`REVIEWERS = [{name, prompt, model?}]`), `build_review_prompt(lens, diff)`, findings schema + parse |
| `api/app/tools/github/runner.py` | **host** subprocess wrappers: `clone`, `branch`, `commit`, `push`, `gh_issue_view`, `gh_pr_create`, `gh_pr_checks`, `gh_pr_comment` |
| `api/app/tools/github/sandbox.py` | `run_claude_in_container(prompt, worktree, session_dir, resume=None, read_only=False, caps)` — builds + runs `docker run --rm`, returns parsed JSON incl. `session_id`; the only place Claude executes |
| `Dockerfile.coding` | the sandbox image (Claude Code CLI + git + node/python/build tools + baked `.claude/settings.json` enabling the native sandbox) |
| `api/app/workflows/code_issue.py` | the Inngest workflow (stages above), `@inngest_client.create_function` |
| `api/app/workflows/registry.py` | add `code_issue` to `WORKFLOW_FUNCTIONS` (existing file — one-line edit) |
| `api/app/agent/toolkit.py` | `work_on_issue(url)` `@tool` (validates/allow-checks URL, `inngest_client.send_sync` the event), appended to `ALL_TOOLS` |
| `api/app/store/db.py` | `CodingRun` model (new table created by `Base.metadata.create_all`; the existing migrations-lite `_migrate` only needs touching for *later* column additions, per the established PRAGMA-`table_info` pattern) |
| `api/app/config.py` | the config keys below |

**Config:** `CLAUDE_CODE_OAUTH_TOKEN`, `CODING_AGENT_REPOS` (comma list),
`CODING_AGENT_MAX_TURNS` (30), `CODING_AGENT_MAX_BUDGET_USD` (5), `CODING_AGENT_TIMEOUT`
(1200s), `CODING_AGENT_MAX_FIX_ROUNDS` (2), `CODING_AGENT_TEST_CMD` (optional),
`CODING_AGENT_WORKTREE_DIR` (default `data/coding`),
`CODING_AGENT_SANDBOX_IMAGE` (default `rotom-coding:latest`),
`CODING_AGENT_CONTAINER_MEM` (e.g. `4g`), `CODING_AGENT_CONTAINER_CPUS` (e.g. `2`).

**`CodingRun` table:** `id, issue_url, repo, issue_number, branch, pr_url,
claude_session_id, worktree_path, status (running|review|blocked|done|failed),
created_at, updated_at`.

## Security / policy

- **Bounded exception to "agent performs no external writes."** The agent tool only fires
  an internal event. The *workflow* may clone, branch, push, open draft PRs, and comment —
  but ONLY on `CODING_AGENT_REPOS`, ONLY draft PRs, NEVER the default branch, NEVER merge.
  This is stated explicitly so it can't be mistaken for a general loosening.
- **All Claude execution is containerized** (see Isolation) — untrusted code never runs as
  a host subprocess. Inngest orchestrates but does not isolate; Docker is the boundary.
- Reviewers are **read-only** (`--allowedTools` without Edit/Write, worktree mounted `:ro`)
  and run in fresh sessions/containers — they can read the repo to verify but cannot change
  it or inherit the coder's reasoning.
- Per-run caps (`--max-turns`, `--max-budget-usd`, subprocess timeout) bound every Claude
  invocation; `MAX_FIX_ROUNDS` bounds the loop. Worktrees are cleaned on PR merge/close (a
  later retention job; V1 cleans on terminal success/failure where practical).
- The token (`CLAUDE_CODE_OAUTH_TOKEN`) and `gh` auth live in env / the host keyring,
  never in code or logs.

## Out of scope (V2+)

- Self-repair from *reviewer* findings (V1 only auto-fixes from CI; reviewer findings are
  comment-only).
- Unified top-level `RunLog` row for the whole `code_issue` run (V1 uses `CodingRun` +
  Inngest dashboard; per-Claude `record_run` only). V2 adds it via `start_run`/`finish_run`
  in dedicated idempotent steps keyed on the Inngest run id — see Observability + the
  roadmap's "first-class Inngest run tracking".
- Mid-run human intervention (pause / fix / approve / reject in a UI) — needs the
  pause/resume primitive (Inngest `waitForEvent`).
- Fork-based PRs for repos where you lack push access (V1 requires write; aborts
  otherwise). V2 adds `gh repo fork` → push to fork → cross-repo PR (`--head you:branch`).
- GitHub webhook → event (replaces CI polling) once rotom is publicly reachable.
- Network egress filtering for the sandbox container (V1 allows network for deps + API;
  a TLS-terminating proxy / domain allowlist is V2).
- Rich rotom dashboard "Coding runs" section (the `CodingRun` table is its future backing
  store).
- Injection-scanning issue bodies (allow-listed repos are the V1 mitigation).
- F0 standalone REST client, F1 issue creation, F3 repo watch.

## Testing

- Unit-test the pure helpers with fakes (no network, no LLM, no `gh`, no Docker):
  `parse_issue_url` (valid/invalid/enterprise URLs), `is_allowed_repo` (allow/deny),
  `build_task_prompt`, `build_pr_body`, `build_findings_comment`, the reviewer findings
  parse (incl. malformed → safe default), and the claude-JSON parse (extracts
  `session_id`, handles non-zero exit).
- Unit-test the `docker run` **command builder** in `sandbox.py` (correct mounts incl.
  worktree, `:ro` for reviewers, session dir, token env, caps, `--rm`) without invoking
  Docker.
- The `runner.py` host wrappers, the container execution, and the full workflow are
  verified by a **real manual run on `DSdatsme/rotom`** against a throwaway test issue —
  not unit-mocked end to end. No live Claude/LLM call or Docker run in CI.
- CI (pytest + next build) stays green; the workflow imports cleanly without a running
  Inngest server or `CLAUDE_CODE_OAUTH_TOKEN`.

## Done when

Pasting a real issue link for an allow-listed repo produces: a branch, a draft PR, a
bounded CI-fix loop that reacts to red checks, a collated reviewer+security findings
comment on the PR, and a Telegram report with the PR link — and a non-allow-listed link
is refused immediately. Boundary exhaustion leaves the draft PR open with a "cannot
proceed" comment + Telegram alert. Ordinary triage/reminders/workflows are unaffected.
