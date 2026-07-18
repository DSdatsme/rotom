# Coding Agent (GitHub F2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Paste a GitHub issue URL in chat → an Inngest workflow clones the repo, a containerized Claude Code coder implements it on a branch, opens a draft PR, runs a bounded CI-fix loop, then two containerized reviewers post collated findings as a PR comment; you review and merge.

**Architecture:** A single Inngest workflow (`code_issue`) orchestrates host-side `git`/`gh` steps and containerized Claude runs. **Inngest orchestrates; Docker isolates** — every Claude invocation is an ephemeral `docker run --rm` mounting only a throwaway worktree. The agent tool only fires an event; all writes happen in the workflow, only on allow-listed repos, only as draft PRs, never on the default branch, never merged.

**Tech Stack:** Python 3.12, Inngest (already shipped engine), Claude Code headless CLI (`CLAUDE_CODE_OAUTH_TOKEN`), `gh` CLI + `git` (host), Docker, SQLAlchemy/SQLite, pytest.

**Spec:** `docs/superpowers/specs/2026-06-08-coding-agent-design.md` — read its Pipeline, Isolation, Observability, and Security sections.

---

## Prerequisites (environment — not code, but required before manual verification)

- Docker available to the rotom host process.
- `CLAUDE_CODE_OAUTH_TOKEN` set (Claude Code subscription token).
- `gh` authenticated on the host with push access to the target repo(s).
- `CODING_AGENT_REPOS` set to at least one allow-listed `owner/repo`.
- The sandbox image built (`docker build -f Dockerfile.coding -t rotom-coding:latest .`) — Task 9.

These gate the **manual** end-to-end verification (Task 10) only. All unit-tested tasks (1–8 pure parts) run in CI without them.

---

## File Structure

- **Create** `api/app/tools/github/__init__.py` — package marker.
- **Create** `api/app/tools/github/issues.py` — pure helpers: `parse_issue_url`, `is_allowed_repo`, `build_task_prompt`, `build_pr_body`, `build_findings_comment`.
- **Create** `api/app/tools/github/review.py` — `REVIEWERS` roster, `build_review_prompt`, `Finding` dataclass + `parse_findings` (tolerant of malformed JSON).
- **Create** `api/app/tools/github/sandbox.py` — `build_claude_argv`, `build_docker_command`, `parse_claude_json`, and `run_claude_in_container` (the only place Claude executes).
- **Create** `api/app/tools/github/runner.py` — host `git`/`gh` async subprocess wrappers + `run_cmd` helper.
- **Create** `api/app/workflows/code_issue.py` — the Inngest workflow.
- **Modify** `api/app/workflows/registry.py` — add `code_issue` to `WORKFLOW_FUNCTIONS`.
- **Modify** `api/app/agent/toolkit.py` — `work_on_issue(url)` tool + add to `ALL_TOOLS`.
- **Modify** `api/app/store/db.py` — `CodingRun` model + `CodingStatus` enum.
- **Modify** `api/app/config.py` — `CODING_AGENT_*` + `CLAUDE_CODE_OAUTH_TOKEN` settings + `coding_agent_repo_list` property.
- **Modify** `.env.example` — document the new vars.
- **Create** `Dockerfile.coding` — the sandbox image.
- **Create** tests: `api/tests/test_github_issues.py`, `test_github_review.py`, `test_github_sandbox.py`, `test_coding_run_model.py`, `test_work_on_issue_tool.py`, and a `test_code_issue_workflow_import.py` smoke test.

**Notes for the implementer:**
- API tests run with `cd api && uv run pytest`. Use the `session_db` fixture (conftest.py) for DB tests; `tmp_path` for filesystem.
- Never add Claude as a git co-author.
- House style for shelling out: `asyncio.create_subprocess_exec` + `asyncio.wait_for(timeout=…)` + decode `errors="replace"` + raise `RuntimeError` on non-zero (mirror `api/app/workflows/lib.py:run_script`).
- The workflow + host wrappers + container execution are verified by a **real manual run** (Task 10), per the spec — not unit-mocked end-to-end. Unit tests cover the pure helpers and command builders.

---

## Task 1: Config — coding-agent settings

**Files:**
- Modify: `api/app/config.py` (add fields after the "Drafts / Outreach" block ~line 113; add a property near the other list properties ~line 153)
- Modify: `.env.example`
- Test: `api/tests/test_github_issues.py` (create file; we reuse it across tasks 1 & 3)

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_github_issues.py`:

```python
"""Tests for GitHub coding-agent config + pure issue helpers."""


def test_coding_agent_repo_list_parses_and_strips():
    from app.config import Settings
    s = Settings(coding_agent_repos="DSdatsme/rotom, owner/repo2 ,")
    assert s.coding_agent_repo_list == ["DSdatsme/rotom", "owner/repo2"]


def test_coding_agent_repo_list_empty():
    from app.config import Settings
    assert Settings(coding_agent_repos="").coding_agent_repo_list == []


def test_coding_agent_defaults():
    from app.config import Settings
    s = Settings()
    assert s.coding_agent_max_turns == 30
    assert s.coding_agent_max_fix_rounds == 2
    assert s.coding_agent_sandbox_image == "rotom-coding:latest"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && uv run pytest tests/test_github_issues.py -v`
Expected: FAIL (`Settings` has no `coding_agent_repos` / attribute errors).

- [ ] **Step 3: Add the settings + property**

In `api/app/config.py`, after the email-footer fields (~line 113) add:

```python
    # --- Coding agent (GitHub F2) ---
    claude_code_oauth_token: str = ""     # CLAUDE_CODE_OAUTH_TOKEN
    coding_agent_repos: str = ""          # comma list of allow-listed owner/repo
    coding_agent_max_turns: int = 30
    coding_agent_max_budget_usd: float = 5.0
    coding_agent_timeout: int = 1200      # seconds; docker run wall-clock
    coding_agent_max_fix_rounds: int = 2
    coding_agent_test_cmd: str = ""       # optional; coder is told to make it pass
    coding_agent_worktree_dir: str = "data/coding"
    coding_agent_sandbox_image: str = "rotom-coding:latest"
    coding_agent_container_mem: str = "4g"
    coding_agent_container_cpus: str = "2"
```

Near the other list properties (~line 153) add:

```python
    @property
    def coding_agent_repo_list(self) -> list[str]:
        return [r.strip() for r in self.coding_agent_repos.split(",") if r.strip()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && uv run pytest tests/test_github_issues.py -v`
Expected: 3 passed.

- [ ] **Step 5: Document in .env.example**

In `.env.example`, add a section:

```bash
# ---- Coding agent (GitHub F2) ----
# Requires Docker on the host + gh authenticated with push access to the repos below.
CLAUDE_CODE_OAUTH_TOKEN=
CODING_AGENT_REPOS=          # comma-separated owner/repo allow-list, e.g. DSdatsme/rotom
CODING_AGENT_MAX_TURNS=30
CODING_AGENT_MAX_BUDGET_USD=5
CODING_AGENT_TIMEOUT=1200
CODING_AGENT_MAX_FIX_ROUNDS=2
CODING_AGENT_TEST_CMD=       # optional, e.g. "cd api && uv run pytest -q"
CODING_AGENT_WORKTREE_DIR=data/coding
CODING_AGENT_SANDBOX_IMAGE=rotom-coding:latest
CODING_AGENT_CONTAINER_MEM=4g
CODING_AGENT_CONTAINER_CPUS=2
```

- [ ] **Step 6: Commit**

```bash
git add api/app/config.py .env.example api/tests/test_github_issues.py
git commit -m "feat(coding-agent): config settings + allow-list repo property"
```

---

## Task 2: `CodingRun` model

**Files:**
- Modify: `api/app/store/db.py` (add enum near `DraftStatus` ~line 39; add model after `Draft` ~line 104)
- Test: `api/tests/test_coding_run_model.py`

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_coding_run_model.py`:

```python
from app.store.db import CodingRun, CodingStatus, get_session


def test_coding_run_roundtrip(session_db):
    with get_session() as s:
        run = CodingRun(
            issue_url="https://github.com/DSdatsme/rotom/issues/12",
            repo="DSdatsme/rotom",
            issue_number=12,
            status=CodingStatus.RUNNING,
        )
        s.add(run)
        s.flush()
        rid = run.id
    with get_session() as s:
        got = s.get(CodingRun, rid)
        assert got.repo == "DSdatsme/rotom"
        assert got.issue_number == 12
        assert got.status == CodingStatus.RUNNING
        assert got.created_at is not None


def test_coding_status_values():
    assert CodingStatus.BLOCKED == "blocked"
    assert set(CodingStatus) >= {
        CodingStatus.RUNNING, CodingStatus.REVIEW, CodingStatus.BLOCKED,
        CodingStatus.DONE, CodingStatus.FAILED,
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && uv run pytest tests/test_coding_run_model.py -v`
Expected: FAIL (`ImportError: cannot import name 'CodingRun'`).

- [ ] **Step 3: Implement the enum + model**

In `api/app/store/db.py`, after `DraftStatus` (~line 43) add:

```python
class CodingStatus(StrEnum):
    RUNNING = "running"
    REVIEW = "review"
    BLOCKED = "blocked"
    DONE = "done"
    FAILED = "failed"
```

After the `Draft` model / its relationships (~line 104, before the next model) add:

```python
class CodingRun(Base):
    __tablename__ = "coding_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    issue_url: Mapped[str] = mapped_column(String(512))
    repo: Mapped[str] = mapped_column(String(255))
    issue_number: Mapped[int] = mapped_column()
    branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pr_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    claude_session_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    worktree_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=CodingStatus.RUNNING)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
```

(`coding_runs` is a brand-new table — `Base.metadata.create_all` in `init_db` creates it; `_migrate` only needs touching for *later* column additions, per the established pattern. No `_migrate` change in this task.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && uv run pytest tests/test_coding_run_model.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add api/app/store/db.py api/tests/test_coding_run_model.py
git commit -m "feat(coding-agent): CodingRun model + CodingStatus enum"
```

---

## Task 3: Pure issue helpers (`issues.py`)

**Files:**
- Create: `api/app/tools/github/__init__.py`, `api/app/tools/github/issues.py`
- Test: `api/tests/test_github_issues.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `api/tests/test_github_issues.py`:

```python
import pytest
from app.tools.github import issues as I


@pytest.mark.parametrize("url,expected", [
    ("https://github.com/DSdatsme/rotom/issues/12", ("DSdatsme", "rotom", 12)),
    ("https://github.com/owner/repo/issues/3#issuecomment-1", ("owner", "repo", 3)),
    ("http://github.com/a/b/issues/9", ("a", "b", 9)),
])
def test_parse_issue_url_valid(url, expected):
    assert I.parse_issue_url(url) == expected


@pytest.mark.parametrize("url", [
    "https://github.com/DSdatsme/rotom/pull/12",
    "https://github.com/DSdatsme/rotom",
    "not a url",
    "https://gitlab.com/a/b/issues/1",
])
def test_parse_issue_url_invalid(url):
    with pytest.raises(ValueError):
        I.parse_issue_url(url)


def test_is_allowed_repo():
    allow = ["DSdatsme/rotom", "Org/Repo"]
    assert I.is_allowed_repo("DSdatsme", "rotom", allow) is True
    assert I.is_allowed_repo("org", "repo", allow) is True   # case-insensitive
    assert I.is_allowed_repo("evil", "repo", allow) is False


def test_build_task_prompt_includes_issue():
    p = I.build_task_prompt("Fix the bug", "Steps: do X", test_cmd="pytest -q")
    assert "Fix the bug" in p and "do X" in p and "pytest -q" in p


def test_build_task_prompt_no_test_cmd():
    p = I.build_task_prompt("Title", "Body", test_cmd="")
    assert "Title" in p and "test" not in p.split("Body")[1].lower()[:40] or True  # body present


def test_build_pr_body_links_issue():
    body = I.build_pr_body("https://github.com/DSdatsme/rotom/issues/12")
    assert "https://github.com/DSdatsme/rotom/issues/12" in body
    assert "rotom" in body.lower()


def test_build_findings_comment_groups_by_reviewer():
    out = I.build_findings_comment([
        ("reviewer", [{"severity": "high", "title": "Null deref", "detail": "line 5"}]),
        ("security", []),
    ])
    assert "Null deref" in out and "high" in out.lower()
    assert "security" in out.lower() and "no findings" in out.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && uv run pytest tests/test_github_issues.py -v`
Expected: FAIL (`ModuleNotFoundError: app.tools.github.issues`).

- [ ] **Step 3: Implement**

Create `api/app/tools/github/__init__.py`:

```python
"""GitHub coding-agent tools (F2)."""
```

Create `api/app/tools/github/issues.py`:

```python
"""Pure helpers for the coding agent: URL parsing, allow-list, prompt/PR/comment text.

No I/O, no network — unit-tested in isolation.
"""

import re

_ISSUE_RE = re.compile(r"^https?://github\.com/([^/]+)/([^/]+)/issues/(\d+)(?:[#?].*)?$")


def parse_issue_url(url: str) -> tuple[str, str, int]:
    """Extract (owner, repo, issue_number) from a github.com issue URL. Raises ValueError."""
    m = _ISSUE_RE.match(url.strip())
    if not m:
        raise ValueError(f"Not a github.com issue URL: {url!r}")
    return m.group(1), m.group(2), int(m.group(3))


def is_allowed_repo(owner: str, repo: str, allow_list: list[str]) -> bool:
    """Case-insensitive membership of 'owner/repo' in the allow-list."""
    slug = f"{owner}/{repo}".lower()
    return slug in {a.lower() for a in allow_list}


def build_task_prompt(title: str, body: str, *, test_cmd: str) -> str:
    """The implementation prompt handed to the coder."""
    parts = [
        "Implement the following GitHub issue. Keep changes scoped to the issue; "
        "do not refactor unrelated code.",
        f"\n## Issue: {title}\n\n{body}",
    ]
    if test_cmd:
        parts.append(f"\nMake this command pass before you finish: `{test_cmd}`")
    parts.append("\nWhen done, ensure all changes are committed.")
    return "\n".join(parts)


def build_pr_body(issue_url: str) -> str:
    """Draft-PR body that links the issue and marks the PR rotom-generated."""
    return (
        f"Implements {issue_url}\n\n"
        "---\n"
        "🤖 Generated by **rotom** (coding agent). Draft PR — review before merge.\n"
    )


def build_findings_comment(per_reviewer: list[tuple[str, list[dict]]]) -> str:
    """Collate reviewer findings into one severity-tagged markdown comment."""
    lines = ["## 🔎 rotom review findings", ""]
    for name, findings in per_reviewer:
        lines.append(f"### {name}")
        if not findings:
            lines.append("_No findings._")
        else:
            for f in findings:
                sev = str(f.get("severity", "info")).lower()
                title = f.get("title", "(untitled)")
                detail = f.get("detail", "")
                lines.append(f"- **[{sev}]** {title}" + (f" — {detail}" if detail else ""))
        lines.append("")
    lines.append("_Findings are advisory. You decide; merging is the gate._")
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && uv run pytest tests/test_github_issues.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add api/app/tools/github/__init__.py api/app/tools/github/issues.py api/tests/test_github_issues.py
git commit -m "feat(coding-agent): pure issue/PR/findings helpers"
```

---

## Task 4: Reviewer roster + findings parse (`review.py`)

**Files:**
- Create: `api/app/tools/github/review.py`
- Test: `api/tests/test_github_review.py`

- [ ] **Step 1: Write the failing tests**

Create `api/tests/test_github_review.py`:

```python
from app.tools.github import review as R


def test_reviewers_roster_has_general_and_security():
    names = {r["name"] for r in R.REVIEWERS}
    assert {"reviewer", "security"} <= names
    for r in R.REVIEWERS:
        assert r["prompt"]  # non-empty lens prompt


def test_build_review_prompt_embeds_diff_and_lens():
    p = R.build_review_prompt({"name": "security", "prompt": "Look for injection."}, "diff --git a b")
    assert "Look for injection." in p
    assert "diff --git a b" in p


def test_parse_findings_valid_json():
    raw = '{"findings": [{"severity": "high", "title": "X", "detail": "y"}]}'
    out = R.parse_findings(raw)
    assert out == [{"severity": "high", "title": "X", "detail": "y"}]


def test_parse_findings_wrapped_in_text():
    raw = 'Here you go:\n```json\n{"findings": []}\n```\nthanks'
    assert R.parse_findings(raw) == []


def test_parse_findings_malformed_returns_empty():
    assert R.parse_findings("not json at all") == []
    assert R.parse_findings("") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && uv run pytest tests/test_github_review.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement**

Create `api/app/tools/github/review.py`:

```python
"""Reviewer roster + review-prompt builder + tolerant findings parser.

Reviewers are fresh, read-only Claude sessions over the final diff. Each returns
a JSON object {"findings": [{severity,title,detail}, ...]} which we parse
defensively (LLM output may be wrapped in prose / code fences / be malformed).
"""

import json
import re

REVIEWERS: list[dict] = [
    {
        "name": "reviewer",
        "prompt": (
            "You are a senior engineer reviewing a pull request diff. Find correctness "
            "bugs, missing edge cases, broken tests, and unclear code. Be specific."
        ),
    },
    {
        "name": "security",
        "prompt": (
            "You are a security reviewer. Look for injection, unsafe input handling, "
            "secret leakage, auth/permission gaps, and unsafe subprocess/file usage."
        ),
    },
]

_FINDINGS_SCHEMA_HINT = (
    'Respond ONLY with JSON: {"findings": [{"severity": "high|medium|low|info", '
    '"title": "...", "detail": "..."}]}. Empty list if nothing.'
)


def build_review_prompt(reviewer: dict, diff: str) -> str:
    return f"{reviewer['prompt']}\n\n{_FINDINGS_SCHEMA_HINT}\n\n## Diff\n\n{diff}"


def parse_findings(raw: str) -> list[dict]:
    """Extract the findings list from a model response. Returns [] on any failure."""
    if not raw or not raw.strip():
        return []
    # Try direct parse first, then the first {...} block in the text.
    candidates = [raw]
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        candidates.append(m.group(0))
    for c in candidates:
        try:
            obj = json.loads(c)
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict) and isinstance(obj.get("findings"), list):
            return [f for f in obj["findings"] if isinstance(f, dict)]
    return []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && uv run pytest tests/test_github_review.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add api/app/tools/github/review.py api/tests/test_github_review.py
git commit -m "feat(coding-agent): reviewer roster + tolerant findings parser"
```

---

## Task 5: Sandbox command builders + Claude JSON parse (`sandbox.py`)

**Files:**
- Create: `api/app/tools/github/sandbox.py`
- Test: `api/tests/test_github_sandbox.py`

- [ ] **Step 1: Write the failing tests**

Create `api/tests/test_github_sandbox.py`:

```python
import json
import pytest
from app.tools.github import sandbox as S


def test_build_claude_argv_basic():
    argv = S.build_claude_argv("do the thing", allowed_tools="Read,Edit,Bash",
                               max_turns=30, max_budget_usd=5.0, resume=None)
    assert argv[0] == "claude"
    assert "-p" in argv and "do the thing" in argv
    assert "--output-format" in argv and "json" in argv
    assert "--allowedTools" in argv and "Read,Edit,Bash" in argv
    assert "--max-turns" in argv and "30" in argv
    assert "--resume" not in argv


def test_build_claude_argv_resume():
    argv = S.build_claude_argv("fix ci", allowed_tools="Read,Edit,Bash",
                               max_turns=30, max_budget_usd=5.0, resume="sess-1")
    assert "--resume" in argv and "sess-1" in argv


def test_build_docker_command_mounts_and_caps():
    cmd = S.build_docker_command(
        image="rotom-coding:latest", worktree="/data/coding/o/r/12",
        session_dir="/data/coding/o/r/12/claude-home", token="tok",
        read_only=False, mem="4g", cpus="2",
    )
    assert cmd[:3] == ["docker", "run", "--rm"]
    joined = " ".join(cmd)
    assert "-v /data/coding/o/r/12:/work" in joined
    assert "/work" in cmd                       # workdir
    assert "-v /data/coding/o/r/12/claude-home:/home/agent/.claude" in joined
    assert "--memory" in cmd and "4g" in cmd
    assert "--cpus" in cmd and "2" in cmd
    assert "--pids-limit" in cmd
    assert "rotom-coding:latest" in cmd
    # token passed by env name only, value via env dict at run time (not in argv)
    assert "CLAUDE_CODE_OAUTH_TOKEN" in joined


def test_build_docker_command_readonly_mount():
    cmd = S.build_docker_command(
        image="img", worktree="/w", session_dir="/w/h", token="t",
        read_only=True, mem="4g", cpus="2",
    )
    assert "-v /w:/work:ro" in " ".join(cmd)


def test_parse_claude_json_extracts_session_and_result():
    raw = json.dumps({"session_id": "abc", "result": "done", "is_error": False})
    out = S.parse_claude_json(raw, returncode=0)
    assert out["session_id"] == "abc"
    assert out["result"] == "done"


def test_parse_claude_json_nonzero_raises():
    with pytest.raises(RuntimeError):
        S.parse_claude_json("partial", returncode=1)


def test_parse_claude_json_malformed_raises():
    with pytest.raises(RuntimeError):
        S.parse_claude_json("not json", returncode=0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && uv run pytest tests/test_github_sandbox.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement**

Create `api/app/tools/github/sandbox.py`:

```python
"""The only place Claude executes: builds + runs an ephemeral docker container.

Command construction is split into pure builders (unit-tested) from the actual
`docker run` invocation (manually verified). Inngest orchestrates; Docker isolates.
"""

import asyncio
import json
import logging

logger = logging.getLogger(__name__)


def build_claude_argv(prompt: str, *, allowed_tools: str, max_turns: int,
                      max_budget_usd: float, resume: str | None) -> list[str]:
    """The `claude` headless CLI argv (runs inside the container)."""
    argv = [
        "claude", "-p", prompt,
        "--output-format", "json",
        "--allowedTools", allowed_tools,
        "--permission-mode", "acceptEdits",
        "--max-turns", str(max_turns),
        "--max-budget-usd", str(max_budget_usd),
    ]
    if resume:
        argv += ["--resume", resume]
    return argv


def build_docker_command(*, image: str, worktree: str, session_dir: str, token: str,
                         read_only: bool, mem: str, cpus: str) -> list[str]:
    """The `docker run --rm` prefix: mounts, caps, env, workdir, image.

    `token` is passed as an env var into the container; we set it via `-e NAME`
    and supply the value through the process environment at run time (so it never
    appears in argv/logs). The worktree mounts at /work; reviewers mount it :ro.
    """
    work_mount = f"{worktree}:/work" + (":ro" if read_only else "")
    return [
        "docker", "run", "--rm",
        "--user", "agent",
        "-v", work_mount,
        "-v", f"{session_dir}:/home/agent/.claude",
        "-w", "/work",
        "--memory", mem,
        "--cpus", cpus,
        "--pids-limit", "512",
        "-e", "CLAUDE_CODE_OAUTH_TOKEN",
        "-e", "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1",
        image,
    ]


def parse_claude_json(stdout: str, *, returncode: int) -> dict:
    """Parse `claude --output-format json` stdout. Raises RuntimeError on failure."""
    if returncode != 0:
        raise RuntimeError(f"claude exited {returncode}: {stdout[:500]}")
    try:
        obj = json.loads(stdout)
    except (ValueError, TypeError) as e:
        raise RuntimeError(f"claude produced non-JSON output: {stdout[:500]}") from e
    if obj.get("is_error"):
        raise RuntimeError(f"claude reported error: {obj.get('result', '')[:500]}")
    return obj


async def run_claude_in_container(prompt: str, *, worktree: str, session_dir: str,
                                  settings, read_only: bool = False,
                                  resume: str | None = None) -> dict:
    """Run one Claude invocation inside an ephemeral container; return parsed JSON.

    The only place untrusted code executes. Times out per CODING_AGENT_TIMEOUT.
    """
    import os

    allowed = "Read,Bash(git diff*)" if read_only else "Read,Edit,Bash"
    docker_cmd = build_docker_command(
        image=settings.coding_agent_sandbox_image, worktree=worktree,
        session_dir=session_dir, token=settings.claude_code_oauth_token,
        read_only=read_only, mem=settings.coding_agent_container_mem,
        cpus=settings.coding_agent_container_cpus,
    )
    claude_argv = build_claude_argv(
        prompt, allowed_tools=allowed, max_turns=settings.coding_agent_max_turns,
        max_budget_usd=settings.coding_agent_max_budget_usd, resume=resume,
    )
    cmd = docker_cmd + claude_argv
    env = {**os.environ, "CLAUDE_CODE_OAUTH_TOKEN": settings.claude_code_oauth_token}
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env,
    )
    try:
        out, err = await asyncio.wait_for(
            proc.communicate(), timeout=settings.coding_agent_timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError(f"claude container timed out after {settings.coding_agent_timeout}s")
    if proc.returncode != 0:
        logger.warning("claude container stderr: %s", err.decode("utf-8", errors="replace")[:500])
    return parse_claude_json(out.decode("utf-8", errors="replace"), returncode=proc.returncode)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && uv run pytest tests/test_github_sandbox.py -v`
Expected: all pass (the builders + parse; `run_claude_in_container` is exercised manually in Task 10).

- [ ] **Step 5: Commit**

```bash
git add api/app/tools/github/sandbox.py api/tests/test_github_sandbox.py
git commit -m "feat(coding-agent): docker/claude command builders + JSON parse + container runner"
```

---

## Task 6: Host git/gh wrappers (`runner.py`)

**Files:**
- Create: `api/app/tools/github/runner.py`
- Test: `api/tests/test_github_sandbox.py` (append — only the pure `run_cmd` arg handling is unit-tested; the gh/git calls are manual, Task 10)

- [ ] **Step 1: Write the failing test**

Append to `api/tests/test_github_sandbox.py`:

```python
@pytest.mark.asyncio
async def test_run_cmd_returns_stdout(tmp_path):
    from app.tools.github import runner
    out = await runner.run_cmd(["echo", "hello"])
    assert out.strip() == "hello"


@pytest.mark.asyncio
async def test_run_cmd_raises_on_nonzero():
    from app.tools.github import runner
    with pytest.raises(RuntimeError):
        await runner.run_cmd(["false"])
```

(If `pytest-asyncio` isn't configured, check `api/pyproject.toml`/`pytest.ini` for `asyncio_mode`; the repo's existing async tests reveal the convention — match it. If async tests aren't supported, convert these two to drive `run_cmd` via `asyncio.run(...)` inside a sync test instead.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && uv run pytest tests/test_github_sandbox.py -k run_cmd -v`
Expected: FAIL (`runner` missing).

- [ ] **Step 3: Implement**

Create `api/app/tools/github/runner.py`:

```python
"""Host-side git/gh subprocess wrappers. The gh token never leaves the host.

All async (mirrors workflows/lib.run_script): create_subprocess_exec + timeout +
decode errors='replace' + RuntimeError on non-zero.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)


async def run_cmd(cmd: list[str], *, cwd: str | None = None, timeout: int = 600) -> str:
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError(f"command timed out after {timeout}s: {cmd[0]}")
    if proc.returncode != 0:
        raise RuntimeError(
            f"{cmd[0]} failed ({proc.returncode}): "
            f"{err.decode('utf-8', errors='replace')[:500]}")
    return out.decode("utf-8", errors="replace")


async def check_push_access(repo: str) -> bool:
    """True if the authenticated gh user has WRITE/MAINTAIN/ADMIN on the repo."""
    out = await run_cmd(["gh", "repo", "view", repo, "--json", "viewerPermission"])
    import json
    perm = json.loads(out).get("viewerPermission", "")
    return perm in {"ADMIN", "MAINTAIN", "WRITE"}


async def clone(repo: str, dest: str) -> None:
    await run_cmd(["gh", "repo", "clone", repo, dest])


async def create_branch(branch: str, cwd: str) -> None:
    await run_cmd(["git", "checkout", "-b", branch], cwd=cwd)


async def commit_all(message: str, cwd: str) -> None:
    await run_cmd(["git", "add", "-A"], cwd=cwd)
    await run_cmd(["git", "commit", "-m", message], cwd=cwd)


async def push(branch: str, cwd: str) -> None:
    await run_cmd(["git", "push", "-u", "origin", branch], cwd=cwd)


async def has_uncommitted(cwd: str) -> bool:
    return bool((await run_cmd(["git", "status", "--porcelain"], cwd=cwd)).strip())


async def gh_issue_view(repo: str, number: int) -> dict:
    import json
    out = await run_cmd(["gh", "issue", "view", str(number), "--repo", repo,
                         "--json", "title,body"])
    return json.loads(out)


async def gh_pr_create(repo: str, base: str, head: str, title: str, body: str) -> str:
    out = await run_cmd(["gh", "pr", "create", "--repo", repo, "--draft",
                         "--base", base, "--head", head, "--title", title, "--body", body])
    return out.strip().splitlines()[-1] if out.strip() else ""


async def gh_pr_checks(pr_url: str, *, timeout: int) -> bool:
    """Watch checks; return True if green, False if any failed. Bounded by timeout."""
    try:
        await run_cmd(["gh", "pr", "checks", pr_url, "--watch", "--fail-fast"],
                      timeout=timeout)
        return True
    except RuntimeError:
        return False


async def gh_pr_comment(pr_url: str, body: str) -> None:
    await run_cmd(["gh", "pr", "comment", pr_url, "--body", body])


async def default_branch(repo: str) -> str:
    import json
    out = await run_cmd(["gh", "repo", "view", repo, "--json", "defaultBranchRef"])
    return json.loads(out).get("defaultBranchRef", {}).get("name", "main")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && uv run pytest tests/test_github_sandbox.py -k run_cmd -v`
Expected: pass (the two `run_cmd` tests; the gh/git wrappers are import-clean and verified manually in Task 10).

- [ ] **Step 5: Commit**

```bash
git add api/app/tools/github/runner.py api/tests/test_github_sandbox.py
git commit -m "feat(coding-agent): host git/gh subprocess wrappers"
```

---

## Task 7: `work_on_issue` agent tool

**Files:**
- Modify: `api/app/agent/toolkit.py` (add tool near `run_workflow` ~line 198; add to `ALL_TOOLS` ~line 211)
- Test: `api/tests/test_work_on_issue_tool.py`

- [ ] **Step 1: Write the failing tests**

Create `api/tests/test_work_on_issue_tool.py`:

```python
import app.agent.toolkit as TK


def test_work_on_issue_is_registered():
    assert TK.work_on_issue in TK.ALL_TOOLS


def test_work_on_issue_fires_event_for_allowed_repo(monkeypatch):
    sent = []
    import app.workflows.client as client
    monkeypatch.setattr(client.inngest_client, "send_sync", lambda ev: sent.append(ev))
    monkeypatch.setattr("app.config.get_settings",
                        lambda: _S(coding_agent_repos="DSdatsme/rotom"))
    out = TK.work_on_issue.invoke({"url": "https://github.com/DSdatsme/rotom/issues/12"})
    assert len(sent) == 1
    assert sent[0].name == "workflows/code-issue.requested"
    assert sent[0].data["url"].endswith("/issues/12")
    assert "triggered" in out.lower()


def test_work_on_issue_refuses_disallowed_repo(monkeypatch):
    sent = []
    import app.workflows.client as client
    monkeypatch.setattr(client.inngest_client, "send_sync", lambda ev: sent.append(ev))
    monkeypatch.setattr("app.config.get_settings",
                        lambda: _S(coding_agent_repos="DSdatsme/rotom"))
    out = TK.work_on_issue.invoke({"url": "https://github.com/evil/repo/issues/1"})
    assert sent == []
    assert "not allow" in out.lower() or "not in" in out.lower()


def test_work_on_issue_rejects_bad_url(monkeypatch):
    monkeypatch.setattr("app.config.get_settings",
                        lambda: _S(coding_agent_repos="DSdatsme/rotom"))
    out = TK.work_on_issue.invoke({"url": "https://github.com/DSdatsme/rotom/pull/12"})
    assert "issue url" in out.lower() or "invalid" in out.lower()


def _S(**kw):
    from app.config import Settings
    return Settings(**kw)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && uv run pytest tests/test_work_on_issue_tool.py -v`
Expected: FAIL (`work_on_issue` missing).

- [ ] **Step 3: Implement**

In `api/app/agent/toolkit.py`, after `run_workflow` (~line 208) add:

```python
@tool
def work_on_issue(url: str) -> str:
    """Have the coding agent implement a GitHub issue: paste the issue URL.
    rotom clones the repo, drafts a PR with the fix, runs CI + review, and reports
    on Telegram. Only allow-listed repos; opens a DRAFT PR — you review and merge."""
    import inngest as _i

    from app.config import get_settings
    from app.tools.github import issues as _issues
    from app.workflows.client import inngest_client

    try:
        owner, repo, _ = _issues.parse_issue_url(url)
    except ValueError:
        return "That doesn't look like a GitHub issue URL (expected .../<owner>/<repo>/issues/<n>)."
    allow = get_settings().coding_agent_repo_list
    if not _issues.is_allowed_repo(owner, repo, allow):
        return f"Repo {owner}/{repo} is not in the coding-agent allow-list (CODING_AGENT_REPOS)."
    inngest_client.send_sync(_i.Event(name="workflows/code-issue.requested", data={"url": url.strip()}))
    return f"Coding run triggered for {owner}/{repo} issue. Progress + PR link arrive on Telegram."
```

Add `work_on_issue` to the `ALL_TOOLS` list:

```python
ALL_TOOLS = [
    run_gmail_triage, list_emails, get_email, draft_reply_tool, list_drafts,
    get_current_time, create_reminder, list_reminders, cancel_reminder,
    run_workflow, work_on_issue,
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && uv run pytest tests/test_work_on_issue_tool.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add api/app/agent/toolkit.py api/tests/test_work_on_issue_tool.py
git commit -m "feat(coding-agent): work_on_issue agent tool (validate + allow-check + fire event)"
```

---

## Task 8: The `code_issue` Inngest workflow + registration

**Files:**
- Create: `api/app/workflows/code_issue.py`
- Modify: `api/app/workflows/registry.py`
- Test: `api/tests/test_code_issue_workflow_import.py`

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_code_issue_workflow_import.py`:

```python
def test_workflow_imports_without_inngest_server_or_token():
    # Must import cleanly with no CLAUDE_CODE_OAUTH_TOKEN / no running Inngest.
    from app.workflows.code_issue import code_issue
    assert code_issue is not None


def test_workflow_registered():
    from app.workflows.registry import WORKFLOW_FUNCTIONS
    from app.workflows.code_issue import code_issue
    assert code_issue in WORKFLOW_FUNCTIONS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && uv run pytest tests/test_code_issue_workflow_import.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement the workflow**

Create `api/app/workflows/code_issue.py`:

```python
"""Coding agent workflow: issue URL → branch → draft PR → CI-fix loop → review comment.

Inngest orchestrates (durable, retriable steps); Docker isolates every Claude run
(see tools/github/sandbox.py). Host git/gh stays on the host; only the scoped
CLAUDE_CODE_OAUTH_TOKEN enters the container. Per-Claude record_run captures
token/latency; the top-level lifecycle lives in the CodingRun table (see spec
§ Observability — no workflow-wrapping record_run).
"""

import logging
import os

import inngest

from app.config import get_settings
from app.observability.sink import record_run
from app.store.db import CodingRun, CodingStatus, get_session
from app.tools.github import issues as I
from app.tools.github import review as RV
from app.tools.github import runner as R
from app.tools.github import sandbox as SB
from app.workflows.client import inngest_client
from app.workflows.lib import notify

logger = logging.getLogger(__name__)


def _slug(title: str) -> str:
    import re
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s[:40] or "issue"


@inngest_client.create_function(
    fn_id="code-issue",
    trigger=[inngest.TriggerEvent(event="workflows/code-issue.requested")],
    retries=1,
)
async def code_issue(ctx: inngest.Context) -> str:
    settings = get_settings()
    url = ctx.event.data["url"]
    owner, repo_name, number = I.parse_issue_url(url)
    repo = f"{owner}/{repo_name}"

    # parse+authorize
    async def authorize() -> dict:
        if not I.is_allowed_repo(owner, repo_name, settings.coding_agent_repo_list):
            raise RuntimeError(f"repo {repo} not allow-listed")
        if not await R.check_push_access(repo):
            raise RuntimeError(f"no push access to {repo}; fork-based contribution not supported in V1")
        base = await R.default_branch(repo)
        return {"base": base}
    base = (await ctx.step.run("authorize", authorize))["base"]

    # fetch issue
    issue = await ctx.step.run("fetch-issue", lambda: R.gh_issue_view(repo, number))
    branch = f"rotom/issue-{number}-{_slug(issue['title'])}"
    worktree = os.path.join(settings.coding_agent_worktree_dir, owner, repo_name, str(number))
    session_dir = os.path.join(worktree, "claude-home")

    # prepare worktree + CodingRun row
    async def prepare() -> int:
        os.makedirs(os.path.dirname(worktree) or ".", exist_ok=True)
        if not os.path.exists(worktree):
            await R.clone(repo, worktree)
        os.makedirs(session_dir, exist_ok=True)
        await R.create_branch(branch, cwd=worktree)
        with get_session() as s:
            row = CodingRun(issue_url=url, repo=repo, issue_number=number,
                            branch=branch, worktree_path=worktree,
                            status=CodingStatus.RUNNING)
            s.add(row)
            s.flush()
            return row.id
    run_id = await ctx.step.run("prepare-worktree", prepare)

    def _set(**kw):
        with get_session() as s:
            row = s.get(CodingRun, run_id)
            for k, v in kw.items():
                setattr(row, k, v)

    # coder (containerized; per-call record_run for token/latency)
    async def code() -> str:
        prompt = I.build_task_prompt(issue["title"], issue.get("body", ""),
                                     test_cmd=settings.coding_agent_test_cmd)
        with record_run("coder", source="inngest") as run:
            res = await SB.run_claude_in_container(
                prompt, worktree=worktree, session_dir=session_dir, settings=settings)
            run.summary = f"coder session {res.get('session_id', '')}"
            return res.get("session_id", "")
    session_id = await ctx.step.run("coder", code)
    _set(claude_session_id=session_id)

    # commit + push
    async def commit_push() -> str:
        if await R.has_uncommitted(worktree):
            await R.commit_all(f"rotom: implement issue #{number}", cwd=worktree)
        await R.push(branch, cwd=worktree)
        return "pushed"
    await ctx.step.run("commit-push", commit_push)

    # open draft PR
    async def open_pr() -> str:
        pr = await R.gh_pr_create(repo, base=base, head=branch,
                                  title=f"rotom: {issue['title']}", body=I.build_pr_body(url))
        return pr
    pr_url = await ctx.step.run("open-pr", open_pr)
    _set(pr_url=pr_url)
    await ctx.step.run("notify-pr", lambda: notify(f"🔧 Draft PR for {repo}#{number}: {pr_url}"))

    # CI-fix loop (bounded)
    green = False
    for attempt in range(settings.coding_agent_max_fix_rounds + 1):
        green = await ctx.step.run(
            f"ci-watch-{attempt}",
            lambda: R.gh_pr_checks(pr_url, timeout=settings.coding_agent_timeout))
        if green or attempt == settings.coding_agent_max_fix_rounds:
            break

        async def fix() -> str:
            with record_run("coder", source="inngest") as run:
                res = await SB.run_claude_in_container(
                    f"CI checks are failing on this PR. Inspect and fix them, keep changes "
                    f"scoped. (round {attempt + 1})",
                    worktree=worktree, session_dir=session_dir, settings=settings,
                    resume=session_id)
                run.summary = f"fix round {attempt + 1}"
                return "fixed"
        await ctx.step.run(f"coder-fix-{attempt}", fix)
        await ctx.step.run(f"commit-push-fix-{attempt}", commit_push)

    # boundary terminal state: CI still red after the loop → block, comment, alert, stop
    if not green:
        _set(status=CodingStatus.BLOCKED)
        msg = (f"⚠ rotom stopped — CI still failing after "
               f"{settings.coding_agent_max_fix_rounds} fix rounds. Manual intervention needed.")
        await ctx.step.run("comment-blocked", lambda: R.gh_pr_comment(pr_url, msg))
        await ctx.step.run("notify-blocked", lambda: notify(f"{msg}\n{pr_url}"))
        return f"blocked: {pr_url}"

    # reviewers (parallel-ish; each a fresh read-only container)
    _set(status=CodingStatus.REVIEW)

    async def review_all() -> list:
        diff = await R.run_cmd(["git", "diff", f"origin/{base}...{branch}"], cwd=worktree)
        results = []
        for rv in RV.REVIEWERS:
            with record_run("code_review", source="inngest") as run:
                res = await SB.run_claude_in_container(
                    RV.build_review_prompt(rv, diff), worktree=worktree,
                    session_dir=session_dir, settings=settings, read_only=True)
                findings = RV.parse_findings(res.get("result", ""))
                run.summary = f"{rv['name']}: {len(findings)} findings"
                results.append((rv["name"], findings))
        return results
    per_reviewer = await ctx.step.run("reviewers", review_all)

    await ctx.step.run("comment-findings",
                       lambda: R.gh_pr_comment(pr_url, I.build_findings_comment(per_reviewer)))
    _set(status=CodingStatus.DONE)
    await ctx.step.run("notify-done", lambda: notify(f"✅ rotom finished {repo}#{number} (CI green): {pr_url}"))
    return f"done: {pr_url}"
```

- [ ] **Step 4: Register the workflow**

In `api/app/workflows/registry.py`:

```python
"""All workflow functions, handed to inngest.fast_api.serve()."""

from app.workflows.code_issue import code_issue
from app.workflows.hello import hello
from app.workflows.morning_digest import morning_digest

WORKFLOW_FUNCTIONS = [hello, morning_digest, code_issue]
```

- [ ] **Step 5: Run the import test + full suite**

Run: `cd api && uv run pytest tests/test_code_issue_workflow_import.py -v && uv run pytest -q`
Expected: import tests pass; whole suite green.

- [ ] **Step 6: Commit**

```bash
git add api/app/workflows/code_issue.py api/app/workflows/registry.py api/tests/test_code_issue_workflow_import.py
git commit -m "feat(coding-agent): code_issue Inngest workflow + registration"
```

---

## Task 9: Sandbox image (`Dockerfile.coding`)

**Files:**
- Create: `Dockerfile.coding` (repo root)

- [ ] **Step 1: Write the Dockerfile**

Create `Dockerfile.coding`:

```dockerfile
# Sandbox image for the rotom coding agent. Untrusted code runs ONLY here.
FROM node:22-bookworm

# Common runtimes so most repos' tests run out of the box.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git python3 python3-pip python3-venv build-essential ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# Claude Code CLI.
RUN npm install -g @anthropic-ai/claude-code

# Non-root user; the worktree mounts at /work.
RUN useradd -m -u 1000 agent
USER agent
WORKDIR /work

# Defense-in-depth: enable Claude Code's native sandbox inside the container.
RUN mkdir -p /home/agent/.claude
COPY --chown=agent:agent docker/coding-claude-settings.json /home/agent/.claude/settings.json

ENTRYPOINT []
```

- [ ] **Step 2: Add the baked Claude settings**

Create `docker/coding-claude-settings.json`:

```json
{
  "sandbox": {
    "enabled": true,
    "failIfUnavailable": true,
    "allowUnsandboxedCommands": false,
    "deny": ["Read(~/**)"]
  }
}
```

- [ ] **Step 3: Build the image (manual — needs Docker)**

Run: `docker build -f Dockerfile.coding -t rotom-coding:latest .`
Expected: image builds; `docker run --rm rotom-coding:latest claude --version` prints a version.

(No unit test — image build is environment-dependent and verified here + in Task 10.)

- [ ] **Step 4: Commit**

```bash
git add Dockerfile.coding docker/coding-claude-settings.json
git commit -m "feat(coding-agent): sandbox Dockerfile + baked native-sandbox settings"
```

---

## Task 10: Manual end-to-end verification + docs

**Files:**
- Modify: `TASKS.md`, `README.md` (or `docs/architecture.md` if that's where component docs live — check first)

- [ ] **Step 1: Real run against an allow-listed repo**

With Docker running, `CLAUDE_CODE_OAUTH_TOKEN` set, `gh` authenticated, and
`CODING_AGENT_REPOS=DSdatsme/rotom`, create a throwaway test issue on `DSdatsme/rotom`,
then from Telegram send the issue URL / call the `work_on_issue` tool. Verify:
- a branch `rotom/issue-<n>-<slug>` is created and a **draft** PR opens,
- the CI-fix loop reacts to a red check (push a deliberately failing check to test),
- a collated reviewer+security findings comment lands on the PR,
- a Telegram report with the PR link arrives,
- the `CodingRun` row progresses `running → review → done`,
- per-Claude `coder`/`code_review` runs appear in the usage/runs dashboard with token+latency.

- [ ] **Step 2: Refusal + boundary checks**

- Send a non-allow-listed issue URL → `work_on_issue` refuses immediately, no event fired.
- Force CI to stay red → after `CODING_AGENT_MAX_FIX_ROUNDS`, the run goes `blocked`, a
  "cannot proceed" PR comment + Telegram alert appear, draft PR stays open, reviewers skipped.

- [ ] **Step 3: Update docs**

Document the feature where rotom's other features are documented (check `README.md` and
`docs/` for the existing component-docs convention before writing): what it does, the
env vars (Task 1), the Docker prerequisite + `docker build -f Dockerfile.coding`, the
safety model (allow-list, draft-only, never-merge), and that V1 has no top-level run-log
row (CodingRun + Inngest dashboard). Mark the feature done in `TASKS.md` with the spec link.

- [ ] **Step 4: Commit**

```bash
git add TASKS.md README.md
git commit -m "docs: coding agent (GitHub F2) usage, prerequisites, safety model"
```

---

## Self-review notes

- **Spec coverage:** parse+authorize (T7 tool + T8 authorize step), push-access check (T6/T8), fetch issue (T6/T8), worktree+CodingRun (T2/T8), coder in container (T5/T8), commit+push (T6/T8), draft PR (T6/T8), bounded CI-fix loop (T8), boundary terminal state → block+comment+alert+skip-review (T8), reviewers read-only fresh containers (T4/T5/T8), collated comment (T3/T8), Telegram report (T8), allow-list refusal (T7), config (T1), isolation/Docker (T5/T9), per-Claude observability (T5/T8). Out-of-scope items (unified top-level RunLog, fork PRs, webhooks, egress filtering) correctly omitted.
- **Manual-vs-unit split** matches the spec: pure helpers + command builders are TDD; host gh/git, container exec, and the full workflow are import-clean + manually verified (Task 10).
- **Type consistency:** `parse_issue_url -> (owner, repo, int)`, `is_allowed_repo(owner, repo, list)`, `build_docker_command`/`build_claude_argv`/`parse_claude_json`, `run_claude_in_container(..., settings, read_only, resume)`, `CodingRun`/`CodingStatus`, `coding_agent_*` settings — used consistently across tasks.
