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
        log_callback(ctx=ctx, count=None, full=False, graph=True, verbose=0, dry_run=False)
        # Then
        mock_cls.assert_called_once_with(count=15, fold=True, cap=False)

    def test_graph_full_unfolds(self, mock_log_check_git_repo, mocker):
        """Verify --graph --full renders every commit instead of folding."""
        # Given
        mock_cls = mocker.patch("gx.commands.log.LogGraph", autospec=True)
        mock_cls.return_value.render.return_value = [Text("* abc")]
        # When
        ctx = typer.Context(TyperCommand("log"))
        log_callback(ctx=ctx, count=None, full=True, graph=True, verbose=0, dry_run=False)
        # Then
        mock_cls.assert_called_once_with(count=15, fold=False, cap=False)

    def test_graph_explicit_count_caps(self, mock_log_check_git_repo, mocker):
        """Verify an explicit --count caps the graph and shows every commit in it."""
        # Given
        mock_cls = mocker.patch("gx.commands.log.LogGraph", autospec=True)
        mock_cls.return_value.render.return_value = [Text("* abc")]
        # When
        ctx = typer.Context(TyperCommand("log"))
        log_callback(ctx=ctx, count=20, full=False, graph=True, verbose=0, dry_run=False)
        # Then
        mock_cls.assert_called_once_with(count=20, fold=False, cap=True)

    def test_default_panel_count(self, mock_log_check_git_repo, mocker):
        """Verify the panel shows the default number of commits when --count is omitted."""
        # Given
        mock_cls = mocker.patch("gx.commands.log.LogPanel", autospec=True)
        mock_cls.return_value.render.return_value = Panel("test")
        # When
        ctx = typer.Context(TyperCommand("log"))
        log_callback(ctx=ctx, count=None, full=False, graph=False, verbose=0, dry_run=False)
        # Then
        mock_cls.assert_called_once_with(count=15, title="Log", show_body=False)
