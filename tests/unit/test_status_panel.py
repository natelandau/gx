"""Tests for StatusPanel and porcelain parsing."""

from __future__ import annotations

from gx.lib.status_panel import StatusPanel, _build_file_tree, _parse_porcelain


class TestParsePorcelain:
    """Tests for parsing git status --porcelain output."""

    def test_parses_modified_staged_untracked(self):
        """Verify correct parsing of mixed status output."""
        # Given
        lines = " M src/gx/cli.py\nA  src/gx/commands/status.py\n?? tests/test_new.py\nMM pyproject.toml"
        # When
        result = _parse_porcelain(lines)
        # Then
        assert len(result) == 4
        assert result[0] == (" M", "src/gx/cli.py")
        assert result[1] == ("A ", "src/gx/commands/status.py")
        assert result[2] == ("??", "tests/test_new.py")
        assert result[3] == ("MM", "pyproject.toml")

    def test_empty_output(self):
        """Verify empty list for clean working tree."""
        result = _parse_porcelain("")
        assert result == []

    def test_renamed_file(self):
        """Verify renamed files are parsed with the new name."""
        lines = "R  old_name.py -> new_name.py"
        result = _parse_porcelain(lines)
        assert result[0] == ("R ", "new_name.py")


class TestBuildFileTree:
    """Tests for building the Rich Tree from parsed status entries."""

    def test_builds_nested_tree(self):
        """Verify files are nested under their directory paths."""
        entries = [
            (" M", "src/gx/cli.py"),
            ("A ", "src/gx/commands/status.py"),
            ("??", "README.md"),
        ]
        tree = _build_file_tree(entries, "myrepo")
        assert "myrepo" in str(tree.label)

    def test_empty_entries_returns_none(self):
        """Verify None returned for empty entry list."""
        result = _build_file_tree([], "myrepo")
        assert result is None


class TestStatusPanel:
    """Tests for the StatusPanel class."""

    def test_render_with_changes(self):
        """Verify render returns a Tree when there are changes."""
        # Given
        panel = StatusPanel(" M file.py", "myrepo")
        # When
        result = panel.render()
        # Then
        assert result is not None
        assert "myrepo" in str(result.label)

    def test_render_clean_tree(self):
        """Verify render returns info text when porcelain is empty."""
        # Given
        panel = StatusPanel("", "myrepo")
        # When
        result = panel.render()
        # Then
        assert "Working tree clean" in str(result)
