"""Integration tests for gx pull command."""

from pathlib import Path

from typer.testing import CliRunner

from gx.cli import app
from tests.conftest import make_tmp_dirty, push_tmp_remote_commit

runner = CliRunner()


class TestPullIntegration:
    """Tests for pull command against real repo."""

    def test_pull_new_commits(self, tmp_git_repo: Path) -> None:
        """Verify pull fetches and shows new commits."""
        push_tmp_remote_commit(tmp_git_repo)
        result = runner.invoke(app, ["pull"])
        assert result.exit_code == 0
        assert "1 new commit(s)" in result.output

    def test_pull_already_up_to_date(self, tmp_git_repo: Path) -> None:
        """Verify pull shows up-to-date when nothing new."""
        result = runner.invoke(app, ["pull"])
        assert result.exit_code == 0
        assert "Already up to date" in result.output

    def test_pull_stashes_dirty_tree(self, tmp_git_repo: Path) -> None:
        """Verify pull stashes and restores dirty working tree."""
        push_tmp_remote_commit(tmp_git_repo)
        make_tmp_dirty(tmp_git_repo)
        result = runner.invoke(app, ["pull"])
        assert result.exit_code == 0
        assert (tmp_git_repo / "dirty.txt").exists()
