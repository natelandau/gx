"""Integrate subcommand for gx."""

from __future__ import annotations

import typer
from nclutils import pp
from nclutils.git import ahead_behind, current_branch, is_dirty, tracking_branch

from gx.lib.branch import is_remote_ref
from gx.lib.git import check_git_repo, git, raise_on_error, set_dry_run
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
    fast_forward,
    reconcile_divergence,
    warn_if_stale_base,
)

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

app = typer.Typer(rich_markup_mode="rich", context_settings=CONTEXT_SETTINGS)


REF_ARGUMENT: str | None = typer.Argument(
    None,
    help="Ref to integrate into the current branch. Defaults to the upstream.",
)


def _resolve_target(ref: str | None) -> tuple[str, str | None]:
    """Resolve the target ref and the remote to fetch, if any.

    Args:
        ref: The positional ref argument, or None to use the upstream.

    Returns:
        A (target_ref, fetch_remote) tuple. fetch_remote is None when the
        target is a local branch that needs no fetch.

    Raises:
        typer.Exit: When no ref is given and no upstream is configured.
    """
    if ref is not None:
        fetch_remote = ref.split("/", 1)[0] if is_remote_ref(ref) else None
        return ref, fetch_remote

    tracking = tracking_branch()
    if tracking is None:
        pp.info("Nothing to integrate: no upstream is configured.")
        raise typer.Exit(0)
    remote, remote_branch = tracking
    return f"{remote}/{remote_branch}", remote


@app.callback(invoke_without_command=True)
def integrate(
    ctx: typer.Context,  # noqa: ARG001
    ref: str | None = REF_ARGUMENT,
    verbose: int = VERBOSE_OPTION,
    dry_run: bool = DRY_RUN_OPTION,  # noqa: FBT001
    rebase: bool = REBASE_OPTION,  # noqa: FBT001
    merge: bool = MERGE_OPTION,  # noqa: FBT001
    ff_only: bool = FF_ONLY_OPTION,  # noqa: FBT001
) -> None:
    """Reconcile the current branch with another ref, guiding rebase vs merge.

    The current branch always receives. With no argument, reconciles against the
    upstream; given a ref (e.g. main or origin/main), brings that ref's commits
    into the current branch. On divergence you choose a rebase (linear history)
    or a merge commit, unless a strategy flag or the integrate.strategy config
    setting decides for you.

    [bold]Examples:[/bold]

      gx integrate              Reconcile with the upstream
      gx integrate main         Bring main into the current branch
      gx integrate main --merge Merge main in without prompting
      gx int main -n            Preview integrating main
    """
    if verbose:
        pp.configure(verbosity=verbose)
    if dry_run:
        set_dry_run(enabled=True)
    check_git_repo()

    ensure_one_strategy_flag(rebase=rebase, merge=merge, ff_only=ff_only)

    branch = current_branch()
    if branch is None:
        pp.error("Cannot integrate in detached HEAD state.")
        raise typer.Exit(1)

    if is_dirty():
        pp.error("Working tree has uncommitted changes. Commit or stash before integrating.")
        raise typer.Exit(1)

    target_ref, fetch_remote = _resolve_target(ref)

    if fetch_remote is not None:
        with pp.step(f"Fetch from {fetch_remote}"):
            raise_on_error(git("fetch", fetch_remote))

    if not git("rev-parse", "--verify", "--quiet", target_ref).ok:
        pp.error(f"Cannot resolve ref '{target_ref}'.")
        raise typer.Exit(1)

    warn_if_stale_base(target_ref)

    ahead, behind = ahead_behind(branch, target_ref)
    state = classify_sync_state(ahead, behind)

    if state is SyncState.UP_TO_DATE:
        if ahead > 0:
            pp.success(f"Already up to date with {target_ref}; {ahead} commit(s) ahead.")
            announce_push_hint()
        else:
            pp.success(f"Already up to date with {target_ref}.")
        return

    if state is SyncState.FAST_FORWARD:
        fast_forward(target_ref)
        pp.success(f"Fast-forwarded to {target_ref}.")
        announce_push_hint()
        return

    reconcile_divergence(
        branch, target_ref, ahead, behind, rebase=rebase, merge=merge, ff_only=ff_only
    )
    pp.success(f"Integrated {target_ref} into {branch}.")
    announce_push_hint()
