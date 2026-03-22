"""Integration tests for gx push command."""

from typer.testing import CliRunner

from gx.cli import app
from tests.conftest import (
    create_tmp_branch,
    create_tmp_commit,
    make_tmp_dirty,
    push_tmp_branch,
)

runner = CliRunner()


class TestPushIntegration:
    """Tests for push command against real repo."""

    def test_push_feature_branch(self, tmp_git_repo):
        """Verify push succeeds for a feature branch with commits."""
        create_tmp_branch(tmp_git_repo, "feat/test")
        create_tmp_commit(tmp_git_repo, "new feature")
        result = runner.invoke(app, ["push"])
        assert result.exit_code == 0
        assert "1 commit(s)" in result.output

    def test_push_already_up_to_date(self, tmp_git_repo):
        """Verify push shows up-to-date when nothing to push."""
        create_tmp_branch(tmp_git_repo, "feat/test")
        create_tmp_commit(tmp_git_repo, "work")
        push_tmp_branch(tmp_git_repo)
        result = runner.invoke(app, ["push"])
        assert result.exit_code == 0
        assert "Already up to date" in result.output

    def test_push_warns_dirty_tree(self, tmp_git_repo):
        """Verify push warns about dirty tree but still pushes."""
        create_tmp_branch(tmp_git_repo, "feat/test")
        create_tmp_commit(tmp_git_repo, "committed work")
        make_tmp_dirty(tmp_git_repo)
        result = runner.invoke(app, ["push"])
        assert result.exit_code == 0

    def test_push_to_default_branch_prompts(self, tmp_git_repo, mocker):
        """Verify push to main prompts for confirmation."""
        mock_confirm = mocker.patch(
            "gx.commands.push.Confirm.ask", autospec=True, return_value=False
        )
        create_tmp_commit(tmp_git_repo, "direct to main")
        result = runner.invoke(app, ["push"])
        assert result.exit_code == 0
        mock_confirm.assert_called_once()
