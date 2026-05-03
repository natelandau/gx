"""Tests for GitHub CLI wrapper."""

from __future__ import annotations

from gx.lib.github import gh, gh_available, is_github_remote, pr_state


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


class TestPrState:
    """Tests for pr_state() helper that queries gh for a branch's PR state."""

    def test_returns_none_when_gh_unavailable(self, mocker):
        """Verify None when gh CLI is not on PATH."""
        # Given gh is not available
        mocker.patch("gx.lib.github.gh_available", autospec=True, return_value=False)
        mock_resolve = mocker.patch("gx.lib.github.resolve_remote", autospec=True)
        mock_gh = mocker.patch("gx.lib.github.gh", autospec=True)

        # When
        result = pr_state("feature-x")

        # Then
        assert result is None
        mock_resolve.assert_not_called()
        mock_gh.assert_not_called()

    def test_returns_none_for_non_github_remote(self, mocker):
        """Verify None when the primary remote is not on GitHub."""
        # Given a non-GitHub remote
        mocker.patch("gx.lib.github.gh_available", autospec=True, return_value=True)
        mocker.patch(
            "gx.lib.github.resolve_remote",
            autospec=True,
            return_value=("origin", "git@gitlab.com:user/repo.git"),
        )
        mock_gh = mocker.patch("gx.lib.github.gh", autospec=True)

        # When
        result = pr_state("feature-x")

        # Then
        assert result is None
        mock_gh.assert_not_called()

    def test_returns_none_when_no_remote_configured(self, mocker):
        """Verify None when no remote can be resolved."""
        # Given no remote
        mocker.patch("gx.lib.github.gh_available", autospec=True, return_value=True)
        mocker.patch("gx.lib.github.resolve_remote", autospec=True, return_value=("", ""))
        mock_gh = mocker.patch("gx.lib.github.gh", autospec=True)

        # When
        result = pr_state("feature-x")

        # Then
        assert result is None
        mock_gh.assert_not_called()

    def test_returns_none_when_no_pr_found(self, mocker):
        """Verify None when gh reports no PR exists for the branch."""
        # Given gh fails (no PR for branch)
        mocker.patch("gx.lib.github.gh_available", autospec=True, return_value=True)
        mocker.patch(
            "gx.lib.github.resolve_remote",
            autospec=True,
            return_value=("origin", "git@github.com:user/repo.git"),
        )
        mock_proc = mocker.Mock(returncode=1, stdout="", stderr="no pull requests found")
        mocker.patch("gx.lib.github.subprocess.run", return_value=mock_proc)

        # When
        result = pr_state("feature-x")

        # Then
        assert result is None

    def test_returns_merged_state(self, mocker):
        """Verify 'MERGED' returned when gh reports a merged PR."""
        # Given gh reports MERGED
        mocker.patch("gx.lib.github.gh_available", autospec=True, return_value=True)
        mocker.patch(
            "gx.lib.github.resolve_remote",
            autospec=True,
            return_value=("origin", "https://github.com/user/repo.git"),
        )
        mock_proc = mocker.Mock(returncode=0, stdout="MERGED\n", stderr="")
        mocker.patch("gx.lib.github.subprocess.run", return_value=mock_proc)

        # When
        result = pr_state("feature-x")

        # Then
        assert result == "MERGED"

    def test_returns_open_state(self, mocker):
        """Verify 'OPEN' returned when gh reports an open PR."""
        # Given gh reports OPEN
        mocker.patch("gx.lib.github.gh_available", autospec=True, return_value=True)
        mocker.patch(
            "gx.lib.github.resolve_remote",
            autospec=True,
            return_value=("origin", "git@github.com:user/repo.git"),
        )
        mock_proc = mocker.Mock(returncode=0, stdout="OPEN\n", stderr="")
        mocker.patch("gx.lib.github.subprocess.run", return_value=mock_proc)

        # When
        result = pr_state("feature-x")

        # Then
        assert result == "OPEN"

    def test_returns_none_for_unrecognized_state(self, mocker):
        """Verify None when gh returns a state string outside the known set."""
        # Given gh exits 0 with an unexpected state value
        mocker.patch("gx.lib.github.gh_available", autospec=True, return_value=True)
        mocker.patch(
            "gx.lib.github.resolve_remote",
            autospec=True,
            return_value=("origin", "git@github.com:user/repo.git"),
        )
        mock_proc = mocker.Mock(returncode=0, stdout="DRAFT\n", stderr="")
        mocker.patch("gx.lib.github.subprocess.run", return_value=mock_proc)

        # When
        result = pr_state("feature-x")

        # Then
        assert result is None
