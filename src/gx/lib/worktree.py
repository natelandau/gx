"""Worktree management utilities for creating, listing, and removing git worktrees.

Provides enriched worktree information that includes branch status (merged, gone,
empty) for use by cleanup commands.

Usage in commands:
    from gx.lib.worktree import list_worktrees, create_worktree, remove_worktree

    for wt in list_worktrees():
        if wt.is_gone and not wt.is_main:
            remove_worktree(wt.path)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gx.lib.branch import default_branch, gone_branches, is_empty, merged_branches
from gx.lib.git import GitResult, git


@dataclass(frozen=True)
class WorktreeInfo:
    """Information about a git worktree, enriched with branch status.

    The is_main worktree (the original checkout) is never a cleanup candidate
    regardless of other status flags.
    """

    path: Path
    branch: str | None
    commit: str
    is_bare: bool
    is_main: bool
    is_merged: bool
    is_gone: bool
    is_empty: bool


def _parse_worktree_porcelain(output: str) -> list[dict[str, str]]:
    """Parse `git worktree list --porcelain` output into raw worktree dicts."""
    worktrees: list[dict[str, str]] = []
    current: dict[str, str] = {}

    for line in output.splitlines():
        if not line:
            if current:
                worktrees.append(current)
                current = {}
            continue

        if line.startswith("worktree "):
            current["path"] = line.removeprefix("worktree ")
        elif line.startswith("HEAD "):
            current["commit"] = line.removeprefix("HEAD ")
        elif line.startswith("branch "):
            ref = line.removeprefix("branch ")
            current["branch"] = ref.removeprefix("refs/heads/")
        elif line == "bare":
            current["bare"] = ""

    if current:
        worktrees.append(current)

    return worktrees


def list_worktrees() -> list[WorktreeInfo]:
    """List all worktrees with enriched branch status.

    Parses `git worktree list --porcelain` and enriches each entry with
    is_merged, is_gone, and is_empty flags by querying branch status.
    The first worktree in the list is marked as is_main.
    """
    result = git("worktree", "list", "--porcelain")
    if not result.success:
        return []

    raw_worktrees = _parse_worktree_porcelain(result.stdout)
    if not raw_worktrees:
        return []

    target = default_branch()
    merged = merged_branches(target)
    gone = gone_branches()
    worktrees: list[WorktreeInfo] = []

    for i, raw in enumerate(raw_worktrees):
        branch = raw.get("branch")

        if branch is not None and "bare" not in raw:
            wt_merged = branch in merged
            wt_gone = branch in gone
            wt_empty = is_empty(branch, target)
        else:
            wt_merged = wt_gone = wt_empty = False

        worktrees.append(
            WorktreeInfo(
                path=Path(raw["path"]),
                branch=branch,
                commit=raw.get("commit", ""),
                is_bare="bare" in raw,
                is_main=i == 0,
                is_merged=wt_merged,
                is_gone=wt_gone,
                is_empty=wt_empty,
            )
        )

    return worktrees


def create_worktree(path: Path, branch: str, start_point: str | None = None) -> GitResult:
    """Create a worktree with a new branch.

    Args:
        path: The filesystem path for the new worktree.
        branch: The name of the new branch to create.
        start_point: The commit/branch to base the new branch on. Defaults to HEAD.

    Returns:
        GitResult: The result of the git worktree add command.
    """
    args = ["worktree", "add", str(path), "-b", branch]
    if start_point is not None:
        args.append(start_point)
    return git(*args)


def remove_worktree(path: Path, *, force: bool = False) -> GitResult:
    """Remove a worktree.

    Args:
        path: The filesystem path of the worktree to remove.
        force: Pass --force to remove worktrees with uncommitted changes.

    Returns:
        GitResult: The result of the git worktree remove command.
    """
    args = ["worktree", "remove"]
    if force:
        args.append("--force")
    args.append(str(path))
    return git(*args)
