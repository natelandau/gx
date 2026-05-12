"""Working-tree state and stash management helpers.

Reusable primitives for any command that needs to inspect or mutate the working
tree (dirty checks, submodule presence, rebase state) or coordinate stash/unstash
flows around a potentially-failing git operation.
"""

from __future__ import annotations

import typer
from nclutils import pp
from nclutils.git import is_dirty

from gx.lib.git import git, raise_on_error, repo_root


def has_submodules() -> bool:
    """Return True if the repo has a .gitmodules file at its root."""
    return (repo_root() / ".gitmodules").exists()


def rollback(*, stashed: bool) -> None:
    """Unstash if we stashed earlier, then exit."""
    if stashed:
        pp.warning("Restoring stashed changes...")
        git("stash", "pop")
    raise typer.Exit(1)


def stash_if_dirty() -> bool:
    """Stash uncommitted changes if the working tree is dirty.

    Returns:
        True if changes were stashed, False otherwise.
    """
    if not is_dirty():
        return False

    with pp.step("Stash local changes"):
        raise_on_error(git("stash", "--include-untracked"))
    return True


def update_submodules(*, stashed: bool) -> None:
    """Update submodules if a .gitmodules file is present.

    Args:
        stashed: Whether local changes were stashed, used for rollback.
    """
    if not has_submodules():
        return

    with pp.step("Update submodules"):
        result = git("submodule", "update", "--init", "--recursive")
        if not result.ok:
            pp.error("Failed to update submodules")
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

    with pp.step("Restore stashed changes"):
        result = git("stash", "pop")
        if not result.ok:
            pp.warning(
                "Could not cleanly restore stashed changes",
                details=[
                    "The git operation succeeded, but stashed changes conflict with the updated code",
                    "Run 'git stash show' to see stashed changes",
                    "Run 'git stash pop' to try again, or 'git stash drop' to discard",
                ],
            )
            raise typer.Exit(1)
