"""Tests for gx info command."""

from __future__ import annotations

from gx.commands.info import _remote_to_url


class TestRemoteToUrl:
    """Tests for git remote to HTTPS URL conversion."""

    def test_ssh_github(self):
        """Verify git@github.com SSH format converted."""
        assert _remote_to_url("git@github.com:user/repo.git") == "https://github.com/user/repo"

    def test_ssh_protocol(self):
        """Verify ssh:// protocol format converted."""
        assert (
            _remote_to_url("ssh://git@github.com/user/repo.git") == "https://github.com/user/repo"
        )

    def test_ssh_with_port(self):
        """Verify ssh:// with port strips port number."""
        result = _remote_to_url("ssh://git@github.com:2222/user/repo.git")
        assert result == "https://github.com/user/repo"

    def test_https_passthrough(self):
        """Verify https:// URLs passed through with .git stripped."""
        assert _remote_to_url("https://github.com/user/repo.git") == "https://github.com/user/repo"

    def test_http_passthrough(self):
        """Verify http:// URLs passed through."""
        assert _remote_to_url("http://github.com/user/repo") == "http://github.com/user/repo"

    def test_generic_git_at(self):
        """Verify generic git@ format converted."""
        assert _remote_to_url("git@gitlab.com:user/repo.git") == "https://gitlab.com/user/repo"

    def test_unrecognized_returns_none(self):
        """Verify unrecognized format returns None."""
        assert _remote_to_url("/local/path/to/repo") is None

    def test_strips_whitespace(self):
        """Verify leading/trailing whitespace stripped."""
        assert _remote_to_url("  git@github.com:user/repo.git  ") == "https://github.com/user/repo"
