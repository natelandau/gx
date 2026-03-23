"""Tests for gx info command."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import click
import typer
from rich.panel import Panel

from gx.commands.info import (
    _github_panel,
    _remote_to_url,
    _stash_panel,
    _worktree_panel,
)
from gx.lib.git import GitResult
from gx.lib.github import GhResult
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
        with patch("gx.commands.info.gh_available", return_value=False):
            result = _github_panel("https://github.com/user/repo")
        assert result is None

    def test_returns_none_for_non_github_remote(self):
        """Verify None returned when remote is not a GitHub URL."""
        with (
            patch("gx.commands.info.gh_available", return_value=True),
            patch("gx.commands.info.is_github_remote", return_value=False),
        ):
            result = _github_panel("https://gitlab.com/user/repo")
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
            patch("gx.commands.info.gh_available", return_value=True),
            patch("gx.commands.info.is_github_remote", return_value=True),
            patch("gx.commands.info.gh", return_value=gh_success),
            patch("gx.commands.info._gh_open_count", side_effect=lambda r: 2 if r == "pr" else 5),
        ):
            result = _github_panel("https://github.com/user/repo")
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
            patch("gx.commands.info.gh_available", return_value=True),
            patch("gx.commands.info.is_github_remote", return_value=True),
            patch("gx.commands.info.gh", return_value=gh_success),
            patch("gx.commands.info._gh_open_count", return_value=0),
        ):
            result = _github_panel("https://github.com/user/repo")
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
            patch("gx.commands.info.gh_available", return_value=True),
            patch("gx.commands.info.is_github_remote", return_value=True),
            patch("gx.commands.info.gh", return_value=gh_fail),
        ):
            result = _github_panel("https://github.com/user/repo")
        assert result is None


class TestStashPanel:
    """Tests for the stash info panel."""

    def test_returns_none_when_no_stashes(self):
        """Verify None returned when stash dict is empty."""
        result = _stash_panel({})
        assert result is None

    def test_returns_panel_with_stashes(self):
        """Verify Panel returned when stash dict has entries."""
        stashes = {"main": 2, "feature/foo": 1}
        result = _stash_panel(stashes)
        assert isinstance(result, Panel)

    def test_returns_panel_with_single_stash(self):
        """Verify Panel returned for a single stash entry."""
        result = _stash_panel({"main": 1})
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
        with patch("gx.commands.info.list_worktrees", return_value=[main_wt]):
            result = _worktree_panel(Path("/repo"))
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
        with patch("gx.commands.info.list_worktrees", return_value=[main_wt, feature_wt]):
            result = _worktree_panel(Path("/repo"))
        assert isinstance(result, Panel)

    def test_returns_none_when_list_is_empty(self):
        """Verify None returned when list_worktrees returns empty list."""
        with patch("gx.commands.info.list_worktrees", return_value=[]):
            result = _worktree_panel(Path("/repo"))
        assert result is None


class TestInfoCommand:
    """Tests for the info command callback."""

    def test_renders_without_error(self, mocker):
        """Verify info command runs and produces output."""
        mocker.patch("gx.commands.info.check_git_repo")
        mock_path = mocker.MagicMock()
        mock_path.__truediv__ = mocker.Mock(
            return_value=mocker.MagicMock(
                exists=mocker.Mock(return_value=False),
                is_dir=mocker.Mock(return_value=False),
            )
        )
        mocker.patch("gx.commands.info.repo_root", return_value=mock_path)
        mock_git = mocker.patch("gx.commands.info.git")
        mock_git.return_value = GitResult(command="git", returncode=0, stdout="test", stderr="")
        mocker.patch("gx.commands.info.gh_available", return_value=False)
        mocker.patch("gx.commands.info.list_worktrees", return_value=[])
        mocker.patch("gx.commands.info.collect_branch_data", return_value=[])
        mocker.patch("gx.commands.info.stash_counts", return_value={})
        mocker.patch("gx.commands.info.count_file_statuses", return_value=(0, 0, 0, 0))

        from gx.commands.info import info

        ctx = typer.Context(click.Command("info"))
        info(ctx=ctx)
