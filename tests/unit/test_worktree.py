"""Tests for gx worktree management utilities."""

from pathlib import Path

from gx.lib.git import GitResult
from tests.conftest import (
    create_tmp_commit,
    create_tmp_worktree,
    merge_tmp_branch,
)


class TestListWorktrees:
    """Tests for list_worktrees()."""

    def test_parses_main_and_feature_worktree(self, tmp_git_repo):
        """Verify list_worktrees() returns enriched data for multiple worktrees."""
        from gx.lib.worktree import list_worktrees

        wt_path = create_tmp_worktree(tmp_git_repo, "feature")
        create_tmp_commit(wt_path, "feature work")
        worktrees = list_worktrees()

        assert len(worktrees) == 2

        main_wt = next(w for w in worktrees if w.branch == "main")
        assert main_wt.is_main is True
        assert main_wt.is_merged is True
        assert main_wt.path == tmp_git_repo

        feat_wt = next(w for w in worktrees if w.branch == "feature")
        assert feat_wt.is_main is False
        assert feat_wt.is_merged is False
        assert feat_wt.is_gone is False

    def test_detects_merged_worktree(self, tmp_git_repo):
        """Verify list_worktrees() sets is_merged for merged branches."""
        from gx.lib.worktree import list_worktrees

        wt_path = create_tmp_worktree(tmp_git_repo, "feat-done")
        create_tmp_commit(wt_path, "feature work")
        merge_tmp_branch(tmp_git_repo, "feat-done", into="main")

        worktrees = list_worktrees()
        feat_wt = next(w for w in worktrees if w.branch == "feat-done")
        assert feat_wt.is_merged is True

    def test_returns_empty_list_on_failure(self, mocker):
        """Verify list_worktrees() returns empty list when git command fails."""
        mocker.patch(
            "gx.lib.worktree.git",
            return_value=GitResult(
                command="git worktree list --porcelain",
                returncode=1,
                stdout="",
                stderr="error",
            ),
        )
        from gx.lib.worktree import list_worktrees

        assert list_worktrees() == []


class TestCreateWorktree:
    """Tests for create_worktree()."""

    def test_creates_worktree_with_new_branch(self, mocker):
        """Verify create_worktree() calls git worktree add with -b flag."""
        mock_git = mocker.patch(
            "gx.lib.worktree.git",
            return_value=GitResult(
                command="git worktree add .worktrees/feat -b feat",
                returncode=0,
                stdout="Preparing worktree",
                stderr="",
            ),
        )
        from gx.lib.worktree import create_worktree

        result = create_worktree(Path(".worktrees/feat"), "feat")
        assert result.success is True
        mock_git.assert_called_once_with("worktree", "add", ".worktrees/feat", "-b", "feat")

    def test_returns_failure_on_error(self, mocker):
        """Verify create_worktree() returns failure result on error."""
        mocker.patch(
            "gx.lib.worktree.git",
            return_value=GitResult(
                command="git worktree add .worktrees/feat -b feat",
                returncode=128,
                stdout="",
                stderr="fatal: branch already exists",
            ),
        )
        from gx.lib.worktree import create_worktree

        result = create_worktree(Path(".worktrees/feat"), "feat")
        assert result.success is False

    def test_creates_worktree_with_start_point(self, mocker):
        """Verify create_worktree() passes start_point to git worktree add."""
        mock_git = mocker.patch(
            "gx.lib.worktree.git",
            return_value=GitResult(
                command="git worktree add .worktrees/feat/1 -b feat/1 main",
                returncode=0,
                stdout="Preparing worktree",
                stderr="",
            ),
        )
        from gx.lib.worktree import create_worktree

        result = create_worktree(Path(".worktrees/feat/1"), "feat/1", start_point="main")
        assert result.success is True
        mock_git.assert_called_once_with(
            "worktree", "add", ".worktrees/feat/1", "-b", "feat/1", "main"
        )


class TestRemoveWorktree:
    """Tests for remove_worktree()."""

    def test_removes_worktree(self, mocker):
        """Verify remove_worktree() calls git worktree remove."""
        mock_git = mocker.patch(
            "gx.lib.worktree.git",
            return_value=GitResult(
                command="git worktree remove .worktrees/feat",
                returncode=0,
                stdout="",
                stderr="",
            ),
        )
        from gx.lib.worktree import remove_worktree

        result = remove_worktree(Path(".worktrees/feat"))
        assert result.success is True
        mock_git.assert_called_once_with("worktree", "remove", ".worktrees/feat")

    def test_returns_failure_on_error(self, mocker):
        """Verify remove_worktree() returns failure result on error."""
        mocker.patch(
            "gx.lib.worktree.git",
            return_value=GitResult(
                command="git worktree remove .worktrees/feat",
                returncode=1,
                stdout="",
                stderr="fatal: not a worktree",
            ),
        )
        from gx.lib.worktree import remove_worktree

        result = remove_worktree(Path(".worktrees/feat"))
        assert result.success is False

    def test_force_removes_dirty_worktree(self, mocker):
        """Verify remove_worktree() passes --force when force=True."""
        mock_git = mocker.patch(
            "gx.lib.worktree.git",
            return_value=GitResult(
                command="git worktree remove --force .worktrees/feat",
                returncode=0,
                stdout="",
                stderr="",
            ),
        )
        from gx.lib.worktree import remove_worktree

        result = remove_worktree(Path(".worktrees/feat"), force=True)
        assert result.success is True
        mock_git.assert_called_once_with("worktree", "remove", "--force", ".worktrees/feat")
