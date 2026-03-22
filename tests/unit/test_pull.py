"""Tests for gx pull command."""

from __future__ import annotations

import click
import pytest
import typer

from gx.commands.pull import has_submodules, is_dirty, is_rebase_in_progress, pull
from tests.conftest import make_tmp_dirty

from .conftest import _fail, _ok


class TestPullGuardRails:
    """Tests for pull command guard rail checks."""

    def test_detached_head_aborts(
        self,
        mocker,
        mock_check_git_repo,
        mock_tracking_branch,
        capsys,
    ):
        """Verify pull aborts with error when in detached HEAD state."""
        # Given
        mocker.patch("gx.commands.pull.current_branch", autospec=True, return_value=None)

        # When
        ctx = typer.Context(click.Command("pull"))
        with pytest.raises(typer.Exit):
            pull(ctx=ctx, verbose=0, dry_run=False)

        # Then
        captured = capsys.readouterr()
        assert "detached HEAD" in captured.err

    def test_no_upstream_aborts(
        self,
        mocker,
        mock_check_git_repo,
        capsys,
    ):
        """Verify pull aborts when branch has no upstream configured."""
        # Given
        mocker.patch("gx.commands.pull.current_branch", autospec=True, return_value="feature")
        mocker.patch("gx.commands.pull.tracking_branch", autospec=True, return_value=None)

        # When
        ctx = typer.Context(click.Command("pull"))
        with pytest.raises(typer.Exit):
            pull(ctx=ctx, verbose=0, dry_run=False)

        # Then
        captured = capsys.readouterr()
        assert "upstream" in captured.err
        assert "feature" in captured.err


class TestPullStash:
    """Tests for stash/unstash behavior during pull."""

    def test_stashes_when_dirty(
        self,
        mocker,
        mock_check_git_repo,
        mock_current_branch,
        mock_tracking_branch,
        mock_git,
    ):
        """Verify dirty working tree is stashed and restored after pull."""
        # Given
        mocker.patch("gx.commands.pull.is_dirty", autospec=True, return_value=True)
        mocker.patch("gx.commands.pull.has_submodules", autospec=True, return_value=False)
        mock_git.side_effect = [
            _ok(),  # stash --include-untracked
            _ok(stdout="abc123"),  # rev-parse HEAD (before)
            _ok(),  # fetch
            _ok(),  # pull --rebase
            _ok(),  # stash pop
            _ok(stdout="abc123"),  # rev-parse HEAD (after, same = up to date)
        ]

        # When
        ctx = typer.Context(click.Command("pull"))
        pull(ctx=ctx, verbose=0, dry_run=False)

        # Then
        calls = list(mock_git.call_args_list)
        stash_calls = [c for c in calls if "stash" in c.args]
        assert any("--include-untracked" in c.args for c in stash_calls)
        assert any("pop" in c.args for c in stash_calls)

    def test_skips_stash_when_clean(
        self,
        mocker,
        mock_check_git_repo,
        mock_current_branch,
        mock_tracking_branch,
        mock_git,
    ):
        """Verify no stash calls when working tree is clean."""
        # Given
        mocker.patch("gx.commands.pull.is_dirty", autospec=True, return_value=False)
        mocker.patch("gx.commands.pull.has_submodules", autospec=True, return_value=False)
        mock_git.side_effect = [
            _ok(stdout="abc123"),  # rev-parse HEAD (before)
            _ok(),  # fetch
            _ok(),  # pull --rebase
            _ok(stdout="abc123"),  # rev-parse HEAD (after)
        ]

        # When
        ctx = typer.Context(click.Command("pull"))
        pull(ctx=ctx, verbose=0, dry_run=False)

        # Then
        calls = list(mock_git.call_args_list)
        stash_calls = [c for c in calls if "stash" in c.args]
        assert len(stash_calls) == 0

    def test_stash_pop_failure_warns_and_exits(
        self,
        mocker,
        mock_check_git_repo,
        mock_current_branch,
        mock_tracking_branch,
        mock_git,
        capsys,
    ):
        """Verify warning about stashed changes when pop fails."""
        # Given
        mocker.patch("gx.commands.pull.is_dirty", autospec=True, return_value=True)
        mocker.patch("gx.commands.pull.has_submodules", autospec=True, return_value=False)
        mock_git.side_effect = [
            _ok(),  # stash --include-untracked
            _ok(stdout="abc123"),  # rev-parse HEAD (before)
            _ok(),  # fetch
            _ok(),  # pull --rebase
            _fail(),  # stash pop fails
        ]

        # When
        ctx = typer.Context(click.Command("pull"))
        with pytest.raises(typer.Exit):
            pull(ctx=ctx, verbose=0, dry_run=False)

        # Then
        captured = capsys.readouterr()
        assert "stashed changes" in captured.err


class TestPullFetchAndRebase:
    """Tests for fetch and rebase behavior."""

    def test_fetch_failure_triggers_rollback(
        self,
        mocker,
        mock_check_git_repo,
        mock_current_branch,
        mock_tracking_branch,
        mock_git,
    ):
        """Verify rollback restores stash when fetch fails on dirty tree."""
        # Given
        mocker.patch("gx.commands.pull.is_dirty", autospec=True, return_value=True)
        mock_git.side_effect = [
            _ok(),  # stash --include-untracked
            _ok(stdout="abc123"),  # rev-parse HEAD (before)
            _fail(),  # fetch fails
            _ok(),  # stash pop (rollback)
        ]

        # When
        ctx = typer.Context(click.Command("pull"))
        with pytest.raises(typer.Exit):
            pull(ctx=ctx, verbose=0, dry_run=False)

        # Then - stash pop was called as part of rollback
        calls = list(mock_git.call_args_list)
        stash_pop_calls = [c for c in calls if "stash" in c.args and "pop" in c.args]
        assert len(stash_pop_calls) == 1

    def test_pull_failure_triggers_rollback(
        self,
        mocker,
        mock_check_git_repo,
        mock_current_branch,
        mock_tracking_branch,
        mock_git,
        capsys,
    ):
        """Verify error message when pull --rebase fails on clean tree."""
        # Given
        mocker.patch("gx.commands.pull.is_dirty", autospec=True, return_value=False)
        mocker.patch("gx.commands.pull.is_rebase_in_progress", autospec=True, return_value=False)
        mock_git.side_effect = [
            _ok(stdout="abc123"),  # rev-parse HEAD (before)
            _ok(),  # fetch
            _fail(),  # pull --rebase fails
        ]

        # When
        ctx = typer.Context(click.Command("pull"))
        with pytest.raises(typer.Exit):
            pull(ctx=ctx, verbose=0, dry_run=False)

        # Then
        captured = capsys.readouterr()
        assert "Failed to pull" in captured.err

    def test_rebase_conflict_shows_guidance(
        self,
        mocker,
        mock_check_git_repo,
        mock_current_branch,
        mock_tracking_branch,
        mock_git,
        capsys,
    ):
        """Verify rebase conflict guidance is shown when rebase is in progress."""
        # Given
        mocker.patch("gx.commands.pull.is_dirty", autospec=True, return_value=False)
        mocker.patch("gx.commands.pull.is_rebase_in_progress", autospec=True, return_value=True)
        mock_git.side_effect = [
            _ok(stdout="abc123"),  # rev-parse HEAD (before)
            _ok(),  # fetch
            _fail(),  # pull --rebase fails
        ]

        # When
        ctx = typer.Context(click.Command("pull"))
        with pytest.raises(typer.Exit):
            pull(ctx=ctx, verbose=0, dry_run=False)

        # Then
        captured = capsys.readouterr()
        assert "rebase --continue" in captured.err
        assert "rebase --abort" in captured.err


class TestPullSubmodules:
    """Tests for submodule update behavior."""

    def test_updates_submodules_when_present(
        self,
        mocker,
        mock_check_git_repo,
        mock_current_branch,
        mock_tracking_branch,
        mock_git,
    ):
        """Verify submodule update is called when .gitmodules exists."""
        # Given
        mocker.patch("gx.commands.pull.is_dirty", autospec=True, return_value=False)
        mocker.patch("gx.commands.pull.has_submodules", autospec=True, return_value=True)
        mock_git.side_effect = [
            _ok(stdout="abc123"),  # rev-parse HEAD (before)
            _ok(),  # fetch
            _ok(),  # pull --rebase
            _ok(),  # submodule update
            _ok(stdout="abc123"),  # rev-parse HEAD (after)
        ]

        # When
        ctx = typer.Context(click.Command("pull"))
        pull(ctx=ctx, verbose=0, dry_run=False)

        # Then
        calls = list(mock_git.call_args_list)
        submodule_calls = [c for c in calls if "submodule" in c.args]
        assert len(submodule_calls) == 1

    def test_skips_submodules_when_absent(
        self,
        mocker,
        mock_check_git_repo,
        mock_current_branch,
        mock_tracking_branch,
        mock_git,
    ):
        """Verify no submodule calls when .gitmodules does not exist."""
        # Given
        mocker.patch("gx.commands.pull.is_dirty", autospec=True, return_value=False)
        mocker.patch("gx.commands.pull.has_submodules", autospec=True, return_value=False)
        mock_git.side_effect = [
            _ok(stdout="abc123"),  # rev-parse HEAD (before)
            _ok(),  # fetch
            _ok(),  # pull --rebase
            _ok(stdout="abc123"),  # rev-parse HEAD (after)
        ]

        # When
        ctx = typer.Context(click.Command("pull"))
        pull(ctx=ctx, verbose=0, dry_run=False)

        # Then
        calls = list(mock_git.call_args_list)
        submodule_calls = [c for c in calls if "submodule" in c.args]
        assert len(submodule_calls) == 0

    def test_submodule_failure_triggers_rollback(
        self,
        mocker,
        mock_check_git_repo,
        mock_current_branch,
        mock_tracking_branch,
        mock_git,
        capsys,
    ):
        """Verify error on submodule update failure."""
        # Given
        mocker.patch("gx.commands.pull.is_dirty", autospec=True, return_value=False)
        mocker.patch("gx.commands.pull.has_submodules", autospec=True, return_value=True)
        mock_git.side_effect = [
            _ok(stdout="abc123"),  # rev-parse HEAD (before)
            _ok(),  # fetch
            _ok(),  # pull --rebase
            _fail(),  # submodule update fails
        ]

        # When
        ctx = typer.Context(click.Command("pull"))
        with pytest.raises(typer.Exit):
            pull(ctx=ctx, verbose=0, dry_run=False)

        # Then
        captured = capsys.readouterr()
        assert "Failed to update submodules" in captured.err


class TestPullSummary:
    """Tests for pull summary output."""

    def test_shows_new_commits(
        self,
        mocker,
        mock_check_git_repo,
        mock_current_branch,
        mock_tracking_branch,
        mock_git,
        capsys,
    ):
        """Verify commit list is displayed when new commits are pulled."""
        # Given
        mocker.patch("gx.commands.pull.is_dirty", autospec=True, return_value=False)
        mocker.patch("gx.commands.pull.has_submodules", autospec=True, return_value=False)
        mock_git.side_effect = [
            _ok(stdout="abc123"),  # rev-parse HEAD (before)
            _ok(),  # fetch
            _ok(),  # pull --rebase
            _ok(stdout="def456"),  # rev-parse HEAD (after)
            _ok(stdout="def456 Add feature\nabc124 Fix bug"),  # log
        ]

        # When
        ctx = typer.Context(click.Command("pull"))
        pull(ctx=ctx, verbose=0, dry_run=False)

        # Then
        captured = capsys.readouterr()
        assert "2 new commit(s)" in captured.out
        assert "Add feature" in captured.out
        assert "Fix bug" in captured.out

    def test_shows_already_up_to_date(
        self,
        mocker,
        mock_check_git_repo,
        mock_current_branch,
        mock_tracking_branch,
        mock_git,
        capsys,
    ):
        """Verify 'Already up to date' message when HEAD is unchanged."""
        # Given
        mocker.patch("gx.commands.pull.is_dirty", autospec=True, return_value=False)
        mocker.patch("gx.commands.pull.has_submodules", autospec=True, return_value=False)
        mock_git.side_effect = [
            _ok(stdout="abc123"),  # rev-parse HEAD (before)
            _ok(),  # fetch
            _ok(),  # pull --rebase
            _ok(stdout="abc123"),  # rev-parse HEAD (after, same)
        ]

        # When
        ctx = typer.Context(click.Command("pull"))
        pull(ctx=ctx, verbose=0, dry_run=False)

        # Then
        captured = capsys.readouterr()
        assert "Already up to date" in captured.out


class TestIsDirty:
    """Tests for the _is_dirty helper function."""

    def test_dirty_when_changes_exist(self, tmp_git_repo):
        """Verify is_dirty returns True when working tree has changes."""
        make_tmp_dirty(tmp_git_repo)
        assert is_dirty() is True

    def test_clean_when_no_changes(self, tmp_git_repo):
        """Verify is_dirty returns False when working tree is clean."""
        assert is_dirty() is False


class TestHasSubmodules:
    """Tests for the _has_submodules helper function."""

    def test_true_when_gitmodules_exists(self, tmp_path, monkeypatch):
        """Verify _has_submodules returns True when .gitmodules file exists."""
        # Given a repo root with .git and .gitmodules
        (tmp_path / ".git").mkdir()
        (tmp_path / ".gitmodules").touch()
        monkeypatch.chdir(tmp_path)

        # When
        result = has_submodules()

        # Then
        assert result is True

    def test_false_when_no_gitmodules(self, tmp_path, monkeypatch):
        """Verify _has_submodules returns False when no .gitmodules file."""
        # Given a repo root with .git but no .gitmodules
        (tmp_path / ".git").mkdir()
        monkeypatch.chdir(tmp_path)

        # When
        result = has_submodules()

        # Then
        assert result is False


class TestIsRebaseInProgress:
    """Tests for the _is_rebase_in_progress helper function."""

    def test_true_when_rebase_merge_exists(self, mock_git, tmp_path):
        """Verify True when rebase-merge directory exists."""
        # Given
        (tmp_path / "rebase-merge").mkdir()
        mock_git.return_value = _ok(stdout=str(tmp_path))

        # When
        result = is_rebase_in_progress()

        # Then
        assert result is True

    def test_true_when_rebase_apply_exists(self, mock_git, tmp_path):
        """Verify True when rebase-apply directory exists."""
        # Given
        (tmp_path / "rebase-apply").mkdir()
        mock_git.return_value = _ok(stdout=str(tmp_path))

        # When
        result = is_rebase_in_progress()

        # Then
        assert result is True

    def test_false_when_no_rebase_dirs(self, mock_git, tmp_path):
        """Verify False when no rebase directories exist."""
        # Given
        mock_git.return_value = _ok(stdout=str(tmp_path))

        # When
        result = is_rebase_in_progress()

        # Then
        assert result is False


class TestPullDryRun:
    """Tests for pull command dry-run mode."""

    def test_dry_run_skips_mutating_commands(
        self,
        mocker,
        mock_check_git_repo,
        mock_current_branch,
        mock_tracking_branch,
        mock_git,
    ):
        """Verify all git calls are made in dry-run mode with dirty tree."""
        # Given
        mocker.patch("gx.commands.pull.is_dirty", autospec=True, return_value=True)
        mocker.patch("gx.commands.pull.has_submodules", autospec=True, return_value=False)
        mock_git.side_effect = [
            _ok(),  # stash --include-untracked
            _ok(stdout="abc123"),  # rev-parse HEAD (before)
            _ok(),  # fetch
            _ok(),  # pull --rebase
            _ok(),  # stash pop
            _ok(stdout="abc123"),  # rev-parse HEAD (after)
        ]

        # When
        ctx = typer.Context(click.Command("pull"))
        pull(ctx=ctx, verbose=0, dry_run=True)

        # Then
        assert mock_git.call_count == 6
        call_args = [c.args for c in mock_git.call_args_list]
        assert ("stash", "--include-untracked") in call_args
        assert ("fetch", "origin") in call_args
        assert ("pull", "--rebase", "origin", "main") in call_args
        assert ("stash", "pop") in call_args

    def test_dry_run_still_detects_guards(
        self,
        mocker,
        mock_check_git_repo,
        mock_tracking_branch,
        capsys,
    ):
        """Verify guard rails still trigger in dry-run mode."""
        # Given
        mocker.patch("gx.commands.pull.current_branch", autospec=True, return_value=None)

        # When
        ctx = typer.Context(click.Command("pull"))
        with pytest.raises(typer.Exit):
            pull(ctx=ctx, verbose=0, dry_run=True)

        # Then
        captured = capsys.readouterr()
        assert "detached HEAD" in captured.err
