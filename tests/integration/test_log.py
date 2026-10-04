"""Integration tests for gx log command."""

import pytest
from typer.testing import CliRunner

from gx.cli import app
from tests.conftest import create_tmp_commit, create_tmp_stash, create_tmp_worktree

runner = CliRunner()


class TestLogIntegration:
    """Tests for log command against real repo."""

    def test_log_default(self, tmp_git_repo):
        """Verify default log shows commits and exits 0."""
        # Given — repo has initial commit from fixture
        # When
        result = runner.invoke(app, ["log"])
        # Then
        assert result.exit_code == 0
        assert "init" in result.output

    def test_log_count_flag(self, tmp_git_repo):
        """Verify -c flag limits number of commits shown."""
        # Given
        for i in range(5):
            create_tmp_commit(tmp_git_repo, f"commit {i}")
        # When — use count=4 because --all includes origin/main ref
        result = runner.invoke(app, ["log", "-c", "4"])
        # Then
        assert result.exit_code == 0
        assert "commit 4" in result.output
        assert "commit 3" in result.output
        assert "commit 2" in result.output

    def test_log_full(self, tmp_git_repo):
        """Verify --full flag exits 0."""
        # When
        result = runner.invoke(app, ["log", "--full"])
        # Then
        assert result.exit_code == 0

    def test_log_graph(self, tmp_git_repo):
        """Verify --graph flag shows graph characters."""
        # When
        result = runner.invoke(app, ["log", "--graph"])
        # Then
        assert result.exit_code == 0
        assert "*" in result.output

    def test_log_graph_includes_other_branches(self, tmp_git_repo):
        """Verify --graph shows commits on branches other than HEAD."""
        # Given
        worktree = create_tmp_worktree(tmp_git_repo, "feature")
        create_tmp_commit(worktree, "feature work")
        # When
        result = runner.invoke(app, ["log", "--graph"])
        # Then
        assert result.exit_code == 0
        assert "feature work" in result.output

    @pytest.mark.parametrize("args", [["log"], ["log", "--graph"]])
    def test_log_excludes_stash_commits(self, tmp_git_repo, args):
        """Verify stash WIP and index commits are not shown as history."""
        # Given
        create_tmp_stash(tmp_git_repo)
        # When
        result = runner.invoke(app, args)
        # Then
        assert result.exit_code == 0
        assert "WIP on" not in result.output
        assert "index on" not in result.output

    def test_log_graph_reaches_fork_point(self, tmp_git_repo):
        """Verify --graph shows where a branch forks even past the commit count."""
        # Given a branch forked from "base" with more commits than -c shows
        create_tmp_commit(tmp_git_repo, "base")
        worktree = create_tmp_worktree(tmp_git_repo, "feature")
        for i in range(10):
            create_tmp_commit(worktree, f"feature {i}")
        create_tmp_commit(tmp_git_repo, "main after fork")
        # When
        result = runner.invoke(app, ["log", "--graph", "-c", "3"])
        # Then
        assert result.exit_code == 0
        assert "|/" in result.output
        assert "base" in result.output
        assert "main after fork" in result.output
        assert "feature 9" in result.output
        assert "more commits" in result.output

    def test_log_graph_full_shows_every_commit(self, tmp_git_repo):
        """Verify --graph --full disables folding."""
        # Given
        worktree = create_tmp_worktree(tmp_git_repo, "feature")
        for i in range(10):
            create_tmp_commit(worktree, f"feature {i}")
        create_tmp_commit(tmp_git_repo, "main after fork")
        # When
        result = runner.invoke(app, ["log", "--graph", "--full"])
        # Then
        assert result.exit_code == 0
        assert "more commits" not in result.output
        for i in range(10):
            assert f"feature {i}" in result.output

    def test_log_graph_empty_repo(self, empty_git_repo):
        """Verify --graph in a repo with no commits warns instead of crashing."""
        # When
        result = runner.invoke(app, ["log", "--graph"])
        # Then
        assert result.exit_code == 0
        assert "No commits found" in result.output
