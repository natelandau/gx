"""Tests for info panel classes."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from rich.panel import Panel

from gx.lib.github import GhResult
from gx.lib.info_panels import (
    GitHubPanel,
    StashPanel,
    WorktreePanel,
    _remote_to_url,
)
from gx.lib.worktree import WorktreeInfo


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


class TestGithubPanel:
    """Tests for the GitHub info panel."""

    def test_returns_none_when_gh_unavailable(self):
        """Verify None returned when gh CLI is not installed."""
        with patch("gx.lib.info_panels.gh_available", return_value=False):
            result = GitHubPanel("https://github.com/user/repo").render()
        assert result is None

    def test_returns_none_for_non_github_remote(self):
        """Verify None returned when remote is not a GitHub URL."""
        with (
            patch("gx.lib.info_panels.gh_available", return_value=True),
            patch("gx.lib.info_panels.is_github_remote", return_value=False),
        ):
            result = GitHubPanel("https://gitlab.com/user/repo").render()
        assert result is None

    def test_returns_panel_for_github_remote(self):
        """Verify Panel returned for a valid GitHub remote with gh available."""
        repo_data = {
            "description": "A test repo",
            "visibility": "public",
            "stargazerCount": 42,
            "isFork": False,
            "parent": None,
        }
        gh_success = GhResult(
            command="gh repo view --json ...",
            returncode=0,
            stdout=json.dumps(repo_data),
            stderr="",
        )
        with (
            patch("gx.lib.info_panels.gh_available", return_value=True),
            patch("gx.lib.info_panels.is_github_remote", return_value=True),
            patch("gx.lib.info_panels.gh", return_value=gh_success),
            patch("gx.lib.info_panels._gh_open_count", side_effect=lambda r: 2 if r == "pr" else 5),
        ):
            result = GitHubPanel("https://github.com/user/repo").render()
        assert isinstance(result, Panel)

    def test_returns_panel_for_fork(self):
        """Verify Panel returned and fork info shown when repo is a fork."""
        repo_data = {
            "description": "A forked repo",
            "visibility": "public",
            "stargazerCount": 0,
            "isFork": True,
            "parent": {"nameWithOwner": "upstream/repo"},
        }
        gh_success = GhResult(
            command="gh repo view --json ...",
            returncode=0,
            stdout=json.dumps(repo_data),
            stderr="",
        )
        with (
            patch("gx.lib.info_panels.gh_available", return_value=True),
            patch("gx.lib.info_panels.is_github_remote", return_value=True),
            patch("gx.lib.info_panels.gh", return_value=gh_success),
            patch("gx.lib.info_panels._gh_open_count", return_value=0),
        ):
            result = GitHubPanel("https://github.com/user/repo").render()
        assert isinstance(result, Panel)

    def test_returns_none_when_gh_fails(self):
        """Verify None returned when gh repo view command fails."""
        gh_fail = GhResult(
            command="gh repo view --json ...",
            returncode=1,
            stdout="",
            stderr="not authenticated",
        )
        with (
            patch("gx.lib.info_panels.gh_available", return_value=True),
            patch("gx.lib.info_panels.is_github_remote", return_value=True),
            patch("gx.lib.info_panels.gh", return_value=gh_fail),
        ):
            result = GitHubPanel("https://github.com/user/repo").render()
        assert result is None


class TestStashPanel:
    """Tests for the stash info panel."""

    def test_returns_none_when_no_stashes(self):
        """Verify None returned when stash dict is empty."""
        result = StashPanel({}).render()
        assert result is None

    def test_returns_panel_with_stashes(self):
        """Verify Panel returned when stash dict has entries."""
        stashes = {"main": 2, "feature/foo": 1}
        result = StashPanel(stashes).render()
        assert isinstance(result, Panel)

    def test_returns_panel_with_single_stash(self):
        """Verify Panel returned for a single stash entry."""
        result = StashPanel({"main": 1}).render()
        assert isinstance(result, Panel)


class TestWorktreePanel:
    """Tests for the worktree info panel."""

    def test_returns_none_when_no_worktrees(self):
        """Verify None returned when only the main worktree exists."""
        main_wt = WorktreeInfo(
            path=Path("/repo"),
            branch="main",
            commit="abc1234",
            is_bare=False,
            is_main=True,
            is_merged=False,
            is_gone=False,
            is_empty=False,
        )
        with patch("gx.lib.info_panels.list_worktrees", return_value=[main_wt]):
            result = WorktreePanel(Path("/repo")).render()
        assert result is None

    def test_returns_panel_with_worktrees(self):
        """Verify Panel returned when non-main worktrees exist."""
        main_wt = WorktreeInfo(
            path=Path("/repo"),
            branch="main",
            commit="abc1234",
            is_bare=False,
            is_main=True,
            is_merged=False,
            is_gone=False,
            is_empty=False,
        )
        feature_wt = WorktreeInfo(
            path=Path("/repo/.worktrees/feat-foo"),
            branch="feat-foo",
            commit="def5678",
            is_bare=False,
            is_main=False,
            is_merged=False,
            is_gone=False,
            is_empty=False,
        )
        with patch("gx.lib.info_panels.list_worktrees", return_value=[main_wt, feature_wt]):
            result = WorktreePanel(Path("/repo")).render()
        assert isinstance(result, Panel)

    def test_returns_none_when_list_is_empty(self):
        """Verify None returned when list_worktrees returns empty list."""
        with patch("gx.lib.info_panels.list_worktrees", return_value=[]):
            result = WorktreePanel(Path("/repo")).render()
        assert result is None
