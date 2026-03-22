"""Pull subcommand for gx."""

from __future__ import annotations

from pathlib import Path

import typer

from gx.lib.branch import current_branch, tracking_branch
from gx.lib.console import error, set_verbosity, step, step_result, warning
from gx.lib.git import check_git_repo, git, set_dry_run
from gx.lib.options import DRY_RUN_OPTION, VERBOSE_OPTION

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

app = typer.Typer(rich_markup_mode="rich", context_settings=CONTEXT_SETTINGS)


def is_dirty() -> bool:
    """Return True if the working tree has uncommitted changes or untracked files."""
    result = git("status", "--porcelain")
    return result.success and result.stdout != ""


def has_submodules() -> bool:
    """Return True if the repo has a .gitmodules file at its root."""
    path = Path.cwd()
    for parent in [path, *path.parents]:
        if (parent / ".git").exists():
            return (parent / ".gitmodules").exists()
    return False


def is_rebase_in_progress() -> bool:
    """Return True if a rebase is currently in progress."""
    result = git("rev-parse", "--git-dir")
    if not result.success:
        return False
    git_dir = Path(result.stdout)
    return (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists()


def rollback(*, stashed: bool) -> None:
    """Unstash if we stashed earlier, then exit."""
    if stashed:
        warning("Restoring stashed changes...")
        git("stash", "pop")
    raise typer.Exit(1)


def validate_branch() -> tuple[str, str, str]:
    """Validate branch state and return (branch, remote, remote_branch).

    Raises:
        typer.Exit: If the branch is detached or has no upstream configured.
    """
    branch = current_branch()
    if branch is None:
        error("Cannot pull in detached HEAD state.")
        raise typer.Exit(1)

    tracking = tracking_branch()
    if tracking is None:
        error(f"Branch '{branch}' has no upstream tracking branch configured.")
        raise typer.Exit(1)

    remote, remote_branch = tracking
    return branch, remote, remote_branch


def stash_if_dirty() -> bool:
    """Stash uncommitted changes if the working tree is dirty.

    Returns:
        True if changes were stashed, False otherwise.
    """
    if not is_dirty():
        return False

    with step("Stash local changes"):
        git("stash", "--include-untracked").raise_on_error()
    return True


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
                error("Rebase conflict detected")
                error("1. Fix the conflicts in the affected files", detail=True)
                error("2. Stage the resolved files with 'git add'", detail=True)
                error("3. Continue with 'git rebase --continue'", detail=True)
                error("Or abort with 'git rebase --abort'", detail=True)
            else:
                error(f"Failed to pull from {remote}/{remote_branch}")
            rollback(stashed=stashed)


def update_submodules(*, stashed: bool) -> None:
    """Update submodules if a .gitmodules file is present.

    Args:
        stashed: Whether local changes were stashed, used for rollback.
    """
    if not has_submodules():
        return

    with step("Update submodules"):
        result = git("submodule", "update", "--init", "--recursive")
        if not result.success:
            error("Failed to update submodules")
            rollback(stashed=stashed)


def unstash(*, stashed: bool) -> None:
    """Restore stashed changes after a successful pull.

    Args:
        stashed: Whether changes were stashed before pulling.

    Raises:
        typer.Exit: If the stash pop fails due to conflicts.
    """
    if not stashed:
        return

    with step("Restore stashed changes"):
        result = git("stash", "pop")
        if not result.success:
            warning("Could not cleanly restore stashed changes")
            warning(
                "Your pull succeeded, but stashed changes conflict with pulled code", detail=True
            )
            warning("Run 'git stash show' to see stashed changes", detail=True)
            warning("Run 'git stash pop' to try again, or 'git stash drop' to discard", detail=True)
            raise typer.Exit(1)


def print_summary(head_before: str, remote: str, remote_branch: str) -> None:
    """Print a summary of commits pulled since the pre-pull HEAD.

    Args:
        head_before: The commit SHA before the pull.
        remote: The remote name.
        remote_branch: The remote branch name.
    """
    head_after = git("rev-parse", "HEAD")
    if head_before == head_after.stdout:
        step_result("Already up to date")
        return

    log_result = git("log", "--oneline", f"{head_before}..{head_after.stdout}")
    if log_result.success and log_result.stdout:
        commits = log_result.stdout.splitlines()
        step_result(
            f"Pull {len(commits)} new commit(s) from {remote}/{remote_branch}",
            subs=commits,
        )
    else:
        step_result("Pull complete")


@app.callback(invoke_without_command=True)
def pull(
    ctx: typer.Context,  # noqa: ARG001
    verbose: int = VERBOSE_OPTION,
    dry_run: bool = DRY_RUN_OPTION,  # noqa: FBT001
) -> None:
    """Pull latest changes from the remote tracking branch.

    Fetches and rebases the current branch onto its upstream. Automatically handles uncommitted changes by stashing before the pull and restoring after.

    [bold]What happens:[/bold]

    1. Stashes any uncommitted changes (including untracked files)
    2. Fetches from the remote
    3. Rebases onto the upstream branch
    4. Updates submodules if .gitmodules is present
    5. Restores stashed changes
    6. Prints a summary of new commits

    If a rebase conflict occurs, gx restores your stash and provides instructions for resolving the conflict manually.

    [bold]Examples:[/bold]

      gx pull              Pull and rebase current branch
      gx pull -n           Preview what would happen
      gx pull -v           Pull with debug output
    """
    if verbose:
        set_verbosity(verbose)
    if dry_run:
        set_dry_run(enabled=True)
    check_git_repo()

    _branch, remote, remote_branch = validate_branch()
    stashed = stash_if_dirty()
    head_before = git("rev-parse", "HEAD")

    fetch_and_rebase(remote, remote_branch, stashed=stashed)
    update_submodules(stashed=stashed)
    unstash(stashed=stashed)
    print_summary(head_before.stdout, remote, remote_branch)
