"""Branch query utilities for inspecting local and remote branch state.

Provides functions for querying branch names, tracking status, and merge state.
All git operations use the shared git() wrapper from gx.lib.git.

Usage in commands:
    from gx.lib.branch import current_branch, default_branch, is_merged

    branch = current_branch()
    if branch is None:
        error("Cannot operate in detached HEAD state")
        raise typer.Exit(1)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import typer

from gx.lib.console import error
from gx.lib.git import git

if TYPE_CHECKING:
    from pathlib import Path

_STASH_BRANCH_RE = re.compile(r"^stash@\{\d+\}: (?:WIP on|On) (.+?): ")
_AHEAD_BEHIND_PARTS = 2
_STATUS_CODE_MIN_LEN = 2


def current_branch() -> str | None:
    """Return the current branch name, or None if in detached HEAD state.

    Uses `git rev-parse --abbrev-ref HEAD` which returns "HEAD" when detached.
    Callers decide how to handle None (e.g., push/pull error out, clean ignores it).
    """
    result = git("rev-parse", "--abbrev-ref", "HEAD")
    if not result.success or result.stdout == "HEAD":
        return None

    return result.stdout


def default_branch() -> str:
    """Detect the repository's default branch.

    Try remote-based detection first via `git symbolic-ref refs/remotes/origin/HEAD`,
    then fall back to checking if `main` or `master` exists locally.

    Raises:
        typer.Exit: If no default branch can be determined.
    """
    result = git("symbolic-ref", "refs/remotes/origin/HEAD")
    if result.success:
        return result.stdout.rsplit("/", maxsplit=1)[-1]

    for candidate in ("main", "master"):
        result = git("rev-parse", "--verify", f"refs/heads/{candidate}")
        if result.success:
            return candidate

    error("Could not determine default branch.")
    raise typer.Exit(1)


def branch_exists(branch: str) -> bool:
    """Return whether a local branch with the given name exists.

    Args:
        branch: The full branch name to check.
    """
    result = git("rev-parse", "--verify", f"refs/heads/{branch}")
    return result.success


def has_upstream() -> bool:
    """Return whether the current branch has a remote tracking branch configured."""
    result = git("rev-parse", "--abbrev-ref", "@{upstream}")
    return result.success


def has_upstream_branch(branch: str) -> bool:
    """Return whether the given branch has a remote tracking branch configured.

    Unlike has_upstream() which only checks the current branch, this function
    can check any arbitrary local branch by querying git config directly.

    Args:
        branch: The branch name to check.
    """
    result = git("config", "--get", f"branch.{branch}.remote")
    return result.success


def tracking_branch() -> tuple[str, str] | None:
    """Return (remote, branch) for the current branch's upstream.

    Queries git config for the remote and merge ref of the current branch.
    Returns None if no upstream is configured.
    """
    branch = current_branch()
    if branch is None:
        return None

    remote_result = git("config", "--get", f"branch.{branch}.remote")
    if not remote_result.success:
        return None

    merge_result = git("config", "--get", f"branch.{branch}.merge")
    if not merge_result.success:
        return None

    upstream_branch = merge_result.stdout.removeprefix("refs/heads/")

    return (remote_result.stdout, upstream_branch)


def merged_branches(target: str | None = None) -> frozenset[str]:
    """Return the set of all local branches fully merged into the target branch.

    Prefer calling this once and checking membership, rather than calling
    is_merged() per branch, to avoid spawning one subprocess per branch.

    Args:
        target: The branch to check against. Defaults to the default branch.

    Returns:
        frozenset[str]: Branch names that are merged into target.
    """
    if target is None:
        target = default_branch()

    result = git("branch", "--merged", target)
    if not result.success:
        return frozenset()

    # Each line is "* branch", "+ branch" (worktree), or "  branch"; strip the marker prefix.
    return frozenset(b.lstrip("*+ ") for b in result.stdout.splitlines() if b.strip())


def gone_branches() -> frozenset[str]:
    """Return the set of all local branches whose upstream tracking ref is gone.

    Parses `git branch -vv` once to find all branches with the `[gone]` marker.
    Prefer calling this once and checking membership, rather than calling
    is_gone() per branch, to avoid spawning one subprocess per branch.

    Returns:
        frozenset[str]: Branch names whose remote tracking branch has been deleted.
    """
    result = git("branch", "-vv")
    if not result.success:
        return frozenset()

    gone: set[str] = set()
    for line in result.stdout.splitlines():
        if ": gone]" in line:
            gone.add(line.lstrip("*+ ").split()[0])

    return frozenset(gone)


def is_merged(branch: str, target: str | None = None) -> bool:
    """Return whether a branch is fully merged into the target branch.

    For bulk checks across many branches, call merged_branches() once instead
    to avoid spawning one subprocess per branch.

    Args:
        branch: The branch name to check.
        target: The branch to check against. Defaults to the default branch.
    """
    return branch in merged_branches(target)


def is_gone(branch: str) -> bool:
    """Return whether a branch's upstream tracking ref has been deleted on the remote.

    Parses `git branch -vv` output looking for the `[gone]` marker that indicates
    the remote tracking branch was deleted (typically after a PR merge). For bulk
    checks across many branches, call gone_branches() once instead.

    Args:
        branch: The branch name to check.
    """
    return branch in gone_branches()


def all_local_branches() -> frozenset[str]:
    """Return the set of all local branch names.

    Parses `git branch --list` output, stripping the leading marker characters.
    """
    result = git("branch", "--list")
    if not result.success:
        return frozenset()

    return frozenset(b.lstrip("*+ ").strip() for b in result.stdout.splitlines() if b.strip())


def is_empty(branch: str, target: str | None = None) -> bool:
    """Return whether a branch has zero commits ahead of the target branch.

    Uses `git rev-list --count` to check commits ahead only. A branch that is behind
    the target but has no new work of its own is still considered empty.

    Args:
        branch: The branch name to check.
        target: The branch to compare against. Defaults to the default branch.
    """
    if target is None:
        target = default_branch()

    result = git("rev-list", "--count", f"{target}..{branch}")
    if not result.success:
        return False

    return result.stdout == "0"


def stash_counts() -> dict[str, int]:
    """Return a mapping of branch name to number of stashes for that branch.

    Parses `git stash list` output. Stashes from detached HEAD (shown as
    "(no branch)") are excluded since they cannot be attributed to a branch.
    """
    result = git("stash", "list")
    if not result.success or not result.stdout:
        return {}

    counts: dict[str, int] = {}
    for line in result.stdout.splitlines():
        match = _STASH_BRANCH_RE.match(line)
        if match:
            branch = match.group(1)
            if branch != "(no branch)":
                counts[branch] = counts.get(branch, 0) + 1
    return counts


def ahead_behind(branch: str, target: str) -> tuple[int, int] | None:
    """Return (ahead, behind) commit counts between branch and target.

    Uses `git rev-list --left-right --count` to determine how many commits
    branch is ahead of and behind target.

    Args:
        branch: The branch to measure from.
        target: The branch to measure against.

    Returns:
        A (ahead, behind) tuple, or None if the comparison fails.
    """
    result = git("rev-list", "--left-right", "--count", f"{branch}...{target}")
    if not result.success:
        return None
    parts = result.stdout.split()
    if len(parts) != _AHEAD_BEHIND_PARTS:
        return None
    return (int(parts[0]), int(parts[1]))


def tracking_remote_ref(branch: str) -> str | None:
    """Return the full remote tracking ref for a branch (e.g., "origin/feat/login").

    Queries git config for the branch's remote and merge ref, then combines them
    into a ref that can be used with rev-list for ahead/behind comparison.

    Args:
        branch: The local branch name.

    Returns:
        The remote tracking ref string, or None if no upstream is configured.
    """
    remote_result = git("config", "--get", f"branch.{branch}.remote")
    if not remote_result.success:
        return None
    merge_result = git("config", "--get", f"branch.{branch}.merge")
    if not merge_result.success:
        return None
    upstream_branch = merge_result.stdout.removeprefix("refs/heads/")
    return f"{remote_result.stdout}/{upstream_branch}"


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
        ab = ahead_behind(branch, target)
        at_ahead, at_behind = ab or (0, 0)

    ar_ahead: int | None = None
    ar_behind: int | None = None
    remote_ref = tracking_remote_ref(branch)
    if remote_ref:
        remote_ab = ahead_behind(branch, remote_ref)
        if remote_ab:
            ar_ahead, ar_behind = remote_ab

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
    if result.success:
        return count_file_statuses(result.stdout)
    return (0, 0, 0, 0)


def collect_branch_data(*, show_all: bool, current_porcelain: str | None = None) -> list[BranchRow]:
    """Collect metrics for all local branches.

    Gathers ahead/behind counts relative to the default branch and any remote
    tracking ref, plus working-tree file counts for current and worktree branches.
    Inactive branches (all metrics zero) are excluded unless show_all is True.

    Args:
        show_all: When True, include branches with no activity.
        current_porcelain: Pre-fetched porcelain output for the current branch,
            to avoid a redundant git status call when the caller already has it.

    Returns:
        A list of BranchRow instances sorted with the current branch first.
    """
    from gx.lib.worktree import list_worktrees  # avoid circular import at module level

    cur = current_branch()
    target = default_branch()
    branches = all_local_branches()
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
