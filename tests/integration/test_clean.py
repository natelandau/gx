"""Integration tests for gx clean command."""

from typer.testing import CliRunner

from gx.cli import app
from tests.conftest import (
    checkout_tmp_branch,
    create_tmp_branch,
    create_tmp_commit,
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
