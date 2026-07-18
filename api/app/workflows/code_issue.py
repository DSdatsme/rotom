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


def worktree_path(settings, owner: str, repo_name: str, number: int) -> str:
    """The cloned git worktree for an issue (mounted at /work, where `git add -A` runs)."""
    return os.path.join(settings.coding_agent_worktree_dir, owner, repo_name, str(number))


def session_dir_path(settings, owner: str, repo_name: str, number: int) -> str:
    """Claude's ~/.claude state dir — kept OUTSIDE the worktree on purpose.

    It is bind-mounted into the container, and Claude persists session transcripts
    there. If it lived under the worktree, the workflow's `git add -A` + push would
    commit those transcripts (untrusted issue text + every file the agent read,
    including any secrets) to the PR branch. Siblinged under `.sessions/` it can't be.
    """
    return os.path.join(settings.coding_agent_worktree_dir, ".sessions",
                        owner, repo_name, str(number))


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

    async def authorize() -> dict:
        if not I.is_allowed_repo(owner, repo_name, settings.coding_agent_repo_list):
            raise RuntimeError(f"repo {repo} not allow-listed")
        if not await R.check_push_access(repo):
            raise RuntimeError(f"no push access to {repo}; fork-based contribution not supported in V1")
        base = await R.default_branch(repo)
        return {"base": base}
    base = (await ctx.step.run("authorize", authorize))["base"]

    issue = await ctx.step.run("fetch-issue", lambda: R.gh_issue_view(repo, number))
    branch = f"rotom/issue-{number}-{_slug(issue['title'])}"
    worktree = worktree_path(settings, owner, repo_name, number)
    session_dir = session_dir_path(settings, owner, repo_name, number)

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

    async def commit_push() -> str:
        if await R.has_uncommitted(worktree):
            await R.commit_all(f"rotom: implement issue #{number}", cwd=worktree)
        await R.push(branch, cwd=worktree)
        return "pushed"
    await ctx.step.run("commit-push", commit_push)

    async def open_pr() -> str:
        pr = await R.gh_pr_create(repo, base=base, head=branch,
                                  title=f"rotom: {issue['title']}", body=I.build_pr_body(url))
        return pr
    pr_url = await ctx.step.run("open-pr", open_pr)
    _set(pr_url=pr_url)
    await ctx.step.run("notify-pr", lambda: notify(f"🔧 Draft PR for {repo}#{number}: {pr_url}"))

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

    if not green:
        _set(status=CodingStatus.BLOCKED)
        msg = (f"⚠ rotom stopped — CI still failing after "
               f"{settings.coding_agent_max_fix_rounds} fix rounds. Manual intervention needed.")
        await ctx.step.run("comment-blocked", lambda: R.gh_pr_comment(pr_url, msg))
        await ctx.step.run("notify-blocked", lambda: notify(f"{msg}\n{pr_url}"))
        return f"blocked: {pr_url}"

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
