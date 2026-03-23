"""Tests for gx status command."""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from pathlib import Path
import pytest
import typer

from gx.lib.branch import BranchRow, collect_branch_data

from .conftest import _fail, _ok  # noqa: F401


def _branch_row(
    branch: str = "feat/test",
    target: str = "main",
    ahead_target: int = 0,
    behind_target: int = 0,
    ahead_remote: int | None = None,
    behind_remote: int | None = None,
    staged: int = 0,
    modified: int = 0,
    unmerged: int = 0,
    untracked: int = 0,
    stashes: int = 0,
    is_current: bool = False,  # noqa: FBT002
    is_worktree: bool = False,  # noqa: FBT002
    worktree_path: Path | None = None,
    tracking_ref: str | None = None,
) -> BranchRow:
    """Build a BranchRow for testing."""
    return BranchRow(
        branch=branch,
        target=target,
        ahead_target=ahead_target,
        behind_target=behind_target,
        ahead_remote=ahead_remote,
        behind_remote=behind_remote,
        staged=staged,
        modified=modified,
        unmerged=unmerged,
        untracked=untracked,
        stashes=stashes,
        is_current=is_current,
        is_worktree=is_worktree,
        worktree_path=worktree_path,
        tracking_ref=tracking_ref,
    )


class TestCollectBranchData:
    """Tests for collecting branch dashboard data."""

    def test_basic_branch_data(self, mocker):
        """Verify branch data is collected for active branches."""
        # Given
        mocker.patch("gx.lib.branch.current_branch", return_value="feat/login")
        mocker.patch("gx.lib.branch.default_branch", return_value="main")
        mocker.patch(
            "gx.lib.branch.all_local_branches",
            return_value=frozenset({"main", "feat/login"}),
        )
        mocker.patch("gx.lib.worktree.list_worktrees", return_value=[])
        mocker.patch("gx.lib.branch.stash_counts", return_value={})
        mocker.patch("gx.lib.branch.ahead_behind", return_value=(2, 0))
        mocker.patch("gx.lib.branch.tracking_remote_ref", return_value=None)
        mocker.patch("gx.lib.branch.git", return_value=_ok(stdout=" M file.py\n?? new.txt"))
        # When
        rows = collect_branch_data(show_all=False)
        # Then
        branch_names = [r.branch for r in rows]
        assert "feat/login" in branch_names

    def test_inactive_branch_excluded_by_default(self, mocker):
        """Verify clean branches without activity are excluded."""
        # Given
        mocker.patch("gx.lib.branch.current_branch", return_value="feat/login")
        mocker.patch("gx.lib.branch.default_branch", return_value="main")
        mocker.patch(
            "gx.lib.branch.all_local_branches",
            return_value=frozenset({"main", "feat/login", "old-branch"}),
        )
        mocker.patch("gx.lib.worktree.list_worktrees", return_value=[])
        mocker.patch("gx.lib.branch.stash_counts", return_value={})
        mocker.patch("gx.lib.branch.ahead_behind", return_value=(0, 0))
        mocker.patch("gx.lib.branch.tracking_remote_ref", return_value=None)
        mocker.patch("gx.lib.branch.git", return_value=_ok(stdout=""))
        # When
        rows = collect_branch_data(show_all=False)
        # Then
        branch_names = [r.branch for r in rows]
        assert "old-branch" not in branch_names

    def test_show_all_includes_inactive(self, mocker):
        """Verify --all flag includes clean branches."""
        # Given
        mocker.patch("gx.lib.branch.current_branch", return_value="feat/login")
        mocker.patch("gx.lib.branch.default_branch", return_value="main")
        mocker.patch(
            "gx.lib.branch.all_local_branches",
            return_value=frozenset({"main", "feat/login", "old-branch"}),
        )
        mocker.patch("gx.lib.worktree.list_worktrees", return_value=[])
        mocker.patch("gx.lib.branch.stash_counts", return_value={})
        mocker.patch("gx.lib.branch.ahead_behind", return_value=(0, 0))
        mocker.patch("gx.lib.branch.tracking_remote_ref", return_value=None)
        mocker.patch("gx.lib.branch.git", return_value=_ok(stdout=""))
        # When
        rows = collect_branch_data(show_all=True)
        # Then
        branch_names = [r.branch for r in rows]
        assert "old-branch" in branch_names


class TestStatusCommand:
    """Tests for the status command callback."""

    def test_files_and_branches_mutually_exclusive(self, mocker, capsys):
        """Verify error when both --files and --branches are passed."""
        mocker.patch("gx.commands.status.check_git_repo", autospec=True)
        from gx.commands.status import status

        ctx = typer.Context(click.Command("status"))
        with pytest.raises(typer.Exit):
            status(ctx=ctx, files=True, branches=True, show_all=False)
        captured = capsys.readouterr()
        assert "mutually exclusive" in captured.err.lower() or "cannot" in captured.err.lower()


class TestStatusEdgeCases:
    """Tests for status command edge cases."""

    def test_working_tree_clean_message(
        self, mocker, mock_status_check_git_repo, mock_status_git, mock_status_repo_root, capsys
    ):
        """Verify 'Working tree clean' shown when --files requested with no changes."""
        # Given
        mock_status_git.return_value = _ok(stdout="")
        mocker.patch("gx.commands.status.current_branch", return_value="main")

        # When
        from gx.commands.status import status

        ctx = typer.Context(click.Command("status"))
        status(ctx=ctx, files=True, branches=False, show_all=False)

        # Then
        captured = capsys.readouterr()
        assert "Working tree clean" in captured.out

    def test_files_only_flag(
        self, mocker, mock_status_check_git_repo, mock_status_git, mock_status_repo_root, capsys
    ):
        """Verify --files shows only the file tree panel."""
        # Given
        mock_status_git.return_value = _ok(stdout=" M file.py")
        mocker.patch("gx.commands.status.current_branch", return_value="feat/test")

        # When
        from gx.commands.status import status

        ctx = typer.Context(click.Command("status"))
        status(ctx=ctx, files=True, branches=False, show_all=False)

        # Then — should show file tree panel, no branch table
        captured = capsys.readouterr()
        assert "feat/test" in captured.out
        assert "Branch Status" not in captured.out

    def test_branches_only_flag(self, mocker, mock_status_check_git_repo, mock_status_git, capsys):
        """Verify --branches shows only the branch table."""
        # Given
        mock_status_git.return_value = _ok(stdout=" M file.py")
        mocker.patch("gx.lib.branch.current_branch", return_value="feat/test")
        mocker.patch("gx.lib.branch.default_branch", return_value="main")
        mocker.patch(
            "gx.lib.branch.all_local_branches",
            return_value=frozenset({"main", "feat/test"}),
        )
        mocker.patch("gx.lib.worktree.list_worktrees", return_value=[])
        mocker.patch("gx.lib.branch.stash_counts", return_value={})
        mocker.patch("gx.lib.branch.ahead_behind", return_value=(1, 0))
        mocker.patch("gx.lib.branch.tracking_remote_ref", return_value=None)

        # When
        from gx.commands.status import status

        ctx = typer.Context(click.Command("status"))
        status(ctx=ctx, files=False, branches=True, show_all=False)

        # Then — should show branch table, no file tree
        captured = capsys.readouterr()
        assert "Branches" in captured.out
