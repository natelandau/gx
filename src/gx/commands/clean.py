"""Clean subcommand for gx."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

import typer
from rich.prompt import Confirm

from gx.lib.branch import (
    all_local_branches,
    current_branch,
    default_branch,
    gone_branches,
    has_upstream_branch,
    is_empty,
    merged_branches,
)
from gx.lib.config import config
from gx.lib.console import console, set_verbosity, step, warning
from gx.lib.git import check_git_repo, get_dry_run, git, set_dry_run
from gx.lib.options import DRY_RUN_OPTION, VERBOSE_OPTION
from gx.lib.worktree import WorktreeInfo, list_worktrees, remove_worktree

if TYPE_CHECKING:
    from pathlib import Path

    from gx.constants import StaleReason

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

app = typer.Typer(rich_markup_mode="rich", context_settings=CONTEXT_SETTINGS)


@dataclass(frozen=True)
class CleanCandidate:
    """A branch or worktree identified for cleanup.

    Attributes:
        branch: The branch name.
        reason: Why it's stale ('merged', 'gone', or 'empty').
        worktree: The WorktreeInfo if this candidate is a worktree, None for standalone branches.
    """

    branch: str
    reason: StaleReason
    worktree: WorktreeInfo | None = None


def _fetch() -> None:
    """Fetch from remote with prune to update tracking refs."""
    with step("Fetch with prune"):
        git("fetch", "--prune").raise_on_error()


def _stale_reason(
    branch: str,
    merged: frozenset[str],
    gone: frozenset[str],
    target: str,
) -> StaleReason | None:
    """Determine why a branch is stale, or None if it isn't.

    Args:
        branch: The branch name to check.
        merged: Pre-computed set of merged branches.
        gone: Pre-computed set of gone branches.
        target: The default branch to check emptiness against.
    """
    if branch in gone:
        return "gone"
    if branch in merged:
        return "merged"
    if is_empty(branch, target):
        return "empty"
    return None


def _is_worktree_dirty(path: Path) -> bool:
    """Check if a worktree has uncommitted changes.

    Uses subprocess directly because `git -C <path> status` puts "-C" as
    args[0], which the git() wrapper misclassifies as mutating in dry-run mode.
    Dirty checks are always read-only and must always execute.

    Args:
        path: The worktree directory path to inspect.

    Returns:
        True if there are uncommitted changes, False otherwise.
    """
    try:
        result = subprocess.run(  # noqa: S603
            ["git", "-C", str(path), "status", "--porcelain"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _worktree_stale_reason(wt: WorktreeInfo) -> StaleReason | None:
    """Determine why a worktree's branch is stale using its pre-computed flags.

    Args:
        wt: The worktree to evaluate.

    Returns:
        A reason string ('gone', 'merged', or 'empty'), or None if not stale.
    """
    if wt.is_gone:
        return "gone"
    if wt.is_merged:
        return "merged"
    if wt.is_empty:
        return "empty"
    return None


def _stale_worktrees(
    *,
    force: bool,
    protected: frozenset[str],
) -> tuple[list[CleanCandidate], list[CleanCandidate]]:
    """Identify stale worktrees for cleanup.

    Uses the pre-computed is_merged/is_gone/is_empty flags from list_worktrees()
    to avoid redundant subprocess calls.

    Args:
        force: If True, include dirty worktrees as candidates instead of skipping them.
        protected: Branch names that must never be cleaned.

    Returns:
        A tuple of (candidates, skipped) where skipped contains dirty worktrees
        when force=False.
    """
    worktrees = list_worktrees()
    if not worktrees:
        return [], []

    candidates: list[CleanCandidate] = []
    skipped: list[CleanCandidate] = []

    for wt in worktrees:
        if wt.is_main or wt.is_bare or wt.branch is None:
            continue

        if wt.branch in protected:
            continue

        reason = _worktree_stale_reason(wt)
        if reason is None:
            continue

        # gone implies its upstream is deleted; otherwise verify upstream exists
        if reason != "gone" and not has_upstream_branch(wt.branch):
            continue

        candidate = CleanCandidate(branch=wt.branch, reason=reason, worktree=wt)

        if _is_worktree_dirty(wt.path) and not force:
            skipped.append(candidate)
        else:
            candidates.append(candidate)

    return candidates, skipped


def _stale_branches(
    *, worktree_branches: set[str], protected: frozenset[str]
) -> list[CleanCandidate]:
    """Identify stale standalone branches (not tied to a worktree).

    Args:
        worktree_branches: Branches already covered by stale worktree candidates.
        protected: Branch names that must never be cleaned.
    """
    target = default_branch()
    merged = merged_branches(target)
    gone = gone_branches()

    all_branches = all_local_branches()
    candidates: list[CleanCandidate] = []

    for branch in sorted(all_branches):
        if branch in protected or branch in worktree_branches:
            continue

        reason = _stale_reason(branch, merged, gone, target)
        if reason is None:
            continue

        # Upstream requirement: gone implies upstream; otherwise check explicitly
        if reason != "gone" and not has_upstream_branch(branch):
            continue

        candidates.append(CleanCandidate(branch=branch, reason=reason))

    return candidates


def _display_candidates(
    worktree_candidates: list[CleanCandidate],
    branch_candidates: list[CleanCandidate],
    skipped: list[CleanCandidate],
) -> None:
    """Print the summary of items to be cleaned."""
    total = len(worktree_candidates) + len(branch_candidates)
    if total > 0:
        console.print(
            f"[step.success]✓[/] [step.message]Find {total} stale "
            f"item{'s' if total != 1 else ''}[/]"
        )
        if worktree_candidates:
            console.print("  [sub.pipe]│[/] Worktrees:")
            for c in worktree_candidates:
                if c.worktree is not None:
                    console.print(
                        f"  [sub.pipe]│[/]   {c.worktree.path}  (branch: {c.branch}, {c.reason})"
                    )
        if branch_candidates:
            console.print("  [sub.pipe]│[/] Branches:")
            for c in branch_candidates:
                console.print(f"  [sub.pipe]│[/]   {c.branch}  ({c.reason})")

    if skipped:
        warning("Skipped (dirty worktree, use --force):")
        for c in skipped:
            if c.worktree is not None:
                warning(f"  {c.worktree.path}  (branch: {c.branch}, {c.reason})", detail=True)


def _remove_candidates(
    worktree_candidates: list[CleanCandidate],
    branch_candidates: list[CleanCandidate],
    *,
    force: bool,
) -> tuple[int, int, int]:
    """Remove stale worktrees and branches.

    Returns:
        (worktrees_removed, branches_removed, failures) counts.
    """
    wt_removed = 0
    br_removed = 0
    failures = 0

    for c in worktree_candidates:
        if c.worktree is None:
            continue
        result = remove_worktree(c.worktree.path, force=force)
        if result.success:
            wt_removed += 1
            br_result = git("branch", "-D", c.branch)
            if br_result.success:
                br_removed += 1
            else:
                warning(
                    f"Worktree removed but failed to delete branch {c.branch}: {br_result.stderr}"
                )
                failures += 1
        else:
            warning(f"Failed to remove worktree {c.worktree.path}: {result.stderr}")
            failures += 1

    for c in branch_candidates:
        result = git("branch", "-D", c.branch)
        if result.success:
            br_removed += 1
        else:
            warning(f"Failed to delete branch {c.branch}: {result.stderr}")
            failures += 1

    return wt_removed, br_removed, failures


def _print_removal_summary(wt_removed: int, br_removed: int) -> None:
    """Print a human-readable summary of what was removed."""
    parts: list[str] = []
    if wt_removed:
        parts.append(f"{wt_removed} worktree{'s' if wt_removed != 1 else ''}")
    if br_removed:
        parts.append(f"{br_removed} branch{'es' if br_removed != 1 else ''}")

    if parts:
        verb = "Would remove" if get_dry_run() else "Remove"
        console.print(f"[step.success]✓[/] [step.message]{verb} {' and '.join(parts)}[/]")


FORCE_OPTION: bool = typer.Option(
    False,  # noqa: FBT003
    "--force",
    "-f",
    help="Include worktrees with uncommitted changes. Without this flag, dirty worktrees are skipped.",
)

YES_OPTION: bool = typer.Option(
    False,  # noqa: FBT003
    "--yes",
    "-y",
    help="Skip the confirmation prompt and delete immediately.",
)


@app.callback(invoke_without_command=True)
def clean(
    ctx: typer.Context,  # noqa: ARG001
    verbose: int = VERBOSE_OPTION,
    dry_run: bool = DRY_RUN_OPTION,  # noqa: FBT001
    force: bool = FORCE_OPTION,  # noqa: FBT001
    yes: bool = YES_OPTION,  # noqa: FBT001
) -> None:
    """Remove branches and worktrees that are no longer needed.

    Fetches with --prune to update remote tracking state, then identifies branches that are stale for any of these reasons:

    [bold]Stale branch criteria:[/bold]

    - [bold]merged[/bold] -- fully merged into the default branch
    - [bold]gone[/bold] -- upstream tracking branch was deleted on the remote
    - [bold]empty[/bold] -- zero commits ahead of the default branch

    The current branch, main, master, and develop are always protected from cleanup. Only branches with a configured upstream are considered (except for "gone" branches, where the upstream was already deleted).

    Worktrees are checked first, then standalone branches. Dirty worktrees are skipped unless --force is used. A confirmation prompt lists everything that will be removed before any deletion happens.

    [bold]Examples:[/bold]

      gx clean             Find and remove stale branches interactively
      gx clean -y          Remove stale branches without prompting
      gx clean -f          Include dirty worktrees in cleanup
      gx clean -n          Preview what would be removed
    """
    if verbose:
        set_verbosity(verbose)
    if dry_run:
        set_dry_run(enabled=True)
    check_git_repo()

    _fetch()

    cur = current_branch()
    protected = config.protected_branches | (frozenset({cur}) if cur else frozenset())

    wt_candidates, wt_skipped = _stale_worktrees(force=force, protected=protected)
    worktree_branch_names = {c.branch for c in wt_candidates} | {c.branch for c in wt_skipped}
    br_candidates = _stale_branches(worktree_branches=worktree_branch_names, protected=protected)

    if not wt_candidates and not br_candidates:
        if wt_skipped:
            _display_candidates([], [], wt_skipped)
        else:
            console.print("[step.success]✓[/] [step.message]Nothing to clean[/]")
        return

    _display_candidates(wt_candidates, br_candidates, wt_skipped)

    if get_dry_run():
        return

    if not yes and not Confirm.ask("Delete these items?", default=False):
        return

    wt_removed, br_removed, failures = _remove_candidates(wt_candidates, br_candidates, force=force)

    _print_removal_summary(wt_removed, br_removed)

    if failures and not wt_removed and not br_removed:
        raise typer.Exit(1)
