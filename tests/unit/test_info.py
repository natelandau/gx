"""Tests for gx info command."""

from __future__ import annotations

import click
import typer

from gx.lib.git import GitResult


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
        mocker.patch("gx.lib.info_panels.gh_available", return_value=False)
        mocker.patch("gx.lib.info_panels.list_worktrees", return_value=[])
        mocker.patch("gx.commands.info.collect_branch_data", return_value=[])
        mocker.patch("gx.commands.info.stash_counts", return_value={})
        mocker.patch("gx.commands.info.count_file_statuses", return_value=(0, 0, 0, 0))

        from gx.commands.info import info

        ctx = typer.Context(click.Command("info"))
        info(ctx=ctx)
