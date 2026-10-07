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
from typing import TYPE_CHECKING

from nclutils.git import gone_branches, is_empty_branch, merged_branches

from gx.lib.branch import default_branch, has_commits
from gx.lib.git import git

if TYPE_CHECKING:
    from nclutils.sh import CompletedCommand


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
    is_locked: bool = False


def parse_worktree_porcelain(output: str) -> list[dict[str, str]]:
    """Parse `git worktree list --porcelain` output into raw worktree dicts.

    Args:
        output: Raw porcelain text.

    Returns:
        One dict per worktree with `path`, plus `commit`, `branch`, `bare`, `detached`,
        `locked`, and `prunable` when git reports them.
    """
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
        else:
            flag, _, reason = line.partition(" ")
            if flag in {"bare", "detached", "locked", "prunable"}:
                current[flag] = reason

    if current:
        worktrees.append(current)

    return worktrees


def _is_missing(raw: dict[str, str]) -> bool:
    """Report whether a parsed worktree entry has no folder to run git in.

    Args:
        raw: One entry from `parse_worktree_porcelain`.

    Returns:
        bool: True when git reports the entry as prunable or its folder does not exist.
    """
    return "prunable" in raw or not Path(raw["path"]).exists()


def read_worktree_entries() -> list[dict[str, str]]:
    """Read every worktree registration once, for callers that need several views of it.

    Returns:
        list[dict[str, str]]: Parsed `git worktree list --porcelain` entries, empty when git fails.
    """
    result = git("worktree", "list", "--porcelain")
    return parse_worktree_porcelain(result.stdout) if result.ok else []


def list_worktrees(entries: list[dict[str, str]] | None = None) -> list[WorktreeInfo]:
    """List all worktrees with enriched branch status.

    Parses `git worktree list --porcelain` and enriches each entry with
    is_merged, is_gone, and is_empty flags by querying branch status.
    The first worktree in the list is marked as is_main. Worktrees git reports as
    prunable, or whose directory no longer exists, are left out because running
    git inside them fails.

    Args:
        entries: Registrations already read with `read_worktree_entries`, or None to read them.
    """
    raw_worktrees = entries if entries is not None else read_worktree_entries()
    if not raw_worktrees:
        return []

    # An unborn HEAD has no commit object, so merged/gone/empty queries against
    # it abort with "malformed object name". Skip enrichment entirely in that case.
    enrich = has_commits()
    target = default_branch() if enrich else ""
    merged = merged_branches(target) if enrich else []
    gone = gone_branches() if enrich else []
    worktrees: list[WorktreeInfo] = []

    for i, raw in enumerate(raw_worktrees):
        if _is_missing(raw):
            continue
        branch = raw.get("branch")

        if enrich and branch is not None and "bare" not in raw:
            wt_merged = branch in merged
            wt_gone = branch in gone
            wt_empty = is_empty_branch(branch, target)
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
                is_locked="locked" in raw,
            )
        )

    return worktrees


def missing_worktrees(entries: list[dict[str, str]] | None = None) -> list[Path]:
    """List registered worktrees whose folder is gone and that `git worktree prune` removes.

    `list_worktrees` leaves these out, so callers use this to tell the user that
    `git worktree prune` has something to clean. Locked entries are left out because
    prune keeps them.

    Args:
        entries: Registrations already read with `read_worktree_entries`, or None to read them.

    Returns:
        list[Path]: Paths of the missing worktrees, empty when git fails.
    """
    raw_worktrees = entries if entries is not None else read_worktree_entries()
    return [Path(raw["path"]) for raw in raw_worktrees if _is_missing(raw) and "locked" not in raw]


def checked_out_branches(entries: list[dict[str, str]] | None = None) -> frozenset[str]:
    """List branches git refuses to delete because a worktree has them checked out.

    Prunable entries are left out, since `git worktree prune` releases their branches.
    Locked entries count even when their folder is gone, because prune keeps them.

    Args:
        entries: Registrations already read with `read_worktree_entries`, or None to read them.

    Returns:
        frozenset[str]: Branch names, empty when git fails.
    """
    raw_worktrees = entries if entries is not None else read_worktree_entries()
    return frozenset(
        raw["branch"] for raw in raw_worktrees if "branch" in raw and "prunable" not in raw
    )


def create_worktree(path: Path, branch: str, start_point: str | None = None) -> CompletedCommand:
    """Create a worktree with a new branch.

    Args:
        path: The filesystem path for the new worktree.
        branch: The name of the new branch to create.
        start_point: The commit/branch to base the new branch on. Defaults to HEAD.
    """
    # A target path still registered to a deleted folder makes `worktree add` refuse.
    git("worktree", "prune")
    args = ["worktree", "add", "--no-track", "-b", branch, str(path)]
    if start_point is not None:
        args.append(start_point)
    return git(*args)


def remove_worktree(path: Path, *, force: bool = False) -> CompletedCommand:
    """Remove a worktree.

    Args:
        path: The filesystem path of the worktree to remove.
        force: Pass --force to remove worktrees with uncommitted changes.
    """
    args = ["worktree", "remove"]
    if force:
        args.append("--force")
    args.append(str(path))
    return git(*args)
