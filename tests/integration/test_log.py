"""Integration tests for gx log command."""

from typer.testing import CliRunner

from gx.cli import app
from tests.conftest import create_tmp_commit

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

    def test_log_full_and_graph_mutually_exclusive(self, tmp_git_repo):
        """Verify error when both --full and --graph are passed."""
        # When
        result = runner.invoke(app, ["log", "--full", "--graph"])
        # Then
        assert result.exit_code == 1
        assert (
            "mutually exclusive" in result.output.lower()
            or "mutually exclusive" in (result.stderr or "").lower()
        )
