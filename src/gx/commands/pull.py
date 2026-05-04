"""Pull subcommand for gx."""

from __future__ import annotations

import typer
from nllog import configure

from gx.lib.git import check_git_repo, git, set_dry_run
from gx.lib.options import DRY_RUN_OPTION, VERBOSE_OPTION
from gx.lib.sync import fetch_and_rebase, print_pull_summary, validate_branch
from gx.lib.workspace import stash_if_dirty, unstash, update_submodules

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

app = typer.Typer(rich_markup_mode="rich", context_settings=CONTEXT_SETTINGS)


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
        configure(verbosity=verbose)
    if dry_run:
        set_dry_run(enabled=True)
    check_git_repo()

    _branch, remote, remote_branch = validate_branch()
    stashed = stash_if_dirty()
    head_before = git("rev-parse", "HEAD")

    fetch_and_rebase(remote, remote_branch, stashed=stashed)
    update_submodules(stashed=stashed)
    unstash(stashed=stashed)
    print_pull_summary(head_before.stdout, remote, remote_branch)
