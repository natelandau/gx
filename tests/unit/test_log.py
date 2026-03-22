"""Tests for gx log command."""

from __future__ import annotations

from gx.commands.log import parse_log_entries


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
        entries = parse_log_entries(raw, has_body=False)
        # Then
        assert len(entries) == 2
        assert entries[0].sha == "9c96da2"
        assert entries[0].relative_time == "3 days ago"
        assert entries[0].subject == "bump release"
        assert entries[0].author == "Nate Landau"
        assert entries[0].refs == "HEAD -> main, origin/main"
        assert entries[0].body == ""
        assert entries[1].sha == "cdd86d0"
        assert entries[1].refs == ""

    def test_parses_full_format_with_multiline_body(self):
        """Verify parsing of format with multi-line commit body."""
        # Given
        raw = (
            "\x019c96da2\x003 days ago\x00bump release\x00Nate Landau\x00HEAD -> main\x00"
            "Line one of body\nLine two of body\n"
            "\x01cdd86d0\x003 days ago\x00add flag\x00Nate Landau\x00\x00"
        )
        # When
        entries = parse_log_entries(raw, has_body=True)
        # Then
        assert len(entries) == 2
        assert entries[0].body == "Line one of body\nLine two of body"
        assert entries[1].body == ""

    def test_empty_output(self):
        """Verify empty list for empty git output."""
        # When
        entries = parse_log_entries("", has_body=False)
        # Then
        assert entries == []

    def test_single_entry_no_refs(self):
        """Verify parsing a single commit with no decorations."""
        # Given
        raw = "\x01abc1234\x002 hours ago\x00fix bug\x00Author\x00"
        # When
        entries = parse_log_entries(raw, has_body=False)
        # Then
        assert len(entries) == 1
        assert entries[0].refs == ""
        assert entries[0].body == ""
