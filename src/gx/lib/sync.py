"""Pull-the-remote flow helpers.

Reusable primitives for fetching, rebasing, and reporting on remote-sync
operations against the current branch's upstream.
"""

from __future__ import annotations

import sys
from enum import Enum

import typer
from nclutils import pp
from nclutils.git import ahead_behind, current_branch, is_rebase_in_progress, tracking_branch
from rich.prompt import Prompt

from gx.lib.branch import is_remote_ref
from gx.lib.config import config
from gx.lib.display import commit_text
from gx.lib.git import git
from gx.lib.workspace import rollback


class SyncState(Enum):
    """Relationship of the current branch to a target ref."""

    UP_TO_DATE = "up_to_date"  # equal, or only ahead of the target
    FAST_FORWARD = "fast_forward"  # behind only, no local-only commits
    DIVERGED = "diverged"  # both ahead of and behind the target


class Strategy(Enum):
    """How to reconcile a diverged branch."""

    REBASE = "rebase"
    MERGE = "merge"
    FF_ONLY = "ff-only"


def classify_sync_state(ahead: int, behind: int) -> SyncState:
    """Classify how the current branch relates to a target from ahead/behind counts.

    Kept pure (no git calls) so callers can compute the counts once and both
    branch on the state and report the numbers.

    Args:
        ahead: Number of commits the current branch is ahead of the target.
        behind: Number of commits the current branch is behind the target.

    Returns:
        SyncState: The relationship between the current branch and target.
    """
    if behind == 0:
        return SyncState.UP_TO_DATE
    if ahead == 0:
        return SyncState.FAST_FORWARD
    return SyncState.DIVERGED


def resolve_strategy(
    *, rebase: bool, merge: bool, ff_only: bool, config_strategy: str
) -> Strategy | None:
    """Resolve the reconcile strategy by precedence: explicit flag, then config.

    Returns None only when nothing selects a strategy (no flag and config is
    "ask"), signaling the caller to prompt interactively.

    Args:
        rebase: Whether the rebase flag is set.
        merge: Whether the merge flag is set.
        ff_only: Whether the ff-only flag is set.
        config_strategy: The configured default strategy (rebase, merge, ff-only, or ask).

    Returns:
        Strategy | None: The selected strategy, or None to prompt the user.
    """
    if rebase:
        return Strategy.REBASE
    if merge:
        return Strategy.MERGE
    if ff_only:
        return Strategy.FF_ONLY
    if config_strategy != "ask":
        return Strategy(config_strategy)
    return None


def is_merge_in_progress() -> bool:
    """Return True if a merge is mid-flight (MERGE_HEAD exists)."""
    return git("rev-parse", "-q", "--verify", "MERGE_HEAD").ok


def preview_divergence(current: str, target_ref: str, ahead: int, behind: int) -> None:
    """Show the commits unique to each side so the user can choose informed.

    Args:
        current: The current branch name.
        target_ref: The ref being integrated in.
        ahead: Commits on current not on target_ref.
        behind: Commits on target_ref not on current.
    """
    pp.info(f"'{current}' and '{target_ref}' have diverged: {ahead} ahead, {behind} behind.")

    yours = git("log", "--oneline", f"{target_ref}..HEAD")
    if yours.ok and yours.stdout:
        pp.info("Your commits:", details=[commit_text(c) for c in yours.stdout.splitlines()])

    theirs = git("log", "--oneline", f"HEAD..{target_ref}")
    if theirs.ok and theirs.stdout:
        pp.info(
            f"Commits on {target_ref}:",
            details=[commit_text(c) for c in theirs.stdout.splitlines()],
        )


def report_conflict(operation: str) -> None:
    """Print numbered steps to resolve an in-progress rebase or merge conflict.

    Args:
        operation: Either "rebase" or "merge".
    """
    pp.error(
        f"{operation.capitalize()} conflict detected",
        details=[
            "1. Fix the conflicts in the affected files",
            "2. Stage the resolved files with 'git add'",
            f"3. Continue with 'git {operation} --continue'",
            f"Or abort with 'git {operation} --abort'",
        ],
    )


def fast_forward(target_ref: str, *, stashed: bool = False) -> None:
    """Fast-forward the current branch to target_ref.

    Args:
        target_ref: The ref to fast-forward to.
        stashed: Whether local changes were stashed, used for rollback.
    """
    with pp.step(f"Fast-forward to {target_ref}"):
        result = git("merge", "--ff-only", target_ref)
        if not result.ok:
            pp.error(f"Failed to fast-forward to {target_ref}: {result.stderr}")
            rollback(stashed=stashed)


def execute_reconcile(strategy: Strategy, target_ref: str, *, stashed: bool = False) -> None:
    """Run a rebase or merge, reporting conflicts and rolling back if needed.

    On conflict, the operation is left in progress so the user can resolve
    it. A stash is never popped mid-conflict (git would refuse); instead the
    user is warned the stash is still there so they can pop it themselves
    once the conflict is resolved.

    Args:
        strategy: Strategy.REBASE or Strategy.MERGE.
        target_ref: The ref to integrate in.
        stashed: Whether local changes were stashed, used for rollback.
    """
    if strategy is Strategy.REBASE:
        operation, args = "rebase", ("rebase", target_ref)
    else:
        operation, args = "merge", ("merge", "--no-edit", target_ref)

    with pp.step(f"{operation.capitalize()} onto {target_ref}"):
        result = git(*args)
        if not result.ok:
            if is_rebase_in_progress() or is_merge_in_progress():
                report_conflict(operation)
                if stashed:
                    pp.warning(
                        "Your local changes remain stashed. "
                        "Run 'git stash pop' after resolving the conflict."
                    )
                rollback(stashed=False)
            else:
                pp.error(f"Failed to {operation} onto {target_ref}: {result.stderr}")
                rollback(stashed=stashed)


def ensure_one_strategy_flag(*, rebase: bool, merge: bool, ff_only: bool) -> None:
    """Exit with an error if more than one strategy flag was supplied.

    Raises:
        typer.Exit: If two or more of the strategy flags are set.
    """
    if sum((rebase, merge, ff_only)) > 1:
        pp.error("Choose at most one of --rebase, --merge, --ff-only.")
        raise typer.Exit(1)


def needs_force_push(upstream_ref: str) -> bool:
    """Return True if a normal push would be rejected (upstream not an ancestor).

    Args:
        upstream_ref: The upstream tracking ref, e.g. "origin/feature".
    """
    return not git("merge-base", "--is-ancestor", upstream_ref, "HEAD").ok


def warn_if_stale_base(target_ref: str) -> None:
    """Warn when integrating a local branch that trails its own upstream.

    Skips remote refs (which are freshly fetched) and untracked local branches.

    Args:
        target_ref: The ref being integrated in.
    """
    if is_remote_ref(target_ref):  # a remote ref like origin/main is already fresh
        return
    tracking = tracking_branch(target_ref)
    if tracking is None:
        return
    upstream_ref = f"{tracking[0]}/{tracking[1]}"
    _, behind = ahead_behind(target_ref, upstream_ref)
    if behind > 0:
        pp.warning(
            f"'{target_ref}' is {behind} commit(s) behind {upstream_ref}; "
            "consider updating it first."
        )


def announce_push_hint() -> None:
    """Hint the user to push if the branch now leads its upstream."""
    branch = current_branch()
    if branch is None:
        return
    tracking = tracking_branch()
    if tracking is None:
        return
    upstream_ref = f"{tracking[0]}/{tracking[1]}"
    ahead, _ = ahead_behind(branch, upstream_ref)
    if ahead == 0:
        return
    if needs_force_push(upstream_ref):
        pp.warning("Your branch has diverged from its upstream. Push with: gx push -f")
    else:
        pp.info("Your branch is ahead of its upstream. Push with: gx push")


def prompt_strategy(*, stashed: bool = False) -> Strategy:
    """Ask whether to rebase or merge; exit cleanly when not interactive.

    Args:
        stashed: Whether local changes were stashed, used for rollback.

    Raises:
        typer.Exit: If stdin is not a TTY, since no choice can be gathered.
    """
    if not sys.stdin.isatty():
        pp.error(
            "Branch has diverged and no strategy was given.",
            details=[
                "Pass --rebase or --merge, or set integrate.strategy in your config.",
            ],
        )
        rollback(stashed=stashed)
    choice = Prompt.ask(
        "Branches have diverged. Reconcile by", choices=["rebase", "merge"], default="rebase"
    )
    return Strategy.REBASE if choice == "rebase" else Strategy.MERGE


def reconcile_divergence(  # noqa: PLR0913
    current: str,
    target_ref: str,
    ahead: int,
    behind: int,
    *,
    rebase: bool,
    merge: bool,
    ff_only: bool,
    stashed: bool = False,
) -> None:
    """Guide a diverged branch to reconciliation via the resolved strategy.

    Shows the diverged commits, resolves the strategy (flag, then config, then
    prompt), errors on an impossible ff-only, and executes the rebase or merge.

    Args:
        current: The current branch name.
        target_ref: The ref to integrate in.
        ahead: Commits on current not on target_ref.
        behind: Commits on target_ref not on current.
        rebase: The --rebase flag.
        merge: The --merge flag.
        ff_only: The --ff-only flag.
        stashed: Whether local changes were stashed, used for rollback.

    Raises:
        typer.Exit: On an impossible ff-only reconcile.
    """
    preview_divergence(current, target_ref, ahead, behind)

    strategy = resolve_strategy(
        rebase=rebase, merge=merge, ff_only=ff_only, config_strategy=config.integrate_strategy
    )
    if strategy is None:
        strategy = prompt_strategy(stashed=stashed)

    if strategy is Strategy.FF_ONLY:
        pp.error(f"Cannot fast-forward: '{current}' has diverged from {target_ref}.")
        rollback(stashed=stashed)

    execute_reconcile(strategy, target_ref, stashed=stashed)


def validate_branch() -> tuple[str, str, str]:
    """Validate branch state and return (branch, remote, remote_branch).

    Raises:
        typer.Exit: If the branch is detached or has no upstream configured.
    """
    branch = current_branch()
    if branch is None:
        pp.error("Cannot sync - HEAD is detached.")
        raise typer.Exit(1)

    tracking = tracking_branch()
    if tracking is None:
        pp.error(f"Branch '{branch}' has no upstream tracking branch configured.")
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
    with pp.step(f"Fetch from {remote}"):
        result = git("fetch", remote)
        if not result.ok:
            rollback(stashed=stashed)

    with pp.step(f"Pull with rebase from {remote}/{remote_branch}"):
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
                pp.error(f"Failed to pull from {remote}/{remote_branch}")
                rollback(stashed=stashed)


def print_pull_summary(head_before: str, remote: str, remote_branch: str) -> None:
    """Print a summary of the commits that arrived from the remote.

    Counts commits against the remote-tracking ref rather than HEAD. A
    reconciling rebase rewrites the SHAs of local commits, so a ``head_before..HEAD``
    range would wrongly report the user's own commits as newly pulled; measuring
    against ``remote/branch`` isolates only what actually came from the remote.

    Args:
        head_before: The commit SHA before the pull.
        remote: The remote name.
        remote_branch: The remote branch name.
    """
    upstream_ref = f"{remote}/{remote_branch}"
    remote_tip = git("rev-parse", upstream_ref)
    if head_before == remote_tip.stdout:
        pp.success("Already up to date")
        return

    log_result = git("log", "--oneline", f"{head_before}..{upstream_ref}")
    if log_result.ok and log_result.stdout:
        commits = log_result.stdout.splitlines()
        pp.success(
            f"Pull {len(commits)} new commit(s) from {upstream_ref}",
            details=[commit_text(c) for c in commits],
        )
    else:
        pp.success("Pull complete")
