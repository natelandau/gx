"""Tests for gx clean command."""

from __future__ import annotations

from pathlib import Path

import click
import typer

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


class TestCleanCommand:
    """Tests for the clean() callback."""

    def test_nothing_to_clean(
        self,
        mocker,
        mock_clean_git,
        mock_clean_check_git_repo,
        mock_clean_current_branch,
        capsys,
    ):
        """Verify prints 'Nothing to clean' when no stale items exist."""
        # Given
        mock_clean_git.return_value = _ok()  # fetch
        mocker.patch("gx.lib.stale_analyzer.list_worktrees", return_value=[])
        mocker.patch("gx.lib.stale_analyzer.default_branch", return_value="main")
        mocker.patch("gx.lib.stale_analyzer.merged_branches", return_value=frozenset())
        mocker.patch("gx.lib.stale_analyzer.gone_branches", return_value=frozenset())
        mocker.patch("gx.lib.stale_analyzer.all_local_branches", return_value=frozenset({"main"}))

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
        capsys,
    ):
        """Verify --yes skips the confirmation prompt."""
        # Given — no worktrees, one gone standalone branch
        mock_clean_git.side_effect = [
            _ok(),  # fetch
            _ok(),  # branch -D feat/1
        ]
        mocker.patch("gx.lib.stale_analyzer.list_worktrees", return_value=[])
        mocker.patch("gx.lib.stale_analyzer.default_branch", return_value="main")
        mocker.patch("gx.lib.stale_analyzer.gone_branches", return_value=frozenset({"feat/1"}))
        mocker.patch("gx.lib.stale_analyzer.merged_branches", return_value=frozenset())
        mocker.patch("gx.lib.stale_analyzer.has_upstream_branch", return_value=True)
        mocker.patch(
            "gx.lib.stale_analyzer.all_local_branches",
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
        capsys,
    ):
        """Verify --dry-run shows candidates but does not delete."""
        # Given
        mock_clean_git.return_value = _ok()  # fetch
        mocker.patch("gx.lib.stale_analyzer.list_worktrees", return_value=[])
        mocker.patch("gx.lib.stale_analyzer.default_branch", return_value="main")
        mocker.patch("gx.lib.stale_analyzer.gone_branches", return_value=frozenset({"feat/1"}))
        mocker.patch("gx.lib.stale_analyzer.merged_branches", return_value=frozenset())
        mocker.patch(
            "gx.lib.stale_analyzer.all_local_branches",
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
        capsys,
    ):
        """Verify cleanup continues when one worktree removal fails."""
        # Given — two gone worktrees, first removal fails
        wt1 = _worktree(path="/repo/.worktrees/feat/1", branch="feat/1", is_gone=True)
        wt2 = _worktree(path="/repo/.worktrees/feat/2", branch="feat/2", is_gone=True)
        mocker.patch(
            "gx.lib.stale_analyzer.list_worktrees",
            return_value=[
                _worktree(is_main=True, path="/repo", branch="main"),
                wt1,
                wt2,
            ],
        )
        mocker.patch("gx.lib.stale_analyzer._is_worktree_dirty", return_value=False)
        mocker.patch("gx.lib.stale_analyzer.default_branch", return_value="main")
        mocker.patch(
            "gx.lib.stale_analyzer.all_local_branches",
            return_value=frozenset({"feat/1", "feat/2", "main"}),
        )
        mocker.patch(
            "gx.lib.stale_analyzer.gone_branches", return_value=frozenset({"feat/1", "feat/2"})
        )
        mocker.patch("gx.lib.stale_analyzer.merged_branches", return_value=frozenset())

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
