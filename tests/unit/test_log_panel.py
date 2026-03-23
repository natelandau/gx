"""Tests for LogPanel and LogEntry."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from gx.lib.console import GX_THEME
from gx.lib.log_panel import LogPanel, _parse_entries


class TestParseLogEntries:
    """Tests for parsing git log output into LogEntry objects."""

    def test_parses_default_format(self):
        """Verify parsing of SOH/null-delimited format without body."""
        # Given
        raw = (
            "\x019c96da2\x003 days ago\x00bump release\x00Nate Landau\x00HEAD -> main, origin/main"
            "\x01cdd86d0\x003 days ago\x00add version flag\x00Nate Landau\x00"
        )
        # When
        entries = _parse_entries(raw, has_body=False)
        # Then
        assert len(entries) == 2
        assert entries[0].sha == "9c96da2"
        assert entries[0].relative_time == "3 days ago"
        assert entries[0].subject == "bump release"
        assert entries[0].author == "Nate Landau"
        assert entries[0].branches == ("main",)
        assert entries[0].tags == ()
        assert entries[0].is_head is True
        assert entries[0].body == ""
        assert entries[1].sha == "cdd86d0"
        assert entries[1].branches == ()
        assert entries[1].tags == ()
        assert entries[1].is_head is False

    def test_parses_tags(self):
        """Verify tag refs are parsed into tags list."""
        # Given
        raw = "\x01abc1234\x002 hours ago\x00bump\x00Author\x00tag: v1.0, tag: v1.0.1"
        # When
        entries = _parse_entries(raw, has_body=False)
        # Then
        assert entries[0].tags == ("v1.0", "v1.0.1")
        assert entries[0].branches == ()

    def test_parses_branches_with_slashes(self):
        """Verify local branches with slashes are not treated as remotes."""
        # Given
        raw = "\x01abc1234\x002 hours ago\x00fix\x00Author\x00feat/my-feature"
        # When
        entries = _parse_entries(raw, has_body=False)
        # Then
        assert entries[0].branches == ("feat/my-feature",)

    def test_filters_out_remotes(self):
        """Verify remote refs are excluded."""
        # Given
        raw = "\x01abc1234\x002 hours ago\x00fix\x00Author\x00main, origin/main, upstream/main"
        # When
        entries = _parse_entries(raw, has_body=False)
        # Then
        assert entries[0].branches == ("main",)
        assert "origin/main" not in entries[0].branches
        assert "upstream/main" not in entries[0].branches

    def test_filters_out_head(self):
        """Verify HEAD and HEAD -> branch are excluded from branches list."""
        # Given
        raw = "\x01abc1234\x002 hours ago\x00fix\x00Author\x00HEAD -> main, HEAD"
        # When
        entries = _parse_entries(raw, has_body=False)
        # Then
        assert entries[0].branches == ("main",)
        assert entries[0].is_head is True

    def test_parses_full_format_with_body(self):
        """Verify parsing of format with multi-line commit body."""
        # Given
        raw = (
            "\x019c96da2\x003 days ago\x00bump release\x00Nate\x00HEAD -> main\x00"
            "Line one\nLine two\n"
            "\x01cdd86d0\x003 days ago\x00add flag\x00Nate\x00\x00"
        )
        # When
        entries = _parse_entries(raw, has_body=True)
        # Then
        assert len(entries) == 2
        assert entries[0].body == "Line one\nLine two"
        assert entries[1].body == ""

    def test_empty_output(self):
        """Verify empty list for empty git output."""
        # When
        entries = _parse_entries("", has_body=False)
        # Then
        assert entries == []


class TestLogPanelRender:
    """Tests for LogPanel rendering output."""

    def test_renders_sha_and_subject(self, mocker):
        """Verify panel output contains SHA and subject text."""
        # Given
        mocker.patch(
            "gx.lib.log_panel.git",
            autospec=True,
            return_value=mocker.Mock(
                success=True,
                stdout="\x019c96da2\x003 days ago\x00bump release\x00Nate\x00",
            ),
        )
        panel_obj = LogPanel(count=5)
        # When
        panel = panel_obj.render()
        # Then
        buf = StringIO()
        console = Console(file=buf, width=120, theme=GX_THEME)
        console.print(panel)
        output = buf.getvalue()
        assert "9c96da2" in output
        assert "bump release" in output

    def test_renders_branch_badge(self, mocker):
        """Verify branch names appear in panel output."""
        # Given
        mocker.patch(
            "gx.lib.log_panel.git",
            autospec=True,
            return_value=mocker.Mock(
                success=True,
                stdout="\x019c96da2\x003 days ago\x00bump\x00Nate\x00HEAD -> main",
            ),
        )
        panel_obj = LogPanel(count=5)
        # When
        panel = panel_obj.render()
        # Then
        buf = StringIO()
        console = Console(file=buf, width=120, theme=GX_THEME)
        console.print(panel)
        output = buf.getvalue()
        assert "main" in output

    def test_renders_tag_badge(self, mocker):
        """Verify tag names appear with icon in panel output."""
        # Given
        mocker.patch(
            "gx.lib.log_panel.git",
            autospec=True,
            return_value=mocker.Mock(
                success=True,
                stdout="\x019c96da2\x003 days ago\x00bump\x00Nate\x00tag: v1.0",
            ),
        )
        panel_obj = LogPanel(count=5)
        # When
        panel = panel_obj.render()
        # Then
        buf = StringIO()
        console = Console(file=buf, width=120, theme=GX_THEME)
        console.print(panel)
        output = buf.getvalue()
        assert "v1.0" in output
        assert "\U0001f3f7" in output  # 🏷

    def test_renders_body_when_enabled(self, mocker):
        """Verify commit body appears when show_body is True."""
        # Given
        mocker.patch(
            "gx.lib.log_panel.git",
            autospec=True,
            return_value=mocker.Mock(
                success=True,
                stdout="\x019c96da2\x003 days ago\x00bump\x00Nate\x00\x00Detailed body",
            ),
        )
        panel_obj = LogPanel(count=5, show_body=True)
        # When
        panel = panel_obj.render()
        # Then
        buf = StringIO()
        console = Console(file=buf, width=120, theme=GX_THEME)
        console.print(panel)
        output = buf.getvalue()
        assert "Detailed body" in output

    def test_returns_none_on_no_commits(self, mocker):
        """Verify None when git returns no output."""
        # Given
        mocker.patch(
            "gx.lib.log_panel.git",
            autospec=True,
            return_value=mocker.Mock(success=True, stdout=""),
        )
        panel_obj = LogPanel(count=5)
        # When
        result = panel_obj.render()
        # Then
        assert result is None

    def test_returns_none_on_git_failure(self, mocker):
        """Verify None when git command fails."""
        # Given
        mocker.patch(
            "gx.lib.log_panel.git",
            autospec=True,
            return_value=mocker.Mock(success=False, stdout=""),
        )
        panel_obj = LogPanel(count=5)
        # When
        result = panel_obj.render()
        # Then
        assert result is None

    def test_custom_title(self, mocker):
        """Verify panel uses custom title."""
        # Given
        mocker.patch(
            "gx.lib.log_panel.git",
            autospec=True,
            return_value=mocker.Mock(
                success=True,
                stdout="\x019c96da2\x003 days ago\x00bump\x00Nate\x00",
            ),
        )
        panel_obj = LogPanel(count=5, title="My Log")
        # When
        panel = panel_obj.render()
        # Then
        buf = StringIO()
        console = Console(file=buf, width=120, theme=GX_THEME)
        console.print(panel)
        output = buf.getvalue()
        assert "My Log" in output
