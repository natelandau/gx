"""Integration tests for gx clean command."""

import shutil

from typer.testing import CliRunner

from gx.cli import app
from tests.conftest import (
    _run_git,
    checkout_tmp_branch,
    create_tmp_branch,
    create_tmp_commit,
    create_tmp_worktree,
    delete_tmp_remote_branch,
    merge_tmp_branch,
    push_tmp_branch,
)

runner = CliRunner()


class TestCleanIntegration:
    """Tests for clean command against real repo."""

    def test_nothing_to_clean(self, tmp_git_repo):
        """Verify clean reports nothing when repo is clean."""
        result = runner.invoke(app, ["clean", "-y"])
        assert result.exit_code == 0
        assert "Nothing to clean" in result.output

    def test_cleans_gone_branch(self, tmp_git_repo):
        """Verify clean removes a branch whose remote was deleted."""
        create_tmp_branch(tmp_git_repo, "feat/old")
        create_tmp_commit(tmp_git_repo, "old work")
        push_tmp_branch(tmp_git_repo)
        checkout_tmp_branch(tmp_git_repo, "main")
        delete_tmp_remote_branch(tmp_git_repo, "feat/old")

        result = runner.invoke(app, ["clean", "-y"])
        assert result.exit_code == 0
        assert "feat/old" in result.output

    def test_cleans_merged_branch(self, tmp_git_repo):
        """Verify clean removes a branch that's been merged."""
        create_tmp_branch(tmp_git_repo, "feat/merged")
        create_tmp_commit(tmp_git_repo, "feature")
        push_tmp_branch(tmp_git_repo)
        merge_tmp_branch(tmp_git_repo, "feat/merged", into="main")
        push_tmp_branch(tmp_git_repo, "main")

        result = runner.invoke(app, ["clean", "-y"])
        assert result.exit_code == 0
        assert "feat/merged" in result.output

    def test_dry_run_does_not_delete(self, tmp_git_repo):
        """Verify clean --dry-run shows candidates without deleting."""
        create_tmp_branch(tmp_git_repo, "feat/old")
        create_tmp_commit(tmp_git_repo, "work")
        push_tmp_branch(tmp_git_repo)
        checkout_tmp_branch(tmp_git_repo, "main")
        delete_tmp_remote_branch(tmp_git_repo, "feat/old")

        result = runner.invoke(app, ["clean", "-n"])
        assert result.exit_code == 0
        assert "feat/old" in result.output

        # Branch should still exist
        from gx.lib.branch import all_local_branches

        assert "feat/old" in all_local_branches()


class TestCleanEmptyRepo:
    """Tests for gx clean in a brand-new repo with no commits."""

    def test_clean_handles_repo_with_no_commits(self, empty_git_repo):
        """Verify clean exits cleanly in an unborn-HEAD repo instead of crashing."""
        # Given a freshly initialized repo with no commits (empty_git_repo fixture)
        # When running clean
        result = runner.invoke(app, ["clean", "-y"])

        # Then it succeeds with nothing to clean and no traceback
        assert result.exit_code == 0, result.output
        assert result.exception is None
        assert "Nothing to clean" in result.output


class TestCleanSafety:
    """Tests for gx clean edge cases that must never offer or crash."""

    def test_default_branch_never_offered(self, tmp_git_repo):
        """Verify an unprotected default branch name is not offered for deletion."""
        # Given a default branch named trunk, with another branch checked out
        _run_git("branch", "-m", "main", "trunk", cwd=tmp_git_repo)
        _run_git("push", "-u", "origin", "trunk", cwd=tmp_git_repo)
        _run_git("remote", "set-head", "origin", "trunk", cwd=tmp_git_repo)
        create_tmp_branch(tmp_git_repo, "feat/work")

        # When
        result = runner.invoke(app, ["clean", "-n"])

        # Then
        assert result.exit_code == 0, result.output
        assert "trunk" not in result.output

    def test_survives_hand_deleted_worktree(self, tmp_git_repo):
        """Verify clean does not crash when a worktree folder was removed by hand."""
        # Given a worktree whose folder is deleted without `git worktree remove`
        worktree = create_tmp_worktree(tmp_git_repo, "feat/gone-dir")
        push_tmp_branch(tmp_git_repo, "feat/gone-dir")
        shutil.rmtree(worktree)

        # When
        result = runner.invoke(app, ["clean", "-n"])

        # Then
        assert result.exception is None, result.output
        assert result.exit_code == 0

    def test_removes_branch_of_hand_deleted_worktree(self, tmp_git_repo):
        """Verify a merged branch is deleted even when its worktree folder was removed by hand."""
        # Given a merged, pushed branch whose worktree folder is gone
        worktree = create_tmp_worktree(tmp_git_repo, "feat/merged-wt")
        create_tmp_commit(worktree, "feature")
        push_tmp_branch(worktree)
        merge_tmp_branch(tmp_git_repo, "feat/merged-wt", into="main")
        push_tmp_branch(tmp_git_repo, "main")
        shutil.rmtree(worktree)

        # When
        result = runner.invoke(app, ["clean", "-y"])

        # Then
        from gx.lib.branch import all_local_branches

        assert result.exit_code == 0, result.output
        assert "feat/merged-wt" not in all_local_branches()
