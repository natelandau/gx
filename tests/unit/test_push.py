"""Tests for gx push command."""

from __future__ import annotations

import click
import pytest
import typer

from gx.commands.push import (
    _count_dirty_files,
    _print_summary,
    _resolve_push_target,
    _warn_dirty_tree,
    push,
)
from tests.conftest import create_tmp_commit

from .conftest import _fail, _ok


class TestCountDirtyFiles:
    """Tests for the _count_dirty_files helper function."""

    def test_both_modified_and_untracked(self, tmp_git_repo):
        """Verify correct counts when both modified and untracked files exist."""
        # Given a committed file then modified, plus an untracked file
        create_tmp_commit(tmp_git_repo, "initial", "tracked.txt")
        (tmp_git_repo / "tracked.txt").write_text("modified")
        (tmp_git_repo / "new.txt").write_text("untracked")

        modified, untracked = _count_dirty_files()
        assert modified == 1
        assert untracked == 1

    def test_clean_tree(self, tmp_git_repo):
        """Verify zero counts on a clean working tree."""
        modified, untracked = _count_dirty_files()
        assert modified == 0
        assert untracked == 0


class TestResolvePushTarget:
    """Tests for the _resolve_push_target helper function."""

    def test_uses_tracking_branch_when_configured(self, mock_push_tracking_branch):
        """Verify returns tracking branch remote and branch when upstream is set."""
        # Given
        mock_push_tracking_branch.return_value = ("upstream", "my-feature")

        # When
        remote, branch = _resolve_push_target("feature")

        # Then
        assert remote == "upstream"
        assert branch == "my-feature"

    def test_falls_back_to_origin_when_no_upstream(self, mock_push_tracking_branch):
        """Verify falls back to origin and given branch name when no upstream."""
        # Given
        mock_push_tracking_branch.return_value = None

        # When
        remote, branch = _resolve_push_target("new-feature")

        # Then
        assert remote == "origin"
        assert branch == "new-feature"


class TestWarnDirtyTree:
    """Tests for dirty tree warning message formatting."""

    def test_warns_both_modified_and_untracked(self, mocker, capsys):
        """Verify warning shows both counts when both are nonzero."""
        # Given
        mocker.patch("gx.commands.push._count_dirty_files", autospec=True, return_value=(3, 2))

        # When
        _warn_dirty_tree()

        # Then
        captured = capsys.readouterr()
        assert "3 modified" in captured.err
        assert "2 untracked" in captured.err

    def test_warns_only_modified(self, mocker, capsys):
        """Verify warning shows only modified count when no untracked files."""
        # Given
        mocker.patch("gx.commands.push._count_dirty_files", autospec=True, return_value=(3, 0))

        # When
        _warn_dirty_tree()

        # Then
        captured = capsys.readouterr()
        assert "3 modified" in captured.err
        assert "untracked" not in captured.err

    def test_warns_only_untracked(self, mocker, capsys):
        """Verify warning shows only untracked count when no modified files."""
        # Given
        mocker.patch("gx.commands.push._count_dirty_files", autospec=True, return_value=(0, 2))

        # When
        _warn_dirty_tree()

        # Then
        captured = capsys.readouterr()
        assert "modified" not in captured.err
        assert "2 untracked" in captured.err

    def test_no_warning_when_clean(self, mocker, capsys):
        """Verify no warning when working tree is clean."""
        # Given
        mocker.patch("gx.commands.push._count_dirty_files", autospec=True, return_value=(0, 0))

        # When
        _warn_dirty_tree()

        # Then
        captured = capsys.readouterr()
        assert captured.err == ""


class TestPrintPushSummary:
    """Tests for push summary output."""

    def test_shows_pushed_commits(self, mock_push_git, capsys):
        """Verify commit list is displayed when commits were pushed."""
        # Given
        mock_push_git.return_value = _ok(stdout="abc1234 feat: add widget\ndef5678 fix: edge case")

        # When
        _print_summary(
            remote_ref_before="aaa111", remote="origin", remote_branch="main", default="main"
        )

        # Then
        captured = capsys.readouterr()
        assert "Push 2 commit(s)" in captured.out
        assert "origin/main" in captured.out
        assert "add widget" in captured.out
        assert "edge case" in captured.out

    def test_returns_silently_when_no_commits(self, mock_push_git, capsys):
        """Verify no output when there are no commits to show."""
        # Given
        mock_push_git.return_value = _ok(stdout="")

        # When
        _print_summary(
            remote_ref_before="aaa111", remote="origin", remote_branch="main", default="main"
        )

        # Then
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_first_push_uses_default_branch_range(self, mock_push_git, capsys):
        """Verify first push (no remote ref) uses default branch..HEAD range."""
        # Given
        mock_push_git.return_value = _ok(stdout="abc1234 initial commit")

        # When
        _print_summary(
            remote_ref_before=None, remote="origin", remote_branch="new-feature", default="main"
        )

        # Then
        captured = capsys.readouterr()
        assert "1 commit(s)" in captured.out
        call_args = mock_push_git.call_args
        assert "main..HEAD" in call_args.args[-1]


class TestPushGuardRails:
    """Tests for push command guard rail checks."""

    def test_detached_head_aborts(self, mocker, mock_push_check_git_repo, capsys):
        """Verify push aborts with error when in detached HEAD state."""
        # Given
        mocker.patch("gx.commands.push.current_branch", autospec=True, return_value=None)

        # When
        ctx = typer.Context(click.Command("push"))
        with pytest.raises(typer.Exit):
            push(ctx=ctx, verbose=0, dry_run=False, force=False, tags=False)

        # Then
        captured = capsys.readouterr()
        assert "detached HEAD" in captured.err

    def test_default_branch_prompts_confirmation(
        self, mocker, mock_push_check_git_repo, mock_push_git, mock_push_default_branch
    ):
        """Verify push to default branch prompts for confirmation."""
        # Given
        mocker.patch("gx.commands.push.current_branch", autospec=True, return_value="main")
        mock_confirm = mocker.patch(
            "gx.commands.push.Confirm.ask", autospec=True, return_value=False
        )

        # When
        ctx = typer.Context(click.Command("push"))
        with pytest.raises(typer.Exit):
            push(ctx=ctx, verbose=0, dry_run=False, force=False, tags=False)

        # Then
        mock_confirm.assert_called_once()

    def test_force_skips_default_branch_prompt(
        self,
        mocker,
        mock_push_check_git_repo,
        mock_push_git,
        mock_push_default_branch,
        mock_push_tracking_branch,
    ):
        """Verify --force bypasses the default branch confirmation prompt."""
        # Given
        mocker.patch("gx.commands.push.current_branch", autospec=True, return_value="main")
        mocker.patch("gx.commands.push._count_dirty_files", autospec=True, return_value=(0, 0))
        mock_confirm = mocker.patch("gx.commands.push.Confirm.ask", autospec=True)
        mock_push_git.side_effect = [
            _ok(stdout="abc123"),  # rev-parse remote ref
            _ok(),  # push
            _ok(stdout=""),  # log (summary)
        ]

        # When
        ctx = typer.Context(click.Command("push"))
        push(ctx=ctx, verbose=0, dry_run=False, force=True, tags=False)

        # Then
        mock_confirm.assert_not_called()


class TestPushExecution:
    """Tests for the core push execution."""

    def test_push_with_upstream(
        self,
        mocker,
        mock_push_check_git_repo,
        mock_push_current_branch,
        mock_push_default_branch,
        mock_push_tracking_branch,
        mock_push_git,
        capsys,
    ):
        """Verify push sends correct command when upstream is configured."""
        # Given
        mocker.patch("gx.commands.push._count_dirty_files", autospec=True, return_value=(0, 0))
        mock_push_git.side_effect = [
            _ok(stdout="abc123"),  # rev-parse remote ref
            _ok(),  # push
            _ok(stdout="abc1234 feat: new thing"),  # log (summary)
        ]

        # When
        ctx = typer.Context(click.Command("push"))
        push(ctx=ctx, verbose=0, dry_run=False, force=False, tags=False)

        # Then
        push_call = mock_push_git.call_args_list[1]
        assert "push" in push_call.args
        assert "--set-upstream" in push_call.args
        assert "origin" in push_call.args
        assert "feature" in push_call.args

    def test_push_with_force_uses_force_with_lease(
        self,
        mocker,
        mock_push_check_git_repo,
        mock_push_current_branch,
        mock_push_default_branch,
        mock_push_tracking_branch,
        mock_push_git,
    ):
        """Verify --force maps to --force-with-lease in git command."""
        # Given
        mocker.patch("gx.commands.push._count_dirty_files", autospec=True, return_value=(0, 0))
        mock_push_git.side_effect = [
            _ok(stdout="abc123"),  # rev-parse remote ref
            _ok(),  # push
            _ok(stdout=""),  # log (summary)
        ]

        # When
        ctx = typer.Context(click.Command("push"))
        push(ctx=ctx, verbose=0, dry_run=False, force=True, tags=False)

        # Then
        push_call = mock_push_git.call_args_list[1]
        assert "--force-with-lease" in push_call.args

    def test_push_with_tags(
        self,
        mocker,
        mock_push_check_git_repo,
        mock_push_current_branch,
        mock_push_default_branch,
        mock_push_tracking_branch,
        mock_push_git,
    ):
        """Verify --tags is passed through to git push."""
        # Given
        mocker.patch("gx.commands.push._count_dirty_files", autospec=True, return_value=(0, 0))
        mock_push_git.side_effect = [
            _ok(stdout="abc123"),  # rev-parse remote ref
            _ok(),  # push
            _ok(stdout=""),  # log (summary)
        ]

        # When
        ctx = typer.Context(click.Command("push"))
        push(ctx=ctx, verbose=0, dry_run=False, force=False, tags=True)

        # Then
        push_call = mock_push_git.call_args_list[1]
        assert "--tags" in push_call.args

    def test_push_failure_exits(
        self,
        mocker,
        mock_push_check_git_repo,
        mock_push_current_branch,
        mock_push_default_branch,
        mock_push_tracking_branch,
        mock_push_git,
        capsys,
    ):
        """Verify exit with error when git push fails."""
        # Given
        mocker.patch("gx.commands.push._count_dirty_files", autospec=True, return_value=(0, 0))
        mock_push_git.side_effect = [
            _ok(stdout="abc123"),  # rev-parse remote ref
            _fail(stderr="rejected"),  # push fails
        ]

        # When
        ctx = typer.Context(click.Command("push"))
        with pytest.raises(typer.Exit):
            push(ctx=ctx, verbose=0, dry_run=False, force=False, tags=False)

        # Then
        captured = capsys.readouterr()
        assert "rejected" in captured.err

    def test_push_first_time_no_remote_ref(
        self,
        mocker,
        mock_push_check_git_repo,
        mock_push_default_branch,
        mock_push_git,
    ):
        """Verify push works when no remote ref exists (first push)."""
        # Given
        mocker.patch("gx.commands.push.tracking_branch", return_value=None)
        mocker.patch("gx.commands.push.current_branch", return_value="new-feature")
        mocker.patch("gx.commands.push._count_dirty_files", return_value=(0, 0))
        mock_push_git.side_effect = [
            _fail(),  # rev-parse remote ref (doesn't exist)
            _ok(),  # push
            _ok(stdout="abc1234 initial commit"),  # log (summary)
        ]

        # When
        ctx = typer.Context(click.Command("push"))
        push(ctx=ctx, verbose=0, dry_run=False, force=False, tags=False)

        # Then
        push_call = mock_push_git.call_args_list[1]
        assert "push" in push_call.args
        assert "--set-upstream" in push_call.args
        assert "origin" in push_call.args
        assert "new-feature" in push_call.args

    def test_dirty_tree_warns_but_continues(
        self,
        mocker,
        mock_push_check_git_repo,
        mock_push_current_branch,
        mock_push_default_branch,
        mock_push_tracking_branch,
        mock_push_git,
        capsys,
    ):
        """Verify dirty tree warning is shown but push still proceeds."""
        # Given
        mocker.patch("gx.commands.push._count_dirty_files", autospec=True, return_value=(2, 1))
        mock_push_git.side_effect = [
            _ok(stdout="abc123"),  # rev-parse remote ref
            _ok(),  # push
            _ok(stdout=""),  # log (summary)
        ]

        # When
        ctx = typer.Context(click.Command("push"))
        push(ctx=ctx, verbose=0, dry_run=False, force=False, tags=False)

        # Then
        captured = capsys.readouterr()
        assert "2 modified" in captured.err
        assert "1 untracked" in captured.err
        assert mock_push_git.call_count == 3


class TestPushDryRun:
    """Tests for push command dry-run mode."""

    def test_dry_run_shows_would_push(
        self,
        mocker,
        mock_push_check_git_repo,
        mock_push_current_branch,
        mock_push_default_branch,
        mock_push_tracking_branch,
        mock_push_git,
        capsys,
    ):
        """Verify dry-run uses 'Would push' wording in summary."""
        # Given
        mocker.patch("gx.commands.push._count_dirty_files", autospec=True, return_value=(0, 0))
        mock_push_git.side_effect = [
            _ok(stdout="abc123"),  # rev-parse remote ref
            _ok(),  # push (dry-run synthetic success)
            _ok(stdout="abc1234 feat: new thing"),  # log (summary)
        ]

        # When
        ctx = typer.Context(click.Command("push"))
        push(ctx=ctx, verbose=0, dry_run=True, force=False, tags=False)

        # Then
        captured = capsys.readouterr()
        assert "Would push" in captured.out
        assert "1 commit(s)" in captured.out
        assert mock_push_git.call_count == 3
