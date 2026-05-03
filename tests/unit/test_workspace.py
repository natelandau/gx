"""Tests for gx.lib.workspace primitives."""

from __future__ import annotations

from gx.lib.workspace import has_submodules, is_dirty, is_rebase_in_progress
from tests.conftest import make_tmp_dirty

from .conftest import _ok


class TestIsDirty:
    """Tests for the is_dirty helper function."""

    def test_dirty_when_changes_exist(self, tmp_git_repo):
        """Verify is_dirty returns True when working tree has changes."""
        make_tmp_dirty(tmp_git_repo)
        assert is_dirty() is True

    def test_clean_when_no_changes(self, tmp_git_repo):
        """Verify is_dirty returns False when working tree is clean."""
        assert is_dirty() is False


class TestHasSubmodules:
    """Tests for the has_submodules helper function."""

    def test_true_when_gitmodules_exists(self, tmp_path, monkeypatch):
        """Verify has_submodules returns True when .gitmodules file exists."""
        # Given a repo root with .git and .gitmodules
        (tmp_path / ".git").mkdir()
        (tmp_path / ".gitmodules").touch()
        monkeypatch.chdir(tmp_path)

        # When
        result = has_submodules()

        # Then
        assert result is True

    def test_false_when_no_gitmodules(self, tmp_path, monkeypatch):
        """Verify has_submodules returns False when no .gitmodules file."""
        # Given a repo root with .git but no .gitmodules
        (tmp_path / ".git").mkdir()
        monkeypatch.chdir(tmp_path)

        # When
        result = has_submodules()

        # Then
        assert result is False


class TestIsRebaseInProgress:
    """Tests for the is_rebase_in_progress helper function."""

    def test_true_when_rebase_merge_exists(self, mock_git, tmp_path):
        """Verify True when rebase-merge directory exists."""
        # Given
        (tmp_path / "rebase-merge").mkdir()
        mock_git.return_value = _ok(stdout=str(tmp_path))

        # When
        result = is_rebase_in_progress()

        # Then
        assert result is True

    def test_true_when_rebase_apply_exists(self, mock_git, tmp_path):
        """Verify True when rebase-apply directory exists."""
        # Given
        (tmp_path / "rebase-apply").mkdir()
        mock_git.return_value = _ok(stdout=str(tmp_path))

        # When
        result = is_rebase_in_progress()

        # Then
        assert result is True

    def test_false_when_no_rebase_dirs(self, mock_git, tmp_path):
        """Verify False when no rebase directories exist."""
        # Given
        mock_git.return_value = _ok(stdout=str(tmp_path))

        # When
        result = is_rebase_in_progress()

        # Then
        assert result is False
