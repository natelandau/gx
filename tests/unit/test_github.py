"""Tests for GitHub CLI wrapper."""

from __future__ import annotations

from gx.lib.github import gh, gh_available, is_github_remote


class TestGhAvailable:
    """Tests for gh CLI availability detection."""

    def test_available_when_on_path(self, mocker):
        """Verify returns True when gh is on PATH."""
        mocker.patch("gx.lib.github.shutil.which", return_value="/usr/bin/gh")
        assert gh_available() is True

    def test_unavailable_when_not_on_path(self, mocker):
        """Verify returns False when gh is not on PATH."""
        mocker.patch("gx.lib.github.shutil.which", return_value=None)
        assert gh_available() is False


class TestIsGithubRemote:
    """Tests for GitHub remote detection."""

    def test_ssh_github_remote(self):
        """Verify SSH GitHub URL detected."""
        assert is_github_remote("git@github.com:user/repo.git") is True

    def test_https_github_remote(self):
        """Verify HTTPS GitHub URL detected."""
        assert is_github_remote("https://github.com/user/repo.git") is True

    def test_non_github_remote(self):
        """Verify non-GitHub URL rejected."""
        assert is_github_remote("git@gitlab.com:user/repo.git") is False

    def test_empty_string(self):
        """Verify empty string rejected."""
        assert is_github_remote("") is False


class TestGh:
    """Tests for the gh() subprocess wrapper."""

    def test_successful_command(self, mocker):
        """Verify successful gh command returns GhResult with stdout."""
        mock_proc = mocker.Mock(returncode=0, stdout="output\n", stderr="")
        mocker.patch("gx.lib.github.subprocess.run", return_value=mock_proc)
        result = gh("repo", "view")
        assert result.success is True
        assert result.stdout == "output"

    def test_failed_command(self, mocker):
        """Verify failed gh command returns GhResult with error."""
        mock_proc = mocker.Mock(returncode=1, stdout="", stderr="auth error\n")
        mocker.patch("gx.lib.github.subprocess.run", return_value=mock_proc)
        result = gh("repo", "view")
        assert result.success is False
        assert result.stderr == "auth error"
