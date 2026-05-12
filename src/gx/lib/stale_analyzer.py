"""Stale branch and worktree analysis for cleanup.

Provides StaleAnalyzer which identifies branches and worktrees eligible for
cleanup based on merge status, upstream deletion, or emptiness. Used by the
clean command.

Usage:
    from gx.lib.stale_analyzer import CleanCandidate, StaleAnalyzer

    analyzer = StaleAnalyzer(protected=frozenset({"main"}), force=False)
    wt_candidates, br_candidates, skipped = analyzer.analyze()
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from nclutils.git import (
    all_local_branches,
    gone_branches,
    is_dirty,
    is_empty_branch,
    merged_branches,
    tracking_branch,
)

from gx.lib.branch import default_branch
from gx.lib.worktree import list_worktrees

if TYPE_CHECKING:
    from gx.constants import StaleReason
    from gx.lib.worktree import WorktreeInfo


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


def _classify_stale(*, is_gone: bool, is_merged: bool, is_empty_branch: bool) -> StaleReason | None:
    """Determine why a branch is stale based on three status flags.

    Priority: gone > merged > empty. Returns None if none apply.
    """
    if is_gone:
        return "gone"
    if is_merged:
        return "merged"
    if is_empty_branch:
        return "empty"
    return None


class StaleAnalyzer:
    """Identify stale branches and worktrees eligible for cleanup.

    Analyzes local branches and worktrees to find those that are merged, gone
    (upstream deleted), or empty (zero commits ahead of default branch). Respects
    protected branch names and dirty worktree status.

    Args:
        protected: Branch names that must never be cleaned.
        force: If True, include dirty worktrees as candidates instead of skipping them.
    """

    def __init__(self, protected: frozenset[str], *, force: bool = False) -> None:
        self.protected = protected
        self.force = force

    def analyze(
        self,
    ) -> tuple[list[CleanCandidate], list[CleanCandidate], list[CleanCandidate]]:
        """Run full analysis and return stale worktrees, branches, and skipped items.

        Returns:
            A 3-tuple of (worktree candidates, branch candidates, skipped dirty worktrees).
        """
        wt_candidates, wt_skipped = self._find_stale_worktrees()
        worktree_branch_names = {c.branch for c in wt_candidates} | {c.branch for c in wt_skipped}
        br_candidates = self._find_stale_branches(worktree_branch_names)
        return wt_candidates, br_candidates, wt_skipped

    def _find_stale_worktrees(
        self,
    ) -> tuple[list[CleanCandidate], list[CleanCandidate]]:
        """Identify stale worktrees for cleanup.

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

            if wt.branch in self.protected:
                continue

            reason = _classify_stale(
                is_gone=wt.is_gone, is_merged=wt.is_merged, is_empty_branch=wt.is_empty
            )
            if reason is None:
                continue

            if reason != "gone" and tracking_branch(wt.branch) is None:
                continue

            candidate = CleanCandidate(branch=wt.branch, reason=reason, worktree=wt)

            if is_dirty(cwd=wt.path) and not self.force:
                skipped.append(candidate)
            else:
                candidates.append(candidate)

        return candidates, skipped

    def _find_stale_branches(self, worktree_branches: set[str]) -> list[CleanCandidate]:
        """Identify stale standalone branches (not tied to a worktree).

        Args:
            worktree_branches: Branches already covered by stale worktree candidates.
        """
        target = default_branch()
        merged = merged_branches(target)
        gone = gone_branches()

        all_branches = all_local_branches()
        candidates: list[CleanCandidate] = []

        for branch in sorted(all_branches):
            if branch in self.protected or branch in worktree_branches:
                continue

            reason = _classify_stale(
                is_gone=branch in gone,
                is_merged=branch in merged,
                is_empty_branch=branch not in gone
                and branch not in merged
                and is_empty_branch(branch, target),
            )
            if reason is None:
                continue

            if reason != "gone" and tracking_branch(branch) is None:
                continue

            candidates.append(CleanCandidate(branch=branch, reason=reason))

        return candidates
