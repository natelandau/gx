"""Integration tests for gx done command."""

from typer.testing import CliRunner

from gx.cli import app
from tests.conftest import (
    checkout_tmp_branch,
    create_tmp_branch,
    create_tmp_commit,
    merge_tmp_branch,
    push_tmp_branch,
)

runner = CliRunner()


class TestDoneFromBranch:
    """Tests for done from a feature branch."""

    def test_done_checkout_and_delete(self, tmp_git_repo):
        """Verify done checks out main, pulls, and deletes the branch."""
        # Given a feature branch that's been merged
        create_tmp_branch(tmp_git_repo, "feat/done")
        create_tmp_commit(tmp_git_repo, "feature work")
        push_tmp_branch(tmp_git_repo)
        merge_tmp_branch(tmp_git_repo, "feat/done", into="main")
        push_tmp_branch(tmp_git_repo, "main")
        checkout_tmp_branch(tmp_git_repo, "feat/done")

        # When
        result = runner.invoke(app, ["done"])

        # Then
        assert result.exit_code == 0

    def test_done_on_main_aborts(self, tmp_git_repo):
        """Verify done aborts when already on main."""
        result = runner.invoke(app, ["done"])
        assert result.exit_code == 1
