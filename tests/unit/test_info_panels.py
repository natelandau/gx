"""Tests for info panel classes."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from nclutils.git import Remote
from rich.panel import Panel

from gx.lib.info_panels import GitHubPanel, StashPanel, WorktreePanel
from gx.lib.worktree import WorktreeInfo
from tests.unit.conftest import _completed


def _remote(url: str = "git@github.com:user/repo.git") -> Remote:
    """Build a Remote record matching nclutils.git.primary_remote output."""
    return Remote(name="origin", url=url, web_url="https://github.com/user/repo")


class TestGithubPanel:
    """Tests for the GitHub info panel."""

    def test_returns_none_when_no_remote(self):
        """Verify None returned when no remote is configured."""
        assert GitHubPanel(None).render() is None

    def test_returns_none_when_gh_unavailable(self):
        """Verify None returned when gh CLI is not installed."""
        with patch("gx.lib.info_panels.gh_available", return_value=False):
            result = GitHubPanel(_remote()).render()
        assert result is None

    def test_returns_none_for_non_github_remote(self):
        """Verify None returned when remote is not a GitHub URL."""
        with (
            patch("gx.lib.info_panels.gh_available", return_value=True),
            patch("gx.lib.info_panels.is_github_remote", return_value=False),
        ):
            result = GitHubPanel(_remote("git@gitlab.com:user/repo.git")).render()
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
        gh_success = _completed(returncode=0, stdout=json.dumps(repo_data))
        with (
            patch("gx.lib.info_panels.gh_available", return_value=True),
            patch("gx.lib.info_panels.is_github_remote", return_value=True),
            patch("gx.lib.info_panels.run_command", return_value=gh_success),
            patch("gx.lib.info_panels._gh_open_count", side_effect=lambda r: 2 if r == "pr" else 5),
        ):
            result = GitHubPanel(_remote()).render()
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
        gh_success = _completed(returncode=0, stdout=json.dumps(repo_data))
        with (
            patch("gx.lib.info_panels.gh_available", return_value=True),
            patch("gx.lib.info_panels.is_github_remote", return_value=True),
            patch("gx.lib.info_panels.run_command", return_value=gh_success),
            patch("gx.lib.info_panels._gh_open_count", return_value=0),
        ):
            result = GitHubPanel(_remote()).render()
        assert isinstance(result, Panel)

    def test_returns_none_when_gh_fails(self):
        """Verify None returned when gh repo view command fails."""
        gh_fail = _completed(returncode=1, stderr="not authenticated")
        with (
            patch("gx.lib.info_panels.gh_available", return_value=True),
            patch("gx.lib.info_panels.is_github_remote", return_value=True),
            patch("gx.lib.info_panels.run_command", return_value=gh_fail),
        ):
            result = GitHubPanel(_remote()).render()
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
