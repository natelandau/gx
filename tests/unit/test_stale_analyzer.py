"""Tests for StaleAnalyzer and stale reason helpers."""

from __future__ import annotations

from pathlib import Path

from gx.lib.config import config
from gx.lib.stale_analyzer import StaleAnalyzer, _stale_reason
from gx.lib.worktree import WorktreeInfo


def _worktree(
    path: str = "/repo/.worktrees/feat/1",
    branch: str | None = "feat/1",
    commit: str = "abc123",
    is_bare: bool = False,  # noqa: FBT002
    is_main: bool = False,  # noqa: FBT002
    is_merged: bool = False,  # noqa: FBT002
    is_gone: bool = False,  # noqa: FBT002
    is_empty: bool = False,  # noqa: FBT002
) -> WorktreeInfo:
    """Build a WorktreeInfo for testing."""
    return WorktreeInfo(
        path=Path(path),
        branch=branch,
        commit=commit,
        is_bare=is_bare,
        is_main=is_main,
        is_merged=is_merged,
        is_gone=is_gone,
        is_empty=is_empty,
    )


class TestStaleWorktrees:
    """Tests for StaleAnalyzer worktree detection."""

    def test_finds_gone_worktree(self, mocker):
        """Verify a gone worktree is identified as a candidate."""
        # Given
        mocker.patch(
            "gx.lib.stale_analyzer.list_worktrees",
            return_value=[
                _worktree(is_main=True, path="/repo", branch="main"),
                _worktree(is_gone=True),
            ],
        )
        mocker.patch("gx.lib.stale_analyzer._is_worktree_dirty", return_value=False)
        mocker.patch("gx.lib.stale_analyzer.default_branch", return_value="main")
        mocker.patch("gx.lib.stale_analyzer.merged_branches", return_value=frozenset())
        mocker.patch("gx.lib.stale_analyzer.gone_branches", return_value=frozenset())
        mocker.patch("gx.lib.stale_analyzer.all_local_branches", return_value=frozenset({"main"}))

        # When
        analyzer = StaleAnalyzer(protected=config.protected_branches)
        wt_candidates, _br_candidates, skipped = analyzer.analyze()

        # Then
        assert len(wt_candidates) == 1
        assert wt_candidates[0].branch == "feat/1"
        assert wt_candidates[0].reason == "gone"
        assert len(skipped) == 0

    def test_skips_main_worktree(self, mocker):
        """Verify the main worktree is never a candidate."""
        # Given
        mocker.patch(
            "gx.lib.stale_analyzer.list_worktrees",
            return_value=[
                _worktree(is_main=True, path="/repo", branch="main", is_merged=True),
            ],
        )
        mocker.patch("gx.lib.stale_analyzer.default_branch", return_value="main")
        mocker.patch("gx.lib.stale_analyzer.merged_branches", return_value=frozenset())
        mocker.patch("gx.lib.stale_analyzer.gone_branches", return_value=frozenset())
        mocker.patch("gx.lib.stale_analyzer.all_local_branches", return_value=frozenset({"main"}))

        # When
        analyzer = StaleAnalyzer(protected=config.protected_branches)
        wt_candidates, _, skipped = analyzer.analyze()

        # Then
        assert len(wt_candidates) == 0
        assert len(skipped) == 0

    def test_skips_bare_worktree(self, mocker):
        """Verify bare worktrees are skipped."""
        # Given
        mocker.patch(
            "gx.lib.stale_analyzer.list_worktrees",
            return_value=[
                _worktree(is_main=True, path="/repo", branch="main"),
                _worktree(is_bare=True, is_gone=True),
            ],
        )
        mocker.patch("gx.lib.stale_analyzer.default_branch", return_value="main")
        mocker.patch("gx.lib.stale_analyzer.merged_branches", return_value=frozenset())
        mocker.patch("gx.lib.stale_analyzer.gone_branches", return_value=frozenset())
        mocker.patch("gx.lib.stale_analyzer.all_local_branches", return_value=frozenset({"main"}))

        # When
        analyzer = StaleAnalyzer(protected=config.protected_branches)
        wt_candidates, _, _ = analyzer.analyze()

        # Then
        assert len(wt_candidates) == 0

    def test_skips_detached_head_worktree(self, mocker):
        """Verify detached HEAD worktrees are skipped."""
        # Given
        mocker.patch(
            "gx.lib.stale_analyzer.list_worktrees",
            return_value=[
                _worktree(is_main=True, path="/repo", branch="main"),
                _worktree(branch=None, is_gone=True),
            ],
        )
        mocker.patch("gx.lib.stale_analyzer.default_branch", return_value="main")
        mocker.patch("gx.lib.stale_analyzer.merged_branches", return_value=frozenset())
        mocker.patch("gx.lib.stale_analyzer.gone_branches", return_value=frozenset())
        mocker.patch("gx.lib.stale_analyzer.all_local_branches", return_value=frozenset({"main"}))

        # When
        analyzer = StaleAnalyzer(protected=config.protected_branches)
        wt_candidates, _, _ = analyzer.analyze()

        # Then
        assert len(wt_candidates) == 0

    def test_skips_protected_branch_worktree(self, mocker):
        """Verify worktrees on protected branches are skipped."""
        # Given
        mocker.patch(
            "gx.lib.stale_analyzer.list_worktrees",
            return_value=[
                _worktree(is_main=True, path="/repo", branch="main"),
                _worktree(path="/repo/.worktrees/develop", branch="develop", is_merged=True),
            ],
        )
        mocker.patch("gx.lib.stale_analyzer.default_branch", return_value="main")
        mocker.patch("gx.lib.stale_analyzer.merged_branches", return_value=frozenset())
        mocker.patch("gx.lib.stale_analyzer.gone_branches", return_value=frozenset())
        mocker.patch("gx.lib.stale_analyzer.all_local_branches", return_value=frozenset({"main"}))

        # When
        analyzer = StaleAnalyzer(protected=config.protected_branches)
        wt_candidates, _, _ = analyzer.analyze()

        # Then
        assert len(wt_candidates) == 0

    def test_dirty_worktree_skipped_without_force(self, mocker):
        """Verify dirty worktrees are skipped and reported when force=False."""
        # Given
        mocker.patch(
            "gx.lib.stale_analyzer.list_worktrees",
            return_value=[
                _worktree(is_main=True, path="/repo", branch="main"),
                _worktree(is_gone=True),
            ],
        )
        mocker.patch("gx.lib.stale_analyzer._is_worktree_dirty", return_value=True)
        mocker.patch("gx.lib.stale_analyzer.has_upstream_branch", return_value=True)
        mocker.patch("gx.lib.stale_analyzer.default_branch", return_value="main")
        mocker.patch("gx.lib.stale_analyzer.merged_branches", return_value=frozenset())
        mocker.patch("gx.lib.stale_analyzer.gone_branches", return_value=frozenset())
        mocker.patch("gx.lib.stale_analyzer.all_local_branches", return_value=frozenset({"main"}))

        # When
        analyzer = StaleAnalyzer(protected=config.protected_branches, force=False)
        wt_candidates, _, skipped = analyzer.analyze()

        # Then
        assert len(wt_candidates) == 0
        assert len(skipped) == 1
        assert skipped[0].branch == "feat/1"

    def test_dirty_worktree_included_with_force(self, mocker):
        """Verify dirty worktrees are included when force=True."""
        # Given
        mocker.patch(
            "gx.lib.stale_analyzer.list_worktrees",
            return_value=[
                _worktree(is_main=True, path="/repo", branch="main"),
                _worktree(is_gone=True),
            ],
        )
        mocker.patch("gx.lib.stale_analyzer._is_worktree_dirty", return_value=True)
        mocker.patch("gx.lib.stale_analyzer.has_upstream_branch", return_value=True)
        mocker.patch("gx.lib.stale_analyzer.default_branch", return_value="main")
        mocker.patch("gx.lib.stale_analyzer.merged_branches", return_value=frozenset())
        mocker.patch("gx.lib.stale_analyzer.gone_branches", return_value=frozenset())
        mocker.patch("gx.lib.stale_analyzer.all_local_branches", return_value=frozenset({"main"}))

        # When
        analyzer = StaleAnalyzer(protected=config.protected_branches, force=True)
        wt_candidates, _, skipped = analyzer.analyze()

        # Then
        assert len(wt_candidates) == 1
        assert len(skipped) == 0

    def test_skips_local_only_worktree(self, mocker):
        """Verify worktrees on branches without upstream are never candidates."""
        # Given
        mocker.patch(
            "gx.lib.stale_analyzer.list_worktrees",
            return_value=[
                _worktree(is_main=True, path="/repo", branch="main"),
                _worktree(is_merged=True),
            ],
        )
        mocker.patch("gx.lib.stale_analyzer.has_upstream_branch", return_value=False)
        mocker.patch("gx.lib.stale_analyzer.default_branch", return_value="main")
        mocker.patch("gx.lib.stale_analyzer.merged_branches", return_value=frozenset())
        mocker.patch("gx.lib.stale_analyzer.gone_branches", return_value=frozenset())
        mocker.patch("gx.lib.stale_analyzer.all_local_branches", return_value=frozenset({"main"}))

        # When
        analyzer = StaleAnalyzer(protected=config.protected_branches)
        wt_candidates, _, _ = analyzer.analyze()

        # Then
        assert len(wt_candidates) == 0


class TestStaleBranches:
    """Tests for StaleAnalyzer branch detection."""

    def test_finds_gone_branch(self, mocker):
        """Verify a gone branch is identified as a candidate."""
        # Given
        mocker.patch("gx.lib.stale_analyzer.list_worktrees", return_value=[])
        mocker.patch("gx.lib.stale_analyzer.default_branch", return_value="main")
        mocker.patch(
            "gx.lib.stale_analyzer.all_local_branches",
            return_value=frozenset({"feat/1", "main"}),
        )
        mocker.patch("gx.lib.stale_analyzer.gone_branches", return_value=frozenset({"feat/1"}))
        mocker.patch("gx.lib.stale_analyzer.merged_branches", return_value=frozenset())

        # When
        analyzer = StaleAnalyzer(protected=config.protected_branches)
        _, br_candidates, _ = analyzer.analyze()

        # Then
        assert len(br_candidates) == 1
        assert br_candidates[0].branch == "feat/1"
        assert br_candidates[0].reason == "gone"

    def test_finds_merged_branch_with_upstream(self, mocker):
        """Verify a merged branch with upstream is a candidate."""
        # Given
        mocker.patch("gx.lib.stale_analyzer.list_worktrees", return_value=[])
        mocker.patch("gx.lib.stale_analyzer.default_branch", return_value="main")
        mocker.patch(
            "gx.lib.stale_analyzer.all_local_branches",
            return_value=frozenset({"feat/2", "main"}),
        )
        mocker.patch("gx.lib.stale_analyzer.gone_branches", return_value=frozenset())
        mocker.patch(
            "gx.lib.stale_analyzer.merged_branches", return_value=frozenset({"main", "feat/2"})
        )
        mocker.patch("gx.lib.stale_analyzer.has_upstream_branch", return_value=True)

        # When
        analyzer = StaleAnalyzer(protected=config.protected_branches)
        _, br_candidates, _ = analyzer.analyze()

        # Then
        assert len(br_candidates) == 1
        assert br_candidates[0].branch == "feat/2"
        assert br_candidates[0].reason == "merged"

    def test_excludes_branch_covered_by_worktree(self, mocker):
        """Verify branches already covered by a stale worktree are excluded."""
        # Given
        mocker.patch(
            "gx.lib.stale_analyzer.list_worktrees",
            return_value=[
                _worktree(is_main=True, path="/repo", branch="main"),
                _worktree(is_gone=True),
            ],
        )
        mocker.patch("gx.lib.stale_analyzer._is_worktree_dirty", return_value=False)
        mocker.patch("gx.lib.stale_analyzer.default_branch", return_value="main")
        mocker.patch(
            "gx.lib.stale_analyzer.all_local_branches",
            return_value=frozenset({"feat/1", "main"}),
        )
        mocker.patch("gx.lib.stale_analyzer.gone_branches", return_value=frozenset({"feat/1"}))
        mocker.patch("gx.lib.stale_analyzer.merged_branches", return_value=frozenset())

        # When
        analyzer = StaleAnalyzer(protected=config.protected_branches)
        _, br_candidates, _ = analyzer.analyze()

        # Then
        assert len(br_candidates) == 0

    def test_excludes_protected_branches(self, mocker):
        """Verify protected branches are never candidates."""
        # Given
        mocker.patch("gx.lib.stale_analyzer.list_worktrees", return_value=[])
        mocker.patch("gx.lib.stale_analyzer.default_branch", return_value="main")
        mocker.patch(
            "gx.lib.stale_analyzer.all_local_branches",
            return_value=frozenset({"main", "develop"}),
        )
        mocker.patch(
            "gx.lib.stale_analyzer.gone_branches", return_value=frozenset({"main", "develop"})
        )
        mocker.patch("gx.lib.stale_analyzer.merged_branches", return_value=frozenset())

        # When
        analyzer = StaleAnalyzer(protected=config.protected_branches)
        _, br_candidates, _ = analyzer.analyze()

        # Then
        assert len(br_candidates) == 0

    def test_excludes_current_branch(self, mocker):
        """Verify the current branch is never a candidate."""
        # Given
        mocker.patch("gx.lib.stale_analyzer.list_worktrees", return_value=[])
        mocker.patch("gx.lib.stale_analyzer.default_branch", return_value="main")
        mocker.patch(
            "gx.lib.stale_analyzer.all_local_branches",
            return_value=frozenset({"feat/1", "main"}),
        )
        mocker.patch("gx.lib.stale_analyzer.gone_branches", return_value=frozenset({"feat/1"}))
        mocker.patch("gx.lib.stale_analyzer.merged_branches", return_value=frozenset())

        # When — feat/1 is the current branch, so include it in protected
        protected_with_current = config.protected_branches | frozenset({"feat/1"})
        analyzer = StaleAnalyzer(protected=protected_with_current)
        _, br_candidates, _ = analyzer.analyze()

        # Then
        assert len(br_candidates) == 0

    def test_excludes_local_only_merged_branch(self, mocker):
        """Verify merged branches without upstream are excluded."""
        # Given
        mocker.patch("gx.lib.stale_analyzer.list_worktrees", return_value=[])
        mocker.patch("gx.lib.stale_analyzer.default_branch", return_value="main")
        mocker.patch(
            "gx.lib.stale_analyzer.all_local_branches",
            return_value=frozenset({"feat/local", "main"}),
        )
        mocker.patch("gx.lib.stale_analyzer.gone_branches", return_value=frozenset())
        mocker.patch(
            "gx.lib.stale_analyzer.merged_branches", return_value=frozenset({"feat/local"})
        )
        mocker.patch("gx.lib.stale_analyzer.has_upstream_branch", return_value=False)

        # When
        analyzer = StaleAnalyzer(protected=config.protected_branches)
        _, br_candidates, _ = analyzer.analyze()

        # Then
        assert len(br_candidates) == 0

    def test_finds_empty_branch_with_upstream(self, mocker):
        """Verify an empty branch with upstream is a candidate."""
        # Given
        mocker.patch("gx.lib.stale_analyzer.list_worktrees", return_value=[])
        mocker.patch("gx.lib.stale_analyzer.default_branch", return_value="main")
        mocker.patch("gx.lib.stale_analyzer.gone_branches", return_value=frozenset())
        mocker.patch("gx.lib.stale_analyzer.merged_branches", return_value=frozenset())
        mocker.patch("gx.lib.stale_analyzer.has_upstream_branch", return_value=True)
        mocker.patch(
            "gx.lib.stale_analyzer.all_local_branches",
            return_value=frozenset({"feat/empty", "main"}),
        )
        mocker.patch("gx.lib.stale_analyzer.is_empty", return_value=True)

        # When
        analyzer = StaleAnalyzer(protected=config.protected_branches)
        _, br_candidates, _ = analyzer.analyze()

        # Then
        assert len(br_candidates) == 1
        assert br_candidates[0].branch == "feat/empty"
        assert br_candidates[0].reason == "empty"


class TestStaleReason:
    """Tests for _stale_reason()."""

    def test_gone_takes_priority(self):
        """Verify gone is returned when branch is both gone and merged."""
        reason = _stale_reason(
            "feat/1",
            merged=frozenset({"feat/1"}),
            gone=frozenset({"feat/1"}),
            target="main",
        )
        assert reason == "gone"

    def test_returns_none_for_non_stale(self, mocker):
        """Verify None for a branch that is not stale."""
        mocker.patch("gx.lib.stale_analyzer.is_empty", return_value=False)

        reason = _stale_reason(
            "feat/active",
            merged=frozenset(),
            gone=frozenset(),
            target="main",
        )
        assert reason is None
