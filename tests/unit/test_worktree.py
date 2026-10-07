"""Tests for gx worktree management utilities."""

from pathlib import Path

from tests.conftest import (
    _run_git,
    create_tmp_commit,
    create_tmp_worktree,
    merge_tmp_branch,
)
from tests.unit.conftest import _completed


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
            return_value=_completed(
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
            return_value=_completed(
                returncode=0,
                stdout="Preparing worktree",
                stderr="",
            ),
        )
        from gx.lib.worktree import create_worktree

        result = create_worktree(Path(".worktrees/feat"), "feat")
        assert result.ok is True
        mock_git.assert_called_with(
            "worktree", "add", "--no-track", "-b", "feat", ".worktrees/feat"
        )

    def test_returns_failure_on_error(self, mocker):
        """Verify create_worktree() returns failure result on error."""
        mocker.patch(
            "gx.lib.worktree.git",
            return_value=_completed(
                returncode=128,
                stdout="",
                stderr="fatal: branch already exists",
            ),
        )
        from gx.lib.worktree import create_worktree

        result = create_worktree(Path(".worktrees/feat"), "feat")
        assert result.ok is False

    def test_creates_worktree_with_start_point(self, mocker):
        """Verify create_worktree() passes start_point to git worktree add."""
        mock_git = mocker.patch(
            "gx.lib.worktree.git",
            return_value=_completed(
                returncode=0,
                stdout="Preparing worktree",
                stderr="",
            ),
        )
        from gx.lib.worktree import create_worktree

        result = create_worktree(Path(".worktrees/feat/1"), "feat/1", start_point="main")
        assert result.ok is True
        mock_git.assert_called_with(
            "worktree", "add", "--no-track", "-b", "feat/1", ".worktrees/feat/1", "main"
        )


class TestRemoveWorktree:
    """Tests for remove_worktree()."""

    def test_removes_worktree(self, mocker):
        """Verify remove_worktree() calls git worktree remove."""
        mock_git = mocker.patch(
            "gx.lib.worktree.git",
            return_value=_completed(
                returncode=0,
                stdout="",
                stderr="",
            ),
        )
        from gx.lib.worktree import remove_worktree

        result = remove_worktree(Path(".worktrees/feat"))
        assert result.ok is True
        mock_git.assert_called_once_with("worktree", "remove", ".worktrees/feat")

    def test_returns_failure_on_error(self, mocker):
        """Verify remove_worktree() returns failure result on error."""
        mocker.patch(
            "gx.lib.worktree.git",
            return_value=_completed(
                returncode=1,
                stdout="",
                stderr="fatal: not a worktree",
            ),
        )
        from gx.lib.worktree import remove_worktree

        result = remove_worktree(Path(".worktrees/feat"))
        assert result.ok is False

    def test_force_removes_dirty_worktree(self, mocker):
        """Verify remove_worktree() passes --force when force=True."""
        mock_git = mocker.patch(
            "gx.lib.worktree.git",
            return_value=_completed(
                returncode=0,
                stdout="",
                stderr="",
            ),
        )
        from gx.lib.worktree import remove_worktree

        result = remove_worktree(Path(".worktrees/feat"), force=True)
        assert result.ok is True
        mock_git.assert_called_once_with("worktree", "remove", "--force", ".worktrees/feat")


class TestListWorktreesMissingFolder:
    """Tests for list_worktrees() with a worktree folder removed by hand."""

    def test_skips_worktree_whose_folder_is_gone(self, tmp_git_repo):
        """Verify a deleted worktree folder is not returned as usable."""
        import shutil

        from gx.lib.worktree import list_worktrees

        wt_path = create_tmp_worktree(tmp_git_repo, "feature")
        shutil.rmtree(wt_path)

        assert [w.branch for w in list_worktrees()] == ["main"]

    def test_missing_worktrees_lists_deleted_folders(self, tmp_git_repo):
        """Verify missing_worktrees() reports registrations whose folder is gone."""
        import shutil

        from gx.lib.worktree import missing_worktrees

        wt_path = create_tmp_worktree(tmp_git_repo, "feature")
        assert missing_worktrees() == []

        shutil.rmtree(wt_path)

        assert [p.name for p in missing_worktrees()] == [wt_path.name]

    def test_locked_missing_worktree_keeps_its_branch(self, tmp_git_repo):
        """Verify a locked worktree with no folder is not offered to prune and still holds its branch."""
        import shutil

        from gx.lib.worktree import checked_out_branches, missing_worktrees

        locked = create_tmp_worktree(tmp_git_repo, "locked")
        gone = create_tmp_worktree(tmp_git_repo, "gone")
        _run_git("worktree", "lock", str(locked), cwd=tmp_git_repo)
        shutil.rmtree(locked)
        shutil.rmtree(gone)

        assert [p.name for p in missing_worktrees()] == [gone.name]
        assert checked_out_branches() == frozenset({"main", "locked"})


class TestParseWorktreePorcelain:
    """Tests for parse_worktree_porcelain()."""

    def test_parses_every_entry_kind(self):
        """Verify path, commit, branch, bare, detached, locked, and prunable keys are recorded."""
        from gx.lib.worktree import parse_worktree_porcelain

        output = (
            "worktree /repo\nHEAD aaa\nbranch refs/heads/main\n\n"
            "worktree /repo/bare\nbare\n\n"
            "worktree /repo/wt\nHEAD bbb\ndetached\n\n"
            "worktree /repo/gone\nHEAD ccc\nbranch refs/heads/feat/x\n"
            "prunable gitdir file points to non-existent location\n\n"
            "worktree /repo/usb\nHEAD ddd\nbranch refs/heads/feat/y\nlocked on usb\n"
        )

        assert parse_worktree_porcelain(output) == [
            {"path": "/repo", "commit": "aaa", "branch": "main"},
            {"path": "/repo/bare", "bare": ""},
            {"path": "/repo/wt", "commit": "bbb", "detached": ""},
            {
                "path": "/repo/gone",
                "commit": "ccc",
                "branch": "feat/x",
                "prunable": "gitdir file points to non-existent location",
            },
            {"path": "/repo/usb", "commit": "ddd", "branch": "feat/y", "locked": "on usb"},
        ]


class TestSharedEntries:
    """Callers that read the registrations once pass them to every view."""

    def test_views_use_given_entries_without_git(self, mocker, tmp_path):
        """Verify missing_worktrees and checked_out_branches reuse passed entries."""
        from gx.lib.worktree import checked_out_branches, missing_worktrees

        # Given
        git = mocker.patch("gx.lib.worktree.git")
        entries = [
            {"path": str(tmp_path), "branch": "main"},
            {"path": str(tmp_path / "gone"), "branch": "old", "prunable": ""},
            {"path": str(tmp_path / "usb"), "branch": "usb", "locked": ""},
        ]

        # When
        missing = missing_worktrees(entries)
        branches = checked_out_branches(entries)

        # Then
        assert missing == [tmp_path / "gone"]
        assert branches == {"main", "usb"}
        git.assert_not_called()
