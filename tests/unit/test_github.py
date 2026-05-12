"""Tests for GitHub CLI helpers."""

from __future__ import annotations

from nclutils.git import Remote

from gx.lib.github import gh_available, is_github_remote, pr_state
from tests.unit.conftest import _completed


def _remote(url: str) -> Remote:
    """Build a Remote record matching nclutils.git.primary_remote output."""
    return Remote(name="origin", url=url, web_url=None)


class TestGhAvailable:
    """Tests for gh CLI availability detection."""

    def test_available_when_on_path(self, mocker):
        """Verify returns True when gh is on PATH."""
        mocker.patch("gx.lib.github.which", return_value="/usr/bin/gh")
        assert gh_available() is True

    def test_unavailable_when_not_on_path(self, mocker):
        """Verify returns False when gh is not on PATH."""
        mocker.patch("gx.lib.github.which", return_value=None)
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


class TestPrState:
    """Tests for pr_state() helper that queries gh for a branch's PR state."""

    def test_returns_none_when_gh_unavailable(self, mocker):
        """Verify None when gh CLI is not on PATH."""
        # Given gh is not available
        mocker.patch("gx.lib.github.gh_available", autospec=True, return_value=False)
        mock_primary = mocker.patch("gx.lib.github.primary_remote", autospec=True)
        mock_run = mocker.patch("gx.lib.github.run_command", autospec=True)

        # When
        result = pr_state("feature-x")

        # Then
        assert result is None
        mock_primary.assert_not_called()
        mock_run.assert_not_called()

    def test_returns_none_for_non_github_remote(self, mocker):
        """Verify None when the primary remote is not on GitHub."""
        # Given a non-GitHub remote
        mocker.patch("gx.lib.github.gh_available", autospec=True, return_value=True)
        mocker.patch(
            "gx.lib.github.primary_remote",
            autospec=True,
            return_value=_remote("git@gitlab.com:user/repo.git"),
        )
        mock_run = mocker.patch("gx.lib.github.run_command", autospec=True)

        # When
        result = pr_state("feature-x")

        # Then
        assert result is None
        mock_run.assert_not_called()

    def test_returns_none_when_no_remote_configured(self, mocker):
        """Verify None when no remote can be resolved."""
        # Given no remote
        mocker.patch("gx.lib.github.gh_available", autospec=True, return_value=True)
        mocker.patch("gx.lib.github.primary_remote", autospec=True, return_value=None)
        mock_run = mocker.patch("gx.lib.github.run_command", autospec=True)

        # When
        result = pr_state("feature-x")

        # Then
        assert result is None
        mock_run.assert_not_called()

    def test_returns_none_when_no_pr_found(self, mocker):
        """Verify None when gh reports no PR exists for the branch."""
        # Given gh fails (no PR for branch)
        mocker.patch("gx.lib.github.gh_available", autospec=True, return_value=True)
        mocker.patch(
            "gx.lib.github.primary_remote",
            autospec=True,
            return_value=_remote("git@github.com:user/repo.git"),
        )
        mocker.patch(
            "gx.lib.github.run_command",
            autospec=True,
            return_value=_completed(returncode=1, stderr="no pull requests found"),
        )

        # When
        result = pr_state("feature-x")

        # Then
        assert result is None

    def test_returns_merged_state(self, mocker):
        """Verify 'MERGED' returned when gh reports a merged PR."""
        # Given gh reports MERGED
        mocker.patch("gx.lib.github.gh_available", autospec=True, return_value=True)
        mocker.patch(
            "gx.lib.github.primary_remote",
            autospec=True,
            return_value=_remote("https://github.com/user/repo.git"),
        )
        mocker.patch(
            "gx.lib.github.run_command",
            autospec=True,
            return_value=_completed(returncode=0, stdout="MERGED"),
        )

        # When
        result = pr_state("feature-x")

        # Then
        assert result == "MERGED"

    def test_returns_open_state(self, mocker):
        """Verify 'OPEN' returned when gh reports an open PR."""
        # Given gh reports OPEN
        mocker.patch("gx.lib.github.gh_available", autospec=True, return_value=True)
        mocker.patch(
            "gx.lib.github.primary_remote",
            autospec=True,
            return_value=_remote("git@github.com:user/repo.git"),
        )
        mocker.patch(
            "gx.lib.github.run_command",
            autospec=True,
            return_value=_completed(returncode=0, stdout="OPEN"),
        )

        # When
        result = pr_state("feature-x")

        # Then
        assert result == "OPEN"

    def test_returns_none_for_unrecognized_state(self, mocker):
        """Verify None when gh returns a state string outside the known set."""
        # Given gh exits 0 with an unexpected state value
        mocker.patch("gx.lib.github.gh_available", autospec=True, return_value=True)
        mocker.patch(
            "gx.lib.github.primary_remote",
            autospec=True,
            return_value=_remote("git@github.com:user/repo.git"),
        )
        mocker.patch(
            "gx.lib.github.run_command",
            autospec=True,
            return_value=_completed(returncode=0, stdout="DRAFT"),
        )

        # When
        result = pr_state("feature-x")

        # Then
        assert result is None
