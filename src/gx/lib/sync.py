"""Pull-the-remote flow helpers.

Reusable primitives for fetching, rebasing, and reporting on remote-sync
operations against the current branch's upstream.
"""

from __future__ import annotations

import typer
from nllog import error, step, success

from gx.lib.branch import current_branch, tracking_branch
from gx.lib.display import commit_text
from gx.lib.git import git
from gx.lib.workspace import is_rebase_in_progress, rollback


def validate_branch() -> tuple[str, str, str]:
    """Validate branch state and return (branch, remote, remote_branch).

    Raises:
        typer.Exit: If the branch is detached or has no upstream configured.
    """
    branch = current_branch()
    if branch is None:
        error("Cannot sync - HEAD is detached.")
        raise typer.Exit(1)

    tracking = tracking_branch()
    if tracking is None:
        error(f"Branch '{branch}' has no upstream tracking branch configured.")
        raise typer.Exit(1)

    remote, remote_branch = tracking
    return branch, remote, remote_branch


def fetch_and_rebase(remote: str, remote_branch: str, *, stashed: bool) -> None:
    """Fetch from remote and pull with rebase.

    Args:
        remote: The remote name to fetch from.
        remote_branch: The remote branch to rebase onto.
        stashed: Whether local changes were stashed, used for rollback.
    """
    with step(f"Fetch from {remote}"):
        result = git("fetch", remote)
        if not result.success:
            rollback(stashed=stashed)

    with step(f"Pull with rebase from {remote}/{remote_branch}"):
        result = git("pull", "--rebase", remote, remote_branch)
        if not result.success:
            if is_rebase_in_progress():
                error(
                    "Rebase conflict detected",
                    details=[
                        "1. Fix the conflicts in the affected files",
                        "2. Stage the resolved files with 'git add'",
                        "3. Continue with 'git rebase --continue'",
                        "Or abort with 'git rebase --abort'",
                    ],
                )
            else:
                error(f"Failed to pull from {remote}/{remote_branch}")
            rollback(stashed=stashed)


def print_pull_summary(head_before: str, remote: str, remote_branch: str) -> None:
    """Print a summary of commits pulled since the pre-pull HEAD.

    Args:
        head_before: The commit SHA before the pull.
        remote: The remote name.
        remote_branch: The remote branch name.
    """
    head_after = git("rev-parse", "HEAD")
    if head_before == head_after.stdout:
        success("Already up to date")
        return

    log_result = git("log", "--oneline", f"{head_before}..{head_after.stdout}")
    if log_result.success and log_result.stdout:
        commits = log_result.stdout.splitlines()
        success(
            f"Pull {len(commits)} new commit(s) from {remote}/{remote_branch}",
            details=[commit_text(c) for c in commits],
        )
    else:
        success("Pull complete")
