"""Tests for gx log command."""

from __future__ import annotations

import click
import pytest
import typer
from rich.panel import Panel

from gx.commands.log import colorize_graph_line
from gx.commands.log import log as log_callback

from .conftest import _ok


class TestColorizeGraphLine:
    """Tests for applying Rich styles to git log --graph output lines."""

    def test_commit_line_colorized(self):
        """Verify SHA, time, author, and subject are styled on commit lines."""
        # Given
        line = "* 9c96da2 3 days ago <Nate Landau> bump release"
        # When
        text = colorize_graph_line(line)
        # Then
        plain = text.plain
        assert "9c96da2" in plain
        assert "3 days ago" in plain
        assert "Nate Landau" in plain
        assert "bump release" in plain
        assert "<" not in plain
        assert ">" not in plain

    def test_connector_line_styled_dim(self):
        """Verify graph-only lines are styled with log_graph."""
        # Given
        line = "| * |"
        # When
        text = colorize_graph_line(line)
        # Then
        assert text.plain.strip() == "| * |"

    def test_line_with_ref_decoration(self):
        """Verify ref decorations in parentheses are preserved."""
        # Given
        line = "* 9c96da2 3 days ago <Nate> bump (HEAD -> main, origin/main)"
        # When
        text = colorize_graph_line(line)
        # Then
        plain = text.plain
        assert "HEAD -> main" in plain

    def test_empty_line(self):
        """Verify empty lines pass through."""
        # When
        text = colorize_graph_line("")
        # Then
        assert text.plain == ""


class TestLogCallback:
    """Tests for the log command callback behavior."""

    def test_default_invocation(self, mock_log_check_git_repo, mocker):
        """Verify default invocation renders a LogPanel."""
        # Given
        mock_panel = Panel("test")
        mock_cls = mocker.patch(
            "gx.commands.log.LogPanel",
            autospec=True,
        )
        mock_cls.return_value.render.return_value = mock_panel
        # When
        ctx = typer.Context(click.Command("log"))
        log_callback(ctx=ctx, count=15, full=False, graph=False, verbose=0, dry_run=False)
        # Then
        mock_cls.assert_called_once_with(count=15, title="Log", show_body=False)
        mock_cls.return_value.render.assert_called_once()

    def test_graph_invocation(self, mock_log_check_git_repo, mock_log_git):
        """Verify --graph passes --graph flag to git."""
        # Given
        mock_log_git.return_value = _ok(stdout="* 9c96da2 3 days ago <Nate> bump release")
        # When
        ctx = typer.Context(click.Command("log"))
        log_callback(ctx=ctx, count=15, full=False, graph=True, verbose=0, dry_run=False)
        # Then
        args = mock_log_git.call_args[0]
        assert "--graph" in args

    def test_full_and_graph_mutex(self, mock_log_check_git_repo, capsys):
        """Verify error when both --full and --graph are passed."""
        # When/Then
        ctx = typer.Context(click.Command("log"))
        with pytest.raises(typer.Exit):
            log_callback(ctx=ctx, count=15, full=True, graph=True, verbose=0, dry_run=False)
        captured = capsys.readouterr()
        assert "mutually exclusive" in captured.err.lower()
