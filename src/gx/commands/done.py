"""Done subcommand for gx."""

from __future__ import annotations

import os
from pathlib import Path

import typer
from nllog import configure, error, step, warning
from rich.prompt import Confirm

from gx.lib.branch import ahead_behind, current_branch, default_branch, is_gone, is_merged
from gx.lib.git import check_git_repo, git, set_dry_run
from gx.lib.github import pr_state
from gx.lib.options import DRY_RUN_OPTION, VERBOSE_OPTION
from gx.lib.sync import fetch_and_rebase, print_pull_summary, validate_branch
from gx.lib.workspace import is_dirty, stash_if_dirty, unstash, update_submodules
from gx.lib.worktree import WorktreeInfo, list_worktrees, remove_worktree

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

app = typer.Typer(rich_markup_mode="rich", context_settings=CONTEXT_SETTINGS)


FORCE_OPTION: bool = typer.Option(
    False,  # noqa: FBT003
    "--force",
    "-f",
    help="Skip the merge-verification check and delete the branch unconditionally.",
)


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
    print_pull_summary(head_before.stdout, remote, remote_branch)


def _delete_branch(branch: str) -> None:
    """Delete a local branch, warning on failure instead of erroring.

    Args:
        branch: The branch name to delete.
    """
    with step(f"Delete branch {branch}"):
        result = git("branch", "-D", branch)
        if not result.success:
            warning(f"Could not delete branch {branch}: {result.stderr}")


def _verify_merged(branch: str, target: str) -> None:
    """Confirm the branch has been merged before destructive cleanup, prompting if unsure.

    Checks signals in order of authority: gh PR state, then upstream deletion, then a
    traditional merge commit. If no signal confirms the merge, prompt the user with a
    platform-agnostic message showing the count of commits not in target.

    Args:
        branch: The current feature branch about to be deleted.
        target: The default branch (e.g., main) being compared against.

    Raises:
        typer.Exit: When the user declines the prompt.
    """
    state = pr_state(branch)
    if state == "MERGED":
        return

    # gh is authoritative for GitHub remotes - only fall through to git signals when gh
    # provided no answer (no gh installed, non-GitHub remote, or no PR for branch). The
    # fetch lives in this branch because is_gone/is_merged need fresh refs; pr_state
    # doesn't, and a successful gh check would make the fetch wasted work.
    if state is None:
        with step("Refresh remote refs"):
            git("fetch", "--prune")
        if is_gone(branch) or is_merged(branch, target):
            return

    ab = ahead_behind(branch, target)
    n_ahead = ab[0] if ab else 0
    suffix = "" if n_ahead == 1 else "s"
    message = (
        f"Branch '{branch}' has {n_ahead} commit{suffix} not in {target} and no merge "
        f"was detected. Delete anyway?"
    )

    if not Confirm.ask(message, default=False):
        error("Aborted by user.")
        raise typer.Exit(1)


@app.callback(invoke_without_command=True)
def done(
    ctx: typer.Context,  # noqa: ARG001
    verbose: int = VERBOSE_OPTION,
    dry_run: bool = DRY_RUN_OPTION,  # noqa: FBT001
    force: bool = FORCE_OPTION,  # noqa: FBT001
) -> None:
    """Switch back to the default branch, pull, and clean up.

    Use after your PR has been merged on the remote. Checks out the default branch, pulls the latest changes, and deletes the feature branch you were on.

    Before deleting, verifies the branch was actually merged using (in order) the gh PR state, an upstream-deleted (`[gone]`) marker, or a traditional merge commit. If no signal confirms the merge, you'll be prompted before deletion. Pass --force to skip the check.

    If run from a worktree, removes the worktree first, then switches to the main working directory to pull and clean up. Prints a cd command since your shell will still be in the deleted directory.

    [bold]What happens:[/bold]

    1. Verifies the branch was merged (or prompts)
    2. Checks out the default branch (e.g. main)
    3. Pulls latest changes with rebase
    4. Deletes the feature branch

    [bold]Examples:[/bold]

      gx done              Clean up after a merged PR
      gx done -f           Skip the merge check (use with care)
      gx done -n           Preview what would happen
      gx done -v           Run with debug output
    """
    if verbose:
        configure(verbosity=verbose)
    if dry_run:
        set_dry_run(enabled=True)
    check_git_repo()

    branch = current_branch()
    if branch is None:
        error("Cannot run done in detached HEAD state.")
        raise typer.Exit(1)

    target = default_branch()
    if branch == target:
        error(
            "Already on the default branch - nothing to do.",
            details=["To clean up merged branches/worktrees, run: gx pull && gx clean"],
        )
        raise typer.Exit(1)

    worktree, main_path = _detect_worktree_context()

    # Dirty-worktree check runs before merge verification and is NOT bypassed by --force,
    # since losing uncommitted changes is a separate class of footgun from deleting a
    # not-yet-merged branch.
    if worktree is not None and is_dirty():
        error("Worktree has uncommitted changes. Commit or stash before running done.")
        raise typer.Exit(1)

    if not force:
        _verify_merged(branch, target)

    if worktree is not None:
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
        _checkout_and_pull(target)
        _delete_branch(branch)
