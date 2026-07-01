"""Pull subcommand for gx."""

from __future__ import annotations

import typer
from nclutils import pp
from nclutils.git import ahead_behind, is_rebase_in_progress

from gx.lib.git import check_git_repo, git, set_dry_run
from gx.lib.options import (
    DRY_RUN_OPTION,
    FF_ONLY_OPTION,
    MERGE_OPTION,
    REBASE_OPTION,
    VERBOSE_OPTION,
)
from gx.lib.sync import (
    SyncState,
    announce_push_hint,
    classify_sync_state,
    ensure_one_strategy_flag,
    print_pull_summary,
    reconcile_divergence,
    report_conflict,
    validate_branch,
)
from gx.lib.workspace import rollback, stash_if_dirty, unstash, update_submodules

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

app = typer.Typer(rich_markup_mode="rich", context_settings=CONTEXT_SETTINGS)


@app.callback(invoke_without_command=True)
def pull(
    ctx: typer.Context,  # noqa: ARG001
    verbose: int = VERBOSE_OPTION,
    dry_run: bool = DRY_RUN_OPTION,  # noqa: FBT001
    rebase: bool = REBASE_OPTION,  # noqa: FBT001
    merge: bool = MERGE_OPTION,  # noqa: FBT001
    ff_only: bool = FF_ONLY_OPTION,  # noqa: FBT001
) -> None:
    """Pull latest changes from the remote tracking branch.

    Fetches and rebases the current branch onto its upstream. Automatically handles uncommitted changes by stashing before the pull and restoring after. If the branch has diverged from its upstream, gx asks how to reconcile (rebase or merge), unless a strategy flag (--rebase/--merge/--ff-only) or the integrate.strategy config setting decides for you.

    [bold]What happens:[/bold]

    1. Stashes any uncommitted changes (including untracked files)
    2. Fetches from the remote
    3. Rebases onto the upstream branch, or reconciles a divergence
    4. Updates submodules if .gitmodules is present
    5. Restores stashed changes
    6. Prints a summary of new commits

    If a rebase or merge conflict occurs, gx leaves the operation in progress and prints resolution steps. Any changes it stashed are left in the stash, so restore them with 'git stash pop' after you resolve the conflict.

    [bold]Examples:[/bold]

      gx pull              Pull and rebase current branch
      gx pull --rebase     Reconcile a diverged branch by rebasing
      gx pull --merge      Reconcile a diverged branch with a merge commit
      gx pull -n           Preview what would happen
      gx pull -v           Pull with debug output
    """
    if verbose:
        pp.configure(verbosity=verbose)
    if dry_run:
        set_dry_run(enabled=True)
    check_git_repo()

    ensure_one_strategy_flag(rebase=rebase, merge=merge, ff_only=ff_only)

    branch, remote, remote_branch = validate_branch()
    upstream_ref = f"{remote}/{remote_branch}"
    stashed = stash_if_dirty()
    head_before = git("rev-parse", "HEAD")

    with pp.step(f"Fetch from {remote}"):
        result = git("fetch", remote)
        if not result.ok:
            pp.error(f"Failed to fetch from {remote}: {result.stderr}")
            rollback(stashed=stashed)

    ahead, behind = ahead_behind(branch, upstream_ref)
    state = classify_sync_state(ahead, behind)

    if state is SyncState.DIVERGED:
        reconcile_divergence(
            branch,
            upstream_ref,
            ahead,
            behind,
            rebase=rebase,
            merge=merge,
            ff_only=ff_only,
            stashed=stashed,
        )
    else:
        with pp.step(f"Pull with rebase from {upstream_ref}"):
            result = git("pull", "--rebase", remote, remote_branch)
            if not result.ok:
                if is_rebase_in_progress():
                    report_conflict("rebase")
                    if stashed:
                        pp.warning(
                            "Your local changes remain stashed. "
                            "Run 'git stash pop' after resolving the conflict."
                        )
                    rollback(stashed=False)
                else:
                    pp.error(f"Failed to pull from {upstream_ref}")
                    rollback(stashed=stashed)

    update_submodules(stashed=stashed)
    unstash(stashed=stashed)

    if state is SyncState.DIVERGED:
        announce_push_hint()

    print_pull_summary(head_before.stdout, remote, remote_branch)
