"""Tests for gx done command."""

from __future__ import annotations

from pathlib import Path

import click
import pytest
import typer

from gx.commands.done import done
from gx.lib.worktree import WorktreeInfo

from .conftest import _fail, _ok


def _worktree(
    path: str = "/repo/.worktrees/feat",
    branch: str = "feature-x",
    *,
    is_main: bool = False,
    is_gone: bool = False,
) -> WorktreeInfo:
    """Build a WorktreeInfo for testing."""
    return WorktreeInfo(
        path=Path(path),
        branch=branch,
        commit="abc123",
        is_bare=False,
        is_main=is_main,
        is_merged=False,
        is_gone=is_gone,
        is_empty=False,
    )


class TestDoneGuards:
    """Tests for done command guard rail checks."""

    def test_already_on_default_branch_aborts(
        self,
        mocker,
        capsys,
    ):
        """Verify done aborts when already on the default branch."""
        # Given
        mocker.patch("gx.commands.done.check_git_repo", autospec=True)
        mocker.patch("gx.commands.done.current_branch", autospec=True, return_value="main")
        mocker.patch("gx.commands.done.default_branch", autospec=True, return_value="main")

        # When
        ctx = typer.Context(click.Command("done"))
        with pytest.raises(typer.Exit):
            done(ctx=ctx, verbose=0, dry_run=False)

        # Then
        captured = capsys.readouterr()
        assert "Already on the default branch" in captured.err

    def test_detached_head_aborts(
        self,
        mocker,
        capsys,
    ):
        """Verify done aborts in detached HEAD state."""
        # Given
        mocker.patch("gx.commands.done.check_git_repo", autospec=True)
        mocker.patch("gx.commands.done.current_branch", autospec=True, return_value=None)

        # When
        ctx = typer.Context(click.Command("done"))
        with pytest.raises(typer.Exit):
            done(ctx=ctx, verbose=0, dry_run=False)

        # Then
        captured = capsys.readouterr()
        assert "detached HEAD" in captured.err


class TestDoneMode1:
    """Tests for done from a feature branch (no worktree)."""

    def test_happy_path_checkout_pull_delete(
        self,
        mocker,
        capsys,
    ):
        """Verify done checks out main, pulls, and deletes the feature branch."""
        # Given
        mocker.patch("gx.commands.done.check_git_repo", autospec=True)
        mocker.patch("gx.commands.done.current_branch", autospec=True, return_value="feature-x")
        mocker.patch("gx.commands.done.default_branch", autospec=True, return_value="main")
        mocker.patch("gx.commands.done.list_worktrees", autospec=True, return_value=[])
        mocker.patch(
            "gx.commands.done.validate_branch",
            autospec=True,
            return_value=("main", "origin", "main"),
        )
        mocker.patch("gx.commands.done.stash_if_dirty", autospec=True, return_value=False)
        mocker.patch("gx.commands.done.fetch_and_rebase", autospec=True)
        mocker.patch("gx.commands.done.update_submodules", autospec=True)
        mocker.patch("gx.commands.done.unstash", autospec=True)
        mocker.patch("gx.commands.done.print_summary", autospec=True)
        mock_git = mocker.patch("gx.commands.done.git", autospec=True)
        mock_git.side_effect = [
            _ok(),  # checkout main
            _ok(stdout="abc"),  # rev-parse HEAD (before)
            _ok(),  # branch -D feature-x
        ]

        # When
        ctx = typer.Context(click.Command("done"))
        done(ctx=ctx, verbose=0, dry_run=False)

        # Then
        calls = [c.args for c in mock_git.call_args_list]
        assert ("checkout", "main") in calls
        assert ("branch", "-D", "feature-x") in calls

    def test_branch_delete_failure_warns_not_errors(
        self,
        mocker,
        capsys,
    ):
        """Verify branch deletion failure produces a warning, not a hard error."""
        # Given
        mocker.patch("gx.commands.done.check_git_repo", autospec=True)
        mocker.patch("gx.commands.done.current_branch", autospec=True, return_value="feature-x")
        mocker.patch("gx.commands.done.default_branch", autospec=True, return_value="main")
        mocker.patch("gx.commands.done.list_worktrees", autospec=True, return_value=[])
        mocker.patch(
            "gx.commands.done.validate_branch",
            autospec=True,
            return_value=("main", "origin", "main"),
        )
        mocker.patch("gx.commands.done.stash_if_dirty", autospec=True, return_value=False)
        mocker.patch("gx.commands.done.fetch_and_rebase", autospec=True)
        mocker.patch("gx.commands.done.update_submodules", autospec=True)
        mocker.patch("gx.commands.done.unstash", autospec=True)
        mocker.patch("gx.commands.done.print_summary", autospec=True)
        mock_git = mocker.patch("gx.commands.done.git", autospec=True)
        mock_git.side_effect = [
            _ok(),  # checkout main
            _ok(stdout="abc"),  # rev-parse HEAD (before)
            _fail(stderr="not fully merged"),  # branch -D fails
        ]

        # When — should NOT raise
        ctx = typer.Context(click.Command("done"))
        done(ctx=ctx, verbose=0, dry_run=False)

        # Then
        captured = capsys.readouterr()
        assert "feature-x" in captured.err


class TestDoneMode2:
    """Tests for done from a worktree."""

    def test_worktree_happy_path(
        self,
        mocker,
        tmp_path,
        capsys,
    ):
        """Verify done removes worktree, pulls, and deletes branch."""
        # Given
        mocker.patch("gx.commands.done.check_git_repo", autospec=True)
        mocker.patch(
            "gx.commands.done.current_branch", autospec=True, side_effect=["feature-x", "main"]
        )
        mocker.patch("gx.commands.done.default_branch", autospec=True, return_value="main")
        mocker.patch("gx.commands.done.is_dirty", autospec=True, return_value=False)
        mocker.patch(
            "gx.commands.done.validate_branch",
            autospec=True,
            return_value=("main", "origin", "main"),
        )
        mocker.patch("gx.commands.done.stash_if_dirty", autospec=True, return_value=False)
        mocker.patch("gx.commands.done.fetch_and_rebase", autospec=True)
        mocker.patch("gx.commands.done.update_submodules", autospec=True)
        mocker.patch("gx.commands.done.unstash", autospec=True)
        mocker.patch("gx.commands.done.print_summary", autospec=True)

        wt_path = tmp_path / "worktree"
        wt_path.mkdir()
        main_path = tmp_path / "main"
        main_path.mkdir()

        mocker.patch("gx.commands.done.Path.cwd", return_value=wt_path)

        wt = _worktree(path=str(wt_path), is_gone=True)
        main_wt = _worktree(path=str(main_path), branch="main", is_main=True)
        mocker.patch("gx.commands.done.list_worktrees", autospec=True, return_value=[main_wt, wt])
        mocker.patch("gx.commands.done.remove_worktree", autospec=True, return_value=_ok())
        mock_chdir = mocker.patch("os.chdir", autospec=True)

        mock_git = mocker.patch("gx.commands.done.git", autospec=True)
        mock_git.side_effect = [
            _ok(),  # checkout main
            _ok(stdout="abc"),  # rev-parse HEAD (before pull)
            _ok(),  # branch -D feature-x
        ]

        # When
        ctx = typer.Context(click.Command("done"))
        done(ctx=ctx, verbose=0, dry_run=False)

        # Then
        mock_chdir.assert_called_once_with(main_path)
        captured = capsys.readouterr()
        assert "Remove worktree" in captured.out
        err_flat = captured.err.replace("\n", "")
        assert str(main_path) in err_flat

    def test_dirty_worktree_aborts(
        self,
        mocker,
        tmp_path,
        capsys,
    ):
        """Verify done aborts when worktree has uncommitted changes."""
        # Given
        mocker.patch("gx.commands.done.check_git_repo", autospec=True)
        mocker.patch("gx.commands.done.current_branch", autospec=True, return_value="feature-x")
        mocker.patch("gx.commands.done.default_branch", autospec=True, return_value="main")
        mocker.patch("gx.commands.done.is_dirty", autospec=True, return_value=True)

        wt_path = tmp_path / "worktree"
        wt_path.mkdir()
        main_path = tmp_path / "main"
        main_path.mkdir()

        mocker.patch("gx.commands.done.Path.cwd", return_value=wt_path)

        wt = _worktree(path=str(wt_path), is_gone=True)
        main_wt = _worktree(path=str(main_path), branch="main", is_main=True)
        mocker.patch("gx.commands.done.list_worktrees", autospec=True, return_value=[main_wt, wt])

        # When
        ctx = typer.Context(click.Command("done"))
        with pytest.raises(typer.Exit):
            done(ctx=ctx, verbose=0, dry_run=False)

        # Then
        captured = capsys.readouterr()
        assert "uncommitted changes" in captured.err

    def test_worktree_removal_failure_is_hard_error(
        self,
        mocker,
        tmp_path,
        capsys,
    ):
        """Verify worktree removal failure exits with error."""
        # Given
        mocker.patch("gx.commands.done.check_git_repo", autospec=True)
        mocker.patch("gx.commands.done.current_branch", autospec=True, return_value="feature-x")
        mocker.patch("gx.commands.done.default_branch", autospec=True, return_value="main")
        mocker.patch("gx.commands.done.is_dirty", autospec=True, return_value=False)

        wt_path = tmp_path / "worktree"
        wt_path.mkdir()
        main_path = tmp_path / "main"
        main_path.mkdir()

        mocker.patch("gx.commands.done.Path.cwd", return_value=wt_path)

        wt = _worktree(path=str(wt_path), is_gone=True)
        main_wt = _worktree(path=str(main_path), branch="main", is_main=True)
        mocker.patch("gx.commands.done.list_worktrees", autospec=True, return_value=[main_wt, wt])
        mocker.patch(
            "gx.commands.done.remove_worktree", autospec=True, return_value=_fail(stderr="locked")
        )
        mocker.patch("os.chdir", autospec=True)

        # When
        ctx = typer.Context(click.Command("done"))
        with pytest.raises(typer.Exit):
            done(ctx=ctx, verbose=0, dry_run=False)

        # Then
        captured = capsys.readouterr()
        assert "Failed to remove worktree" in captured.err
