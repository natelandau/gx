"""Tests for gx done command."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import typer
from typer.core import TyperCommand

from gx.commands.done import done
from gx.lib.worktree import WorktreeInfo

from .conftest import _fail, _ok

if TYPE_CHECKING:
    from unittest.mock import Mock


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
        ctx = typer.Context(TyperCommand("done"))
        with pytest.raises(typer.Exit):
            done(ctx=ctx, verbose=0, dry_run=False, force=False)

        # Then
        captured = capsys.readouterr()
        assert "Already on the default branch" in captured.err
        assert "gx pull && gx clean" in captured.err

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
        ctx = typer.Context(TyperCommand("done"))
        with pytest.raises(typer.Exit):
            done(ctx=ctx, verbose=0, dry_run=False, force=False)

        # Then
        captured = capsys.readouterr()
        assert "detached HEAD" in captured.err


def _delete_calls() -> list:
    """Return the standard happy-path git side-effect chain for branch deletion.

    Sequence: checkout target → rev-parse HEAD (for pre-pull diff summary) → branch -D.
    Tests where _verify_merged also fetches should prepend an extra _ok().
    """
    return [_ok(), _ok(stdout="abc"), _ok()]


def _patch_verification(
    mocker,
    *,
    state: str | None = "MERGED",
    is_gone_value: bool = False,
    is_merged_value: bool = False,
    confirm: bool = True,
) -> Mock:
    """Patch the merge verification dependencies on gx.commands.done.

    Defaults to a merged-PR (gh MERGED) signal so verification passes silently.
    Override per-test for the specific verification path under test.
    """
    mocker.patch("gx.commands.done.pr_state", autospec=True, return_value=state)
    gone_set = frozenset({"feature-x"}) if is_gone_value else frozenset()
    merged_set = frozenset({"feature-x"}) if is_merged_value else frozenset()
    mocker.patch("gx.commands.done.gone_branches", autospec=True, return_value=gone_set)
    mocker.patch("gx.commands.done.merged_branches", autospec=True, return_value=merged_set)
    return mocker.patch("gx.commands.done.Confirm.ask", autospec=True, return_value=confirm)


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
        _patch_verification(mocker, state="MERGED")
        mocker.patch(
            "gx.commands.done.validate_branch",
            autospec=True,
            return_value=("main", "origin", "main"),
        )
        mocker.patch("gx.commands.done.stash_if_dirty", autospec=True, return_value=False)
        mocker.patch("gx.commands.done.fetch_and_rebase", autospec=True)
        mocker.patch("gx.commands.done.update_submodules", autospec=True)
        mocker.patch("gx.commands.done.unstash", autospec=True)
        mocker.patch("gx.commands.done.print_pull_summary", autospec=True)
        mock_git = mocker.patch("gx.commands.done.git", autospec=True)
        mock_git.side_effect = [
            _ok(),  # checkout main
            _ok(stdout="abc"),  # rev-parse HEAD (before)
            _ok(),  # branch -D feature-x
        ]

        # When
        ctx = typer.Context(TyperCommand("done"))
        done(ctx=ctx, verbose=0, dry_run=False, force=False)

        # Then — gh MERGED skips the verification fetch
        calls = [c.args for c in mock_git.call_args_list]
        assert ("fetch", "--prune") not in calls
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
        _patch_verification(mocker, state="MERGED")
        mocker.patch(
            "gx.commands.done.validate_branch",
            autospec=True,
            return_value=("main", "origin", "main"),
        )
        mocker.patch("gx.commands.done.stash_if_dirty", autospec=True, return_value=False)
        mocker.patch("gx.commands.done.fetch_and_rebase", autospec=True)
        mocker.patch("gx.commands.done.update_submodules", autospec=True)
        mocker.patch("gx.commands.done.unstash", autospec=True)
        mocker.patch("gx.commands.done.print_pull_summary", autospec=True)
        mock_git = mocker.patch("gx.commands.done.git", autospec=True)
        mock_git.side_effect = [
            _ok(),  # checkout main
            _ok(stdout="abc"),  # rev-parse HEAD (before)
            _fail(stderr="not fully merged"),  # branch -D fails
        ]

        # When — should NOT raise
        ctx = typer.Context(TyperCommand("done"))
        done(ctx=ctx, verbose=0, dry_run=False, force=False)

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
        _patch_verification(mocker, state="MERGED")
        mocker.patch(
            "gx.commands.done.validate_branch",
            autospec=True,
            return_value=("main", "origin", "main"),
        )
        mocker.patch("gx.commands.done.stash_if_dirty", autospec=True, return_value=False)
        mocker.patch("gx.commands.done.fetch_and_rebase", autospec=True)
        mocker.patch("gx.commands.done.update_submodules", autospec=True)
        mocker.patch("gx.commands.done.unstash", autospec=True)
        mocker.patch("gx.commands.done.print_pull_summary", autospec=True)

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
        ctx = typer.Context(TyperCommand("done"))
        done(ctx=ctx, verbose=0, dry_run=False, force=False)

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
        ctx = typer.Context(TyperCommand("done"))
        with pytest.raises(typer.Exit):
            done(ctx=ctx, verbose=0, dry_run=False, force=False)

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
        _patch_verification(mocker, state="MERGED")

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

        # gh MERGED makes _verify_merged a no-op, so no git calls run before failure
        mocker.patch("gx.commands.done.git", autospec=True)

        # When
        ctx = typer.Context(TyperCommand("done"))
        with pytest.raises(typer.Exit):
            done(ctx=ctx, verbose=0, dry_run=False, force=False)

        # Then
        captured = capsys.readouterr()
        assert "Failed to remove worktree" in captured.err


class TestDoneVerification:
    """Tests for the merge-verification chain (gh → is_gone → is_merged → prompt)."""

    @staticmethod
    def _common_mocks(mocker) -> None:
        """Patch shared fixtures used by every verification test."""
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
        mocker.patch("gx.commands.done.print_pull_summary", autospec=True)

    def test_force_skips_merge_verification(self, mocker, capsys):
        """Verify --force bypasses pr_state, is_gone, and is_merged checks."""
        # Given
        self._common_mocks(mocker)
        mock_pr_state = mocker.patch("gx.commands.done.pr_state", autospec=True)
        mock_gone = mocker.patch("gx.commands.done.gone_branches", autospec=True)
        mock_merged = mocker.patch("gx.commands.done.merged_branches", autospec=True)
        mock_confirm = mocker.patch("gx.commands.done.Confirm.ask", autospec=True)
        mock_git = mocker.patch("gx.commands.done.git", autospec=True)
        mock_git.side_effect = _delete_calls()

        # When
        ctx = typer.Context(TyperCommand("done"))
        done(ctx=ctx, verbose=0, dry_run=False, force=True)

        # Then — none of the verification helpers were consulted
        mock_pr_state.assert_not_called()
        mock_gone.assert_not_called()
        mock_merged.assert_not_called()
        mock_confirm.assert_not_called()
        calls = [c.args for c in mock_git.call_args_list]
        assert ("fetch", "--prune") not in calls
        assert ("branch", "-D", "feature-x") in calls

    def test_pr_merged_proceeds_without_prompt(self, mocker):
        """Verify gh state MERGED proceeds with deletion and never prompts or fetches."""
        # Given
        self._common_mocks(mocker)
        mock_confirm = _patch_verification(mocker, state="MERGED")
        mock_git = mocker.patch("gx.commands.done.git", autospec=True)
        mock_git.side_effect = _delete_calls()

        # When
        ctx = typer.Context(TyperCommand("done"))
        done(ctx=ctx, verbose=0, dry_run=False, force=False)

        # Then — gh was authoritative, so no fetch was needed
        calls = [c.args for c in mock_git.call_args_list]
        mock_confirm.assert_not_called()
        assert ("fetch", "--prune") not in calls
        assert ("branch", "-D", "feature-x") in calls

    def test_pr_open_prompt_decline_aborts(self, mocker, capsys):
        """Verify gh state OPEN with declined prompt aborts before deletion."""
        # Given gh reports OPEN (no fetch — gh is authoritative) and user declines
        self._common_mocks(mocker)
        _patch_verification(mocker, state="OPEN", confirm=False)
        mocker.patch("gx.commands.done.ahead_behind", autospec=True, return_value=(3, 0))
        mock_git = mocker.patch("gx.commands.done.git", autospec=True)

        # When
        ctx = typer.Context(TyperCommand("done"))
        with pytest.raises(typer.Exit):
            done(ctx=ctx, verbose=0, dry_run=False, force=False)

        # Then — no destructive ops
        mock_git.assert_not_called()

    def test_pr_open_prompt_accept_proceeds(self, mocker):
        """Verify gh state OPEN with accepted prompt proceeds with deletion."""
        # Given
        self._common_mocks(mocker)
        _patch_verification(mocker, state="OPEN", confirm=True)
        mocker.patch("gx.commands.done.ahead_behind", autospec=True, return_value=(3, 0))
        mock_git = mocker.patch("gx.commands.done.git", autospec=True)
        mock_git.side_effect = _delete_calls()

        # When
        ctx = typer.Context(TyperCommand("done"))
        done(ctx=ctx, verbose=0, dry_run=False, force=False)

        # Then
        assert ("branch", "-D", "feature-x") in [c.args for c in mock_git.call_args_list]

    def test_no_gh_is_gone_proceeds(self, mocker):
        """Verify when gh unavailable but upstream is gone, deletion proceeds without prompt."""
        # Given pr_state None and is_gone True — fetch runs, then is_gone confirms
        self._common_mocks(mocker)
        mock_confirm = _patch_verification(mocker, state=None, is_gone_value=True)
        mock_git = mocker.patch("gx.commands.done.git", autospec=True)
        mock_git.side_effect = [_ok(), *_delete_calls()]

        # When
        ctx = typer.Context(TyperCommand("done"))
        done(ctx=ctx, verbose=0, dry_run=False, force=False)

        # Then
        calls = [c.args for c in mock_git.call_args_list]
        mock_confirm.assert_not_called()
        assert ("fetch", "--prune") in calls
        assert ("branch", "-D", "feature-x") in calls

    def test_no_gh_is_merged_proceeds(self, mocker):
        """Verify when gh unavailable but branch is merged, deletion proceeds without prompt."""
        # Given pr_state None, is_gone False, is_merged True
        self._common_mocks(mocker)
        mock_confirm = _patch_verification(
            mocker, state=None, is_gone_value=False, is_merged_value=True
        )
        mock_git = mocker.patch("gx.commands.done.git", autospec=True)
        mock_git.side_effect = [_ok(), *_delete_calls()]

        # When
        ctx = typer.Context(TyperCommand("done"))
        done(ctx=ctx, verbose=0, dry_run=False, force=False)

        # Then
        mock_confirm.assert_not_called()
        assert ("branch", "-D", "feature-x") in [c.args for c in mock_git.call_args_list]

    def test_no_signal_prompt_decline_aborts(self, mocker, capsys):
        """Verify when no merge signal exists and user declines, deletion is aborted."""
        # Given
        self._common_mocks(mocker)
        _patch_verification(
            mocker, state=None, is_gone_value=False, is_merged_value=False, confirm=False
        )
        mocker.patch("gx.commands.done.ahead_behind", autospec=True, return_value=(2, 0))
        mock_git = mocker.patch("gx.commands.done.git", autospec=True)
        mock_git.side_effect = [_ok()]  # only the verification fetch

        # When
        ctx = typer.Context(TyperCommand("done"))
        with pytest.raises(typer.Exit):
            done(ctx=ctx, verbose=0, dry_run=False, force=False)

        # Then
        calls = [c.args for c in mock_git.call_args_list]
        assert ("branch", "-D", "feature-x") not in calls

    def test_no_signal_prompt_accept_proceeds(self, mocker):
        """Verify when no merge signal exists and user accepts, deletion proceeds."""
        # Given
        self._common_mocks(mocker)
        _patch_verification(
            mocker, state=None, is_gone_value=False, is_merged_value=False, confirm=True
        )
        mocker.patch("gx.commands.done.ahead_behind", autospec=True, return_value=(2, 0))
        mock_git = mocker.patch("gx.commands.done.git", autospec=True)
        mock_git.side_effect = [_ok(), *_delete_calls()]

        # When
        ctx = typer.Context(TyperCommand("done"))
        done(ctx=ctx, verbose=0, dry_run=False, force=False)

        # Then
        assert ("branch", "-D", "feature-x") in [c.args for c in mock_git.call_args_list]

    def test_dirty_worktree_check_runs_even_with_force(self, mocker, tmp_path, capsys):
        """Verify --force does not bypass the dirty-worktree safety check."""
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

        # When --force is set but worktree is dirty
        ctx = typer.Context(TyperCommand("done"))
        with pytest.raises(typer.Exit):
            done(ctx=ctx, verbose=0, dry_run=False, force=True)

        # Then
        captured = capsys.readouterr()
        assert "uncommitted changes" in captured.err

    def test_prompt_message_is_platform_agnostic(self, mocker, capsys):
        """Verify the no-signal prompt message does not mention PR state or platform."""
        # Given gh reports OPEN — verification falls through to prompt
        self._common_mocks(mocker)
        mock_confirm = _patch_verification(mocker, state="OPEN", confirm=True)
        mocker.patch("gx.commands.done.ahead_behind", autospec=True, return_value=(5, 0))
        mock_git = mocker.patch("gx.commands.done.git", autospec=True)
        mock_git.side_effect = _delete_calls()

        # When
        ctx = typer.Context(TyperCommand("done"))
        done(ctx=ctx, verbose=0, dry_run=False, force=False)

        # Then — message mentions branch, count, and target only
        prompt_message = mock_confirm.call_args.args[0]
        assert "feature-x" in prompt_message
        assert "5" in prompt_message
        assert "main" in prompt_message
        assert "PR" not in prompt_message
        assert "OPEN" not in prompt_message
        assert "GitHub" not in prompt_message
        assert "gh" not in prompt_message
