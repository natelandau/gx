"""Branch query utilities for inspecting local and remote branch state.

The basic branch primitives (current_branch, branch_exists, tracking_branch,
gone_branches, all_local_branches, merged_branches, ahead_behind, stash_counts)
come from :mod:`nclutils.git`. This module adds gx-specific composites:

- :func:`default_branch` — origin/HEAD with a local main/master fallback and
  typer.Exit on failure.
- :func:`collect_branch_data` — the per-branch row collection used by the
  status and info dashboards.
- :func:`count_file_statuses` — bucketing of ``git status --porcelain`` XY codes.
"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING

import typer
from nclutils import pp
from nclutils.git import (
    ahead_behind,
    all_local_branches,
    branch_exists,
    current_branch,
    stash_counts,
    tracking_branch,
)
from nclutils.git import default_branch as nc_default_branch
from nclutils.sh import ShellCommandError

from gx.lib.git import git

if TYPE_CHECKING:
    from pathlib import Path

_STATUS_CODE_MIN_LEN = 2


def default_branch() -> str:
    """Detect the repository's default branch.

    Ask nclutils for the remote-advertised default first, then fall back to a
    local main/master probe so repos without ``origin/HEAD`` set still work.
    Finally fall back to the branch HEAD points at, which covers brand-new repos
    with an unborn HEAD (no commits yet, so ``refs/heads/main`` does not exist)
    and repos whose default branch has a non-standard name.

    Raises:
        typer.Exit: If no default branch can be determined.
    """
    name = nc_default_branch()
    if name:
        return name

    for candidate in ("main", "master"):
        if branch_exists(candidate):
            return candidate

    cur = current_branch()
    if cur:
        return cur

    pp.error("Could not determine default branch.")
    raise typer.Exit(1)


def has_commits() -> bool:
    """Report whether the repository has at least one commit.

    A freshly ``git init``'d repo has an unborn HEAD: the checked-out branch ref
    exists in name only and resolves to no commit object. Callers use this to
    skip commit-dependent queries (``git branch --merged``, ahead/behind counts)
    that abort with "malformed object name" against such a ref.
    """
    return git("rev-parse", "--verify", "--quiet", "HEAD").ok


@dataclass(frozen=True)
class BranchRow:
    """Data for one branch in the status display."""

    branch: str
    target: str
    ahead_target: int
    behind_target: int
    ahead_remote: int | None
    behind_remote: int | None
    staged: int
    modified: int
    unmerged: int
    untracked: int
    stashes: int
    is_current: bool
    is_worktree: bool
    worktree_path: Path | None
    tracking_ref: str | None

    @property
    def is_active(self) -> bool:
        """Return True if this branch has any non-zero metric."""
        return (
            self.ahead_target != 0
            or self.behind_target != 0
            or (self.ahead_remote is not None and self.ahead_remote != 0)
            or (self.behind_remote is not None and self.behind_remote != 0)
            or self.staged != 0
            or self.modified != 0
            or self.unmerged != 0
            or self.untracked != 0
            or self.stashes != 0
        )


def count_file_statuses(porcelain_output: str) -> tuple[int, int, int, int]:
    """Count staged, modified, unmerged, and untracked files from porcelain output.

    Parses the two-character XY codes from `git status --porcelain` to bucket
    each file into one of four categories for dashboard display.

    Args:
        porcelain_output: Raw stdout from `git status --porcelain`.

    Returns:
        A (staged, modified, unmerged, untracked) count tuple.
    """
    staged = modified = unmerged = untracked = 0
    if not porcelain_output:
        return (0, 0, 0, 0)
    for line in porcelain_output.splitlines():
        if len(line) < _STATUS_CODE_MIN_LEN:
            continue
        x, y = line[0], line[1]
        if x == "?" and y == "?":
            untracked += 1
        elif x == "U" or y == "U" or (x == "A" and y == "A") or (x == "D" and y == "D"):
            unmerged += 1
        else:
            if x not in (" ", "?"):
                staged += 1
            if y not in (" ", "?"):
                modified += 1
    return (staged, modified, unmerged, untracked)


def branch_remote_counts(
    branch: str, target: str
) -> tuple[int, int, int | None, int | None, str | None]:
    """Return ahead/behind counts for a branch relative to target and remote.

    Args:
        branch: The local branch name.
        target: The default branch to compare against.

    Returns:
        A (ahead_target, behind_target, ahead_remote, behind_remote, tracking_ref) tuple,
        where remote values and tracking_ref are None when no tracking ref is configured.
    """
    if branch == target:
        at_ahead, at_behind = 0, 0
    else:
        at_ahead, at_behind = ahead_behind(branch, target)

    ar_ahead: int | None = None
    ar_behind: int | None = None
    tracking = tracking_branch(branch)
    remote_ref = f"{tracking[0]}/{tracking[1]}" if tracking else None
    if remote_ref:
        with suppress(ShellCommandError):
            ar_ahead, ar_behind = ahead_behind(branch, remote_ref)

    return (at_ahead, at_behind, ar_ahead, ar_behind, remote_ref)


def branch_file_statuses(*, is_current: bool, wt_path: Path | None) -> tuple[int, int, int, int]:
    """Fetch and count working-tree file statuses for a branch.

    Only queries git for branches that are currently checked out (current branch
    or branches with a worktree), since other branches have no working tree state.

    Args:
        is_current: Whether this is the currently active branch.
        wt_path: Path to the branch's worktree, if any.

    Returns:
        A (staged, modified, unmerged, untracked) count tuple.
    """
    if not is_current and not wt_path:
        return (0, 0, 0, 0)

    cwd = None if is_current else wt_path
    result = git("status", "--porcelain", cwd=cwd)
    if result.ok:
        return count_file_statuses(result.stdout)
    return (0, 0, 0, 0)


def collect_branch_data(
    *,
    show_all: bool,
    current_porcelain: str | None = None,
    stashes: dict[str, int] | None = None,
) -> list[BranchRow]:
    """Collect metrics for all local branches.

    Gathers ahead/behind counts relative to the default branch and any remote
    tracking ref, plus working-tree file counts for current and worktree branches.
    Inactive branches (all metrics zero) are excluded unless show_all is True.

    Args:
        show_all: When True, include branches with no activity.
        current_porcelain: Pre-fetched porcelain output for the current branch,
            to avoid a redundant git status call when the caller already has it.
        stashes: Pre-fetched stash counts per branch. If None, fetched internally.

    Returns:
        A list of BranchRow instances sorted with the current branch first.
    """
    from gx.lib.worktree import list_worktrees  # avoid circular import at module level

    cur = current_branch()
    target = default_branch()
    branches = all_local_branches()
    if stashes is None:
        stashes = stash_counts()
    worktrees = list_worktrees()

    wt_map: dict[str, Path] = {}
    for wt in worktrees:
        if wt.branch and not wt.is_main:
            wt_map[wt.branch] = wt.path
    for wt in worktrees:
        if wt.is_main and wt.branch:
            wt_map[wt.branch] = wt.path
            break

    rows: list[BranchRow] = []
    for branch in sorted(branches):
        is_current = branch == cur
        at_ahead, at_behind, ar_ahead, ar_behind, remote_ref = branch_remote_counts(branch, target)

        wt_path = wt_map.get(branch)
        if is_current and current_porcelain is not None:
            staged, modified, unmerged, untracked = count_file_statuses(current_porcelain)
        else:
            staged, modified, unmerged, untracked = branch_file_statuses(
                is_current=is_current, wt_path=wt_path
            )

        row = BranchRow(
            branch=branch,
            target=target,
            ahead_target=at_ahead,
            behind_target=at_behind,
            ahead_remote=ar_ahead,
            behind_remote=ar_behind,
            staged=staged,
            modified=modified,
            unmerged=unmerged,
            untracked=untracked,
            stashes=stashes.get(branch, 0),
            is_current=is_current,
            is_worktree=wt_path is not None and not is_current,
            worktree_path=wt_path if not is_current else None,
            tracking_ref=remote_ref,
        )

        if show_all or row.is_active or is_current:
            rows.append(row)

    rows.sort(key=lambda r: (not r.is_current, r.branch))
    return rows
