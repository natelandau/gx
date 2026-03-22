"""Done subcommand for gx."""

from __future__ import annotations

import os
from pathlib import Path

import typer

from gx.commands.pull import (
    fetch_and_rebase,
    is_dirty,
    print_summary,
    stash_if_dirty,
    unstash,
    update_submodules,
    validate_branch,
)
from gx.lib.branch import current_branch, default_branch
from gx.lib.console import error, set_verbosity, step, warning
from gx.lib.git import check_git_repo, git, set_dry_run
from gx.lib.options import DRY_RUN_OPTION, VERBOSE_OPTION
from gx.lib.worktree import WorktreeInfo, list_worktrees, remove_worktree

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

app = typer.Typer(rich_markup_mode="rich", context_settings=CONTEXT_SETTINGS)


def _detect_worktree_context() -> tuple[WorktreeInfo | None, Path | None]:
    """Detect if the current directory is a non-main worktree and find the main worktree.

    Returns:
        A tuple of (current_worktree, main_worktree_path). Both are None if not in a
        non-main worktree. main_worktree_path is None if no main worktree is found.
    """
    cwd = Path.cwd().resolve()
    worktrees = list_worktrees()

    current_wt: WorktreeInfo | None = None
    main_path: Path | None = None

    for wt in worktrees:
        if wt.is_main:
            main_path = wt.path
        elif not wt.is_bare and wt.path.resolve() == cwd:
            current_wt = wt

    return current_wt, main_path


def _checkout_and_pull(target_branch: str) -> None:
    """Check out the target branch and pull latest changes.

    Args:
        target_branch: The branch to check out (typically the default branch).
    """
    with step(f"Switch to {target_branch}"):
        result = git("checkout", target_branch)
        if not result.success:
            error(f"Failed to checkout {target_branch}: {result.stderr}")
            raise typer.Exit(1)

    _branch, remote, remote_branch = validate_branch()
    stashed = stash_if_dirty()
    head_before = git("rev-parse", "HEAD")

    fetch_and_rebase(remote, remote_branch, stashed=stashed)
    update_submodules(stashed=stashed)
    unstash(stashed=stashed)
    print_summary(head_before.stdout, remote, remote_branch)


def _delete_branch(branch: str) -> None:
    """Delete a local branch, warning on failure instead of erroring.

    Args:
        branch: The branch name to delete.
    """
    with step(f"Delete branch {branch}"):
        result = git("branch", "-D", branch)
        if not result.success:
            warning(f"Could not delete branch {branch}: {result.stderr}")


@app.callback(invoke_without_command=True)
def done(
    ctx: typer.Context,  # noqa: ARG001
    verbose: int = VERBOSE_OPTION,
    dry_run: bool = DRY_RUN_OPTION,  # noqa: FBT001
) -> None:
    """Switch back to the default branch, pull, and clean up.

    Use after your PR has been merged on the remote. Checks out the default branch, pulls the latest changes, and deletes the feature branch you were on.

    If run from a worktree, removes the worktree first, then switches to the main working directory to pull and clean up. Prints a cd command since your shell will still be in the deleted directory.

    [bold]What happens:[/bold]

    1. Checks out the default branch (e.g. main)
    2. Pulls latest changes with rebase
    3. Deletes the feature branch

    [bold]Examples:[/bold]

      gx done              Clean up after a merged PR
      gx done -n           Preview what would happen
      gx done -v           Run with debug output
    """
    if verbose:
        set_verbosity(verbose)
    if dry_run:
        set_dry_run(enabled=True)
    check_git_repo()

    branch = current_branch()
    if branch is None:
        error("Cannot run done in detached HEAD state.")
        raise typer.Exit(1)

    target = default_branch()
    if branch == target:
        error("Already on the default branch — nothing to do.")
        raise typer.Exit(1)

    worktree, main_path = _detect_worktree_context()

    if worktree is not None:
        # Mode 2: in a worktree
        if is_dirty():
            error("Worktree has uncommitted changes. Commit or stash before running done.")
            raise typer.Exit(1)

        if main_path is None:
            error("Could not find main worktree.")
            raise typer.Exit(1)

        # Must leave the worktree directory before removing it
        os.chdir(main_path)

        with step(f"Remove worktree {worktree.path}"):
            result = remove_worktree(worktree.path)
            if not result.success:
                error(f"Failed to remove worktree {worktree.path}: {result.stderr}")
                raise typer.Exit(1)

        _checkout_and_pull(target)
        _delete_branch(branch)
        warning(f"Your previous working directory was removed. Run: cd {main_path}")
    else:
        # Mode 1: on a feature branch
        _checkout_and_pull(target)
        _delete_branch(branch)
