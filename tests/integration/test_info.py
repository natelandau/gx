"""Integration tests for gx info command."""

from __future__ import annotations

from typing import TYPE_CHECKING

from typer.testing import CliRunner

from gx.cli import app

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


class TestInfoCommand:
    """Integration tests for gx info."""

    def test_info_shows_repository_panel(self, tmp_git_repo: Path):
        """Verify info command shows Repository panel."""
        result = runner.invoke(app, ["info"])
        assert result.exit_code == 0
        assert "Repository" in result.output

    def test_info_shows_branches_panel(self, tmp_git_repo: Path):
        """Verify info command shows Branches panel."""
        result = runner.invoke(app, ["info"])
        assert result.exit_code == 0
        assert "Branches" in result.output

    def test_info_shows_working_tree_panel(self, tmp_git_repo: Path):
        """Verify info command shows Working Tree panel."""
        result = runner.invoke(app, ["info"])
        assert result.exit_code == 0
        assert "Working Tree" in result.output

    def test_info_shows_recent_commits(self, tmp_git_repo: Path):
        """Verify info command shows Recent Commits panel."""
        result = runner.invoke(app, ["info"])
        assert result.exit_code == 0
        assert "Recent Commits" in result.output

    def test_default_command_runs_info(self, tmp_git_repo: Path):
        """Verify bare gx runs info instead of status."""
        result = runner.invoke(app, [])
        assert result.exit_code == 0
        assert "Repository" in result.output

    def test_status_still_works(self, tmp_git_repo: Path):
        """Verify gx status still works independently."""
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0


class TestInfoEmptyRepo:
    """Tests for info command in a brand-new repo with no commits."""

    def test_info_handles_repo_with_no_commits(self, empty_git_repo: Path):
        """Verify info exits cleanly in an unborn-HEAD repo instead of crashing."""
        # Given a freshly initialized repo with no commits (empty_git_repo fixture)
        # When running info
        result = runner.invoke(app, ["info"])

        # Then it succeeds and reports the empty state without a traceback
        assert result.exit_code == 0, result.output
        assert result.exception is None
        assert "no commits yet" in result.output.lower()

    def test_default_command_handles_no_commits(self, empty_git_repo: Path):
        """Verify bare gx exits cleanly in an unborn-HEAD repo."""
        # Given a freshly initialized repo with no commits (empty_git_repo fixture)
        # When running the default command
        result = runner.invoke(app, [])

        # Then it succeeds without a traceback
        assert result.exit_code == 0, result.output
        assert result.exception is None

    def test_status_handles_no_commits(self, empty_git_repo: Path):
        """Verify status exits cleanly in an unborn-HEAD repo instead of crashing."""
        # Given a freshly initialized repo with no commits (empty_git_repo fixture)
        # When running status
        result = runner.invoke(app, ["status"])

        # Then it succeeds without a traceback
        assert result.exit_code == 0, result.output
        assert result.exception is None


class TestInfoOutsideGitRepo:
    """Tests for info command outside a git repo."""

    def test_shows_error_outside_repo(self, tmp_path, monkeypatch):
        """Verify error when not in a git repo."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["info"])
        assert result.exit_code != 0
