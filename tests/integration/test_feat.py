"""Integration tests for gx feat command."""

from typer.testing import CliRunner

from gx.cli import app
from tests.conftest import checkout_tmp_branch, create_tmp_branch, create_tmp_commit

runner = CliRunner()


class TestFeatBranch:
    """Tests for feat command branch creation against real repo."""

    def test_creates_auto_numbered_branch(self, tmp_git_repo):
        """Verify feat creates feat/1 when no feat branches exist."""
        result = runner.invoke(app, ["feat"])
        assert result.exit_code == 0
        assert "feat/1" in result.output

    def test_creates_named_branch(self, tmp_git_repo):
        """Verify feat <name> creates feat/<name>."""
        result = runner.invoke(app, ["feat", "login"])
        assert result.exit_code == 0
        assert "feat/login" in result.output

    def test_increments_number(self, tmp_git_repo):
        """Verify feat creates feat/2 when feat/1 exists."""
        create_tmp_branch(tmp_git_repo, "feat/1")
        create_tmp_commit(tmp_git_repo, "work on feat/1")
        checkout_tmp_branch(tmp_git_repo, "main")

        result = runner.invoke(app, ["feat"])
        assert result.exit_code == 0
        assert "feat/2" in result.output


class TestFeatWorktree:
    """Tests for feat command worktree creation against real repo."""

    def test_creates_worktree(self, tmp_git_repo):
        """Verify feat --worktree creates worktree at correct path."""
        (tmp_git_repo / ".worktrees").mkdir()
        result = runner.invoke(app, ["feat", "--worktree"])
        assert result.exit_code == 0
        assert "feat/1" in result.output

    def test_creates_named_worktree(self, tmp_git_repo):
        """Verify feat --worktree <name> creates named worktree."""
        (tmp_git_repo / ".worktrees").mkdir()
        result = runner.invoke(app, ["feat", "--worktree", "login"])
        assert result.exit_code == 0
        assert "feat/login" in result.output
