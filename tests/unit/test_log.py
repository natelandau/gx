"""Tests for gx log command."""

from __future__ import annotations

import typer
from rich.panel import Panel
from rich.text import Text
from typer.core import TyperCommand

from gx.commands.log import log as log_callback


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
        ctx = typer.Context(TyperCommand("log"))
        log_callback(ctx=ctx, count=15, full=False, graph=False, verbose=0, dry_run=False)
        # Then
        mock_cls.assert_called_once_with(count=15, title="Log", show_body=False)
        mock_cls.return_value.render.assert_called_once()

    def test_graph_invocation_folds(self, mock_log_check_git_repo, mocker):
        """Verify --graph renders a folded LogGraph."""
        # Given
        mock_cls = mocker.patch("gx.commands.log.LogGraph", autospec=True)
        mock_cls.return_value.render.return_value = [Text("* abc")]
        # When
        ctx = typer.Context(TyperCommand("log"))
        log_callback(ctx=ctx, count=15, full=False, graph=True, verbose=0, dry_run=False)
        # Then
        mock_cls.assert_called_once_with(count=15, fold=True)

    def test_graph_full_unfolds(self, mock_log_check_git_repo, mocker):
        """Verify --graph --full renders every commit instead of folding."""
        # Given
        mock_cls = mocker.patch("gx.commands.log.LogGraph", autospec=True)
        mock_cls.return_value.render.return_value = [Text("* abc")]
        # When
        ctx = typer.Context(TyperCommand("log"))
        log_callback(ctx=ctx, count=15, full=True, graph=True, verbose=0, dry_run=False)
        # Then
        mock_cls.assert_called_once_with(count=15, fold=False)
