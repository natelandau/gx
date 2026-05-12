"""Tests for gx.lib.workspace primitives."""

from __future__ import annotations

from gx.lib.workspace import has_submodules


class TestHasSubmodules:
    """Tests for the has_submodules helper function."""

    def test_true_when_gitmodules_exists(self, tmp_path, mocker):
        """Verify has_submodules returns True when .gitmodules file exists at repo root."""
        # Given a repo root that contains .gitmodules
        (tmp_path / ".gitmodules").touch()
        mocker.patch("gx.lib.workspace.repo_root", autospec=True, return_value=tmp_path)

        # When
        result = has_submodules()

        # Then
        assert result is True

    def test_false_when_no_gitmodules(self, tmp_path, mocker):
        """Verify has_submodules returns False when no .gitmodules file at repo root."""
        # Given a repo root with no .gitmodules
        mocker.patch("gx.lib.workspace.repo_root", autospec=True, return_value=tmp_path)

        # When
        result = has_submodules()

        # Then
        assert result is False
