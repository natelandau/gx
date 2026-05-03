"""Working-tree state and stash management helpers.

Reusable primitives for any command that needs to inspect or mutate the working
tree (dirty checks, submodule presence, rebase state) or coordinate stash/unstash
flows around a potentially-failing git operation.
"""

from __future__ import annotations

from pathlib import Path

import typer

from gx.lib.console import error, step, warning
from gx.lib.git import git


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
    """Restore stashed changes after a successful operation.

    Args:
        stashed: Whether changes were stashed before the operation.

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
