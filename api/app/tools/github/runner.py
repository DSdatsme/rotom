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
    """Watch checks; return True if green, False otherwise. Bounded by timeout.

    `gh pr checks --watch` exits non-zero when a check fails, which run_cmd turns
    into a RuntimeError → we map to False (red). NOTE: this also maps non-CI
    failures (timeout, bad URL, gh auth/availability) to False, so the workflow
    treats them as a fixable red. Acceptable for V1 (the workflow's fix-loop +
    boundary caps bound the blast radius); a future version can distinguish them.
    """
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
