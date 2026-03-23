"""Clean subcommand for gx."""

from __future__ import annotations

import typer
from rich.prompt import Confirm

from gx.lib.branch import current_branch
from gx.lib.config import config
from gx.lib.console import set_verbosity, step, step_result, warning
from gx.lib.git import check_git_repo, get_dry_run, git, set_dry_run
from gx.lib.options import DRY_RUN_OPTION, VERBOSE_OPTION
from gx.lib.stale_analyzer import CleanCandidate, StaleAnalyzer
from gx.lib.worktree import remove_worktree

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

app = typer.Typer(rich_markup_mode="rich", context_settings=CONTEXT_SETTINGS)


def _fetch() -> None:
    """Fetch from remote with prune to update tracking refs."""
    with step("Fetch with prune"):
        git("fetch", "--prune").raise_on_error()


def _display_candidates(
    worktree_candidates: list[CleanCandidate],
    branch_candidates: list[CleanCandidate],
    skipped: list[CleanCandidate],
) -> None:
    """Print the summary of items to be cleaned."""
    total = len(worktree_candidates) + len(branch_candidates)
    if total > 0:
        subs: list[str] = []
        if worktree_candidates:
            subs.append("Worktrees:")
            subs.extend(
                f"  {c.worktree.path}  (branch: {c.branch}, {c.reason})"
                for c in worktree_candidates
                if c.worktree is not None
            )
        if branch_candidates:
            subs.append("Branches:")
            subs.extend(f"  {c.branch}  ({c.reason})" for c in branch_candidates)
        step_result(f"Find {total} stale item{'s' if total != 1 else ''}", subs=subs)

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
        step_result(f"{verb} {' and '.join(parts)}")


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

    analyzer = StaleAnalyzer(protected, force=force)
    wt_candidates, br_candidates, wt_skipped = analyzer.analyze()

    if not wt_candidates and not br_candidates:
        if wt_skipped:
            _display_candidates([], [], wt_skipped)
        else:
            step_result("Nothing to clean")
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
