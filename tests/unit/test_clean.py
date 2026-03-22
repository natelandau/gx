"""Tests for gx clean command."""

from __future__ import annotations

from pathlib import Path

import click
import typer

from gx.lib.config import config
from gx.lib.worktree import WorktreeInfo

from .conftest import _fail, _ok


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
    """Tests for _stale_worktrees()."""

    def test_finds_gone_worktree(
        self,
        mocker,
        mock_clean_current_branch,
        mock_clean_list_worktrees,
    ):
        """Verify a gone worktree is identified as a candidate."""
        # Given
        mock_clean_list_worktrees.return_value = [
            _worktree(is_main=True, path="/repo", branch="main"),
            _worktree(is_gone=True),
        ]
        mocker.patch("gx.commands.clean._is_worktree_dirty", return_value=False)

        # When
        from gx.commands.clean import _stale_worktrees

        candidates, skipped = _stale_worktrees(force=False, protected=config.protected_branches)

        # Then
        assert len(candidates) == 1
        assert candidates[0].branch == "feat/1"
        assert candidates[0].reason == "gone"
        assert len(skipped) == 0

    def test_skips_main_worktree(
        self,
        mock_clean_current_branch,
        mock_clean_list_worktrees,
    ):
        """Verify the main worktree is never a candidate."""
        # Given
        mock_clean_list_worktrees.return_value = [
            _worktree(is_main=True, path="/repo", branch="main", is_merged=True),
        ]

        # When
        from gx.commands.clean import _stale_worktrees

        candidates, skipped = _stale_worktrees(force=False, protected=config.protected_branches)

        # Then
        assert len(candidates) == 0
        assert len(skipped) == 0

    def test_skips_bare_worktree(
        self,
        mock_clean_current_branch,
        mock_clean_list_worktrees,
    ):
        """Verify bare worktrees are skipped."""
        # Given
        mock_clean_list_worktrees.return_value = [
            _worktree(is_main=True, path="/repo", branch="main"),
            _worktree(is_bare=True, is_gone=True),
        ]

        # When
        from gx.commands.clean import _stale_worktrees

        candidates, _ = _stale_worktrees(force=False, protected=config.protected_branches)

        # Then
        assert len(candidates) == 0

    def test_skips_detached_head_worktree(
        self,
        mock_clean_current_branch,
        mock_clean_list_worktrees,
    ):
        """Verify detached HEAD worktrees are skipped."""
        # Given
        mock_clean_list_worktrees.return_value = [
            _worktree(is_main=True, path="/repo", branch="main"),
            _worktree(branch=None, is_gone=True),
        ]

        # When
        from gx.commands.clean import _stale_worktrees

        candidates, _ = _stale_worktrees(force=False, protected=config.protected_branches)

        # Then
        assert len(candidates) == 0

    def test_skips_protected_branch_worktree(
        self,
        mock_clean_current_branch,
        mock_clean_list_worktrees,
    ):
        """Verify worktrees on protected branches are skipped."""
        # Given
        mock_clean_list_worktrees.return_value = [
            _worktree(is_main=True, path="/repo", branch="main"),
            _worktree(path="/repo/.worktrees/develop", branch="develop", is_merged=True),
        ]

        # When
        from gx.commands.clean import _stale_worktrees

        candidates, _ = _stale_worktrees(force=False, protected=config.protected_branches)

        # Then
        assert len(candidates) == 0

    def test_dirty_worktree_skipped_without_force(
        self,
        mocker,
        mock_clean_current_branch,
        mock_clean_list_worktrees,
        mock_clean_has_upstream_branch,
    ):
        """Verify dirty worktrees are skipped and reported when force=False."""
        # Given
        mock_clean_list_worktrees.return_value = [
            _worktree(is_main=True, path="/repo", branch="main"),
            _worktree(is_gone=True),
        ]
        mocker.patch("gx.commands.clean._is_worktree_dirty", return_value=True)

        # When
        from gx.commands.clean import _stale_worktrees

        candidates, skipped = _stale_worktrees(force=False, protected=config.protected_branches)

        # Then
        assert len(candidates) == 0
        assert len(skipped) == 1
        assert skipped[0].branch == "feat/1"

    def test_dirty_worktree_included_with_force(
        self,
        mocker,
        mock_clean_current_branch,
        mock_clean_list_worktrees,
        mock_clean_has_upstream_branch,
    ):
        """Verify dirty worktrees are included when force=True."""
        # Given
        mock_clean_list_worktrees.return_value = [
            _worktree(is_main=True, path="/repo", branch="main"),
            _worktree(is_gone=True),
        ]
        mocker.patch("gx.commands.clean._is_worktree_dirty", return_value=True)

        # When
        from gx.commands.clean import _stale_worktrees

        candidates, skipped = _stale_worktrees(force=True, protected=config.protected_branches)

        # Then
        assert len(candidates) == 1
        assert len(skipped) == 0

    def test_skips_local_only_worktree(
        self,
        mocker,
        mock_clean_current_branch,
        mock_clean_list_worktrees,
        mock_clean_has_upstream_branch,
    ):
        """Verify worktrees on branches without upstream are never candidates."""
        # Given
        mock_clean_list_worktrees.return_value = [
            _worktree(is_main=True, path="/repo", branch="main"),
            _worktree(is_merged=True),
        ]
        mock_clean_has_upstream_branch.return_value = False

        # When
        from gx.commands.clean import _stale_worktrees

        candidates, _ = _stale_worktrees(force=False, protected=config.protected_branches)

        # Then
        assert len(candidates) == 0


class TestStaleBranches:
    """Tests for _stale_branches()."""

    def test_finds_gone_branch(
        self,
        mocker,
        mock_clean_default_branch,
        mock_clean_current_branch,
        mock_clean_gone_branches,
        mock_clean_merged_branches,
    ):
        """Verify a gone branch is identified as a candidate."""
        # Given
        mocker.patch(
            "gx.commands.clean.all_local_branches",
            return_value=frozenset({"feat/1", "main"}),
        )
        mock_clean_gone_branches.return_value = frozenset({"feat/1"})
        mock_clean_merged_branches.return_value = frozenset()

        # When
        from gx.commands.clean import _stale_branches

        candidates = _stale_branches(worktree_branches=set(), protected=config.protected_branches)

        # Then
        assert len(candidates) == 1
        assert candidates[0].branch == "feat/1"
        assert candidates[0].reason == "gone"

    def test_finds_merged_branch_with_upstream(
        self,
        mocker,
        mock_clean_default_branch,
        mock_clean_current_branch,
        mock_clean_gone_branches,
        mock_clean_merged_branches,
        mock_clean_has_upstream_branch,
    ):
        """Verify a merged branch with upstream is a candidate."""
        # Given
        mocker.patch(
            "gx.commands.clean.all_local_branches",
            return_value=frozenset({"feat/2", "main"}),
        )
        mock_clean_gone_branches.return_value = frozenset()
        mock_clean_merged_branches.return_value = frozenset({"main", "feat/2"})
        mock_clean_has_upstream_branch.return_value = True

        # When
        from gx.commands.clean import _stale_branches

        candidates = _stale_branches(worktree_branches=set(), protected=config.protected_branches)

        # Then
        assert len(candidates) == 1
        assert candidates[0].branch == "feat/2"
        assert candidates[0].reason == "merged"

    def test_excludes_branch_covered_by_worktree(
        self,
        mocker,
        mock_clean_default_branch,
        mock_clean_current_branch,
        mock_clean_gone_branches,
        mock_clean_merged_branches,
    ):
        """Verify branches already covered by a stale worktree are excluded."""
        # Given
        mocker.patch(
            "gx.commands.clean.all_local_branches",
            return_value=frozenset({"feat/1", "main"}),
        )
        mock_clean_gone_branches.return_value = frozenset({"feat/1"})
        mock_clean_merged_branches.return_value = frozenset()

        # When
        from gx.commands.clean import _stale_branches

        candidates = _stale_branches(
            worktree_branches={"feat/1"}, protected=config.protected_branches
        )

        # Then
        assert len(candidates) == 0

    def test_excludes_protected_branches(
        self,
        mocker,
        mock_clean_default_branch,
        mock_clean_current_branch,
        mock_clean_gone_branches,
        mock_clean_merged_branches,
    ):
        """Verify protected branches are never candidates."""
        # Given
        mocker.patch(
            "gx.commands.clean.all_local_branches",
            return_value=frozenset({"main", "develop"}),
        )
        mock_clean_gone_branches.return_value = frozenset({"main", "develop"})
        mock_clean_merged_branches.return_value = frozenset()

        # When
        from gx.commands.clean import _stale_branches

        candidates = _stale_branches(worktree_branches=set(), protected=config.protected_branches)

        # Then
        assert len(candidates) == 0

    def test_excludes_current_branch(
        self,
        mocker,
        mock_clean_default_branch,
        mock_clean_current_branch,
        mock_clean_gone_branches,
        mock_clean_merged_branches,
    ):
        """Verify the current branch is never a candidate."""
        # Given
        mocker.patch(
            "gx.commands.clean.all_local_branches",
            return_value=frozenset({"feat/1", "main"}),
        )
        mock_clean_gone_branches.return_value = frozenset({"feat/1"})
        mock_clean_merged_branches.return_value = frozenset()

        # When — feat/1 is the current branch, so include it in protected
        from gx.commands.clean import _stale_branches

        protected_with_current = config.protected_branches | frozenset({"feat/1"})
        candidates = _stale_branches(worktree_branches=set(), protected=protected_with_current)

        # Then
        assert len(candidates) == 0

    def test_excludes_local_only_merged_branch(
        self,
        mocker,
        mock_clean_default_branch,
        mock_clean_current_branch,
        mock_clean_gone_branches,
        mock_clean_merged_branches,
        mock_clean_has_upstream_branch,
    ):
        """Verify merged branches without upstream are excluded."""
        # Given
        mocker.patch(
            "gx.commands.clean.all_local_branches",
            return_value=frozenset({"feat/local", "main"}),
        )
        mock_clean_gone_branches.return_value = frozenset()
        mock_clean_merged_branches.return_value = frozenset({"feat/local"})
        mock_clean_has_upstream_branch.return_value = False

        # When
        from gx.commands.clean import _stale_branches

        candidates = _stale_branches(worktree_branches=set(), protected=config.protected_branches)

        # Then
        assert len(candidates) == 0

    def test_finds_empty_branch_with_upstream(
        self,
        mocker,
        mock_clean_default_branch,
        mock_clean_current_branch,
        mock_clean_gone_branches,
        mock_clean_merged_branches,
        mock_clean_has_upstream_branch,
    ):
        """Verify an empty branch with upstream is a candidate."""
        # Given
        mock_clean_gone_branches.return_value = frozenset()
        mock_clean_merged_branches.return_value = frozenset()
        mock_clean_has_upstream_branch.return_value = True
        mocker.patch(
            "gx.commands.clean.all_local_branches",
            return_value=frozenset({"feat/empty", "main"}),
        )
        mocker.patch("gx.commands.clean.is_empty", return_value=True)

        # When
        from gx.commands.clean import _stale_branches

        candidates = _stale_branches(worktree_branches=set(), protected=config.protected_branches)

        # Then
        assert len(candidates) == 1
        assert candidates[0].branch == "feat/empty"
        assert candidates[0].reason == "empty"


class TestCleanCommand:
    """Tests for the clean() callback."""

    def test_nothing_to_clean(
        self,
        mocker,
        mock_clean_git,
        mock_clean_check_git_repo,
        mock_clean_current_branch,
        mock_clean_default_branch,
        mock_clean_list_worktrees,
        mock_clean_merged_branches,
        mock_clean_gone_branches,
        capsys,
    ):
        """Verify prints 'Nothing to clean' when no stale items exist."""
        # Given
        mock_clean_git.return_value = _ok()  # fetch
        mocker.patch("gx.commands.clean.all_local_branches", return_value=frozenset({"main"}))

        # When
        ctx = typer.Context(click.Command("clean"))
        from gx.commands.clean import clean

        clean(ctx=ctx, verbose=0, dry_run=False, force=False, yes=False)

        # Then
        captured = capsys.readouterr()
        assert "Nothing to clean" in captured.out

    def test_yes_skips_confirmation(
        self,
        mocker,
        mock_clean_git,
        mock_clean_check_git_repo,
        mock_clean_current_branch,
        mock_clean_default_branch,
        mock_clean_list_worktrees,
        mock_clean_merged_branches,
        mock_clean_gone_branches,
        mock_clean_has_upstream_branch,
        capsys,
    ):
        """Verify --yes skips the confirmation prompt."""
        # Given — no worktrees, one gone standalone branch
        mock_clean_git.side_effect = [
            _ok(),  # fetch
            _ok(),  # branch -D feat/1
        ]
        mock_clean_list_worktrees.return_value = []
        mock_clean_gone_branches.return_value = frozenset({"feat/1"})
        mock_clean_merged_branches.return_value = frozenset()
        mocker.patch(
            "gx.commands.clean.all_local_branches",
            return_value=frozenset({"feat/1", "main"}),
        )
        mock_confirm = mocker.patch("gx.commands.clean.Confirm.ask", autospec=True)

        # When
        ctx = typer.Context(click.Command("clean"))
        from gx.commands.clean import clean

        clean(ctx=ctx, verbose=0, dry_run=False, force=False, yes=True)

        # Then
        mock_confirm.assert_not_called()

    def test_dry_run_skips_deletion(
        self,
        mocker,
        mock_clean_git,
        mock_clean_check_git_repo,
        mock_clean_current_branch,
        mock_clean_default_branch,
        mock_clean_list_worktrees,
        mock_clean_merged_branches,
        mock_clean_gone_branches,
        capsys,
    ):
        """Verify --dry-run shows candidates but does not delete."""
        # Given
        mock_clean_git.return_value = _ok()  # fetch
        mock_clean_list_worktrees.return_value = []
        mock_clean_gone_branches.return_value = frozenset({"feat/1"})
        mock_clean_merged_branches.return_value = frozenset()
        mocker.patch(
            "gx.commands.clean.all_local_branches",
            return_value=frozenset({"feat/1", "main"}),
        )

        # When
        from gx.lib.git import set_dry_run

        set_dry_run(enabled=True)
        ctx = typer.Context(click.Command("clean"))
        from gx.commands.clean import clean

        clean(ctx=ctx, verbose=0, dry_run=True, force=False, yes=False)

        # Then
        captured = capsys.readouterr()
        assert "feat/1" in captured.out
        # branch -D should not have been called — only fetch
        assert mock_clean_git.call_count == 1


class TestCleanPartialFailure:
    """Tests for partial failure handling during cleanup."""

    def test_continues_on_worktree_removal_failure(
        self,
        mocker,
        mock_clean_git,
        mock_clean_check_git_repo,
        mock_clean_current_branch,
        mock_clean_default_branch,
        mock_clean_list_worktrees,
        mock_clean_merged_branches,
        mock_clean_gone_branches,
        mock_clean_has_upstream_branch,
        capsys,
    ):
        """Verify cleanup continues when one worktree removal fails."""
        # Given — two gone worktrees, first removal fails
        wt1 = _worktree(path="/repo/.worktrees/feat/1", branch="feat/1", is_gone=True)
        wt2 = _worktree(path="/repo/.worktrees/feat/2", branch="feat/2", is_gone=True)
        mock_clean_list_worktrees.return_value = [
            _worktree(is_main=True, path="/repo", branch="main"),
            wt1,
            wt2,
        ]
        mocker.patch("gx.commands.clean._is_worktree_dirty", return_value=False)
        mocker.patch(
            "gx.commands.clean.all_local_branches",
            return_value=frozenset({"feat/1", "feat/2", "main"}),
        )
        mock_clean_gone_branches.return_value = frozenset({"feat/1", "feat/2"})
        mock_clean_merged_branches.return_value = frozenset()

        mock_remove = mocker.patch("gx.commands.clean.remove_worktree", autospec=True)
        mock_remove.side_effect = [_fail(stderr="locked"), _ok()]

        mock_clean_git.side_effect = [
            _ok(),  # fetch
            _ok(),  # branch -D feat/2
        ]

        # When
        ctx = typer.Context(click.Command("clean"))
        from gx.commands.clean import clean

        clean(ctx=ctx, verbose=0, dry_run=False, force=False, yes=True)

        # Then
        captured = capsys.readouterr()
        assert "Failed to remove worktree" in captured.err
        assert "Remove" in captured.out


class TestStaleReason:
    """Tests for _stale_reason()."""

    def test_gone_takes_priority(self):
        """Verify gone is returned when branch is both gone and merged."""
        from gx.commands.clean import _stale_reason

        reason = _stale_reason(
            "feat/1",
            merged=frozenset({"feat/1"}),
            gone=frozenset({"feat/1"}),
            target="main",
        )
        assert reason == "gone"

    def test_returns_none_for_non_stale(self, mock_clean_git):
        """Verify None for a branch that is not stale."""
        from gx.commands.clean import _stale_reason

        mock_clean_git.return_value = _ok(stdout="5")  # 5 commits ahead

        reason = _stale_reason(
            "feat/active",
            merged=frozenset(),
            gone=frozenset(),
            target="main",
        )
        assert reason is None
