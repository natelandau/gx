"""Tests for LogGraph parsing, folding, and rendering."""

from __future__ import annotations

import pytest

from gx.lib.log_graph import (
    FOLD_MIN_RUN,
    GraphCommit,
    GraphFold,
    fold_runs,
    parse_graph_line,
    render_graph_line,
    short_age,
)

NOW = 1_000_000


def _commit(sha: str, prefix: str = "* ", refs: str = "") -> GraphCommit:
    return GraphCommit(
        prefix=prefix,
        sha=sha * 40,
        short_sha=sha * 7,
        timestamp=NOW - 3 * 86400,
        author="Nate",
        refs=refs,
        subject=f"commit {sha}",
    )


class TestParseGraphLine:
    """Tests for splitting raw graph output lines."""

    def test_commit_line(self):
        """Verify a commit line splits into graph prefix and fields."""
        # Given
        line = (
            "| * \x1f"
            + "a" * 40
            + "\x1faaaaaaa\x1f1700000000\x1fNate\x1fHEAD -> main\x1ffix(log): x"
        )
        # When
        parsed = parse_graph_line(line)
        # Then
        assert isinstance(parsed, GraphCommit)
        assert parsed.prefix == "| * "
        assert parsed.short_sha == "aaaaaaa"
        assert parsed.timestamp == 1_700_000_000
        assert parsed.refs == "HEAD -> main"
        assert parsed.subject == "fix(log): x"

    def test_connector_line(self):
        """Verify a connector-only line passes through unchanged."""
        # When
        parsed = parse_graph_line("|/  ")
        # Then
        assert parsed == "|/  "


class TestFoldRuns:
    """Tests for collapsing long runs of plain commits."""

    def test_long_run_folds_middle(self):
        """Verify a long run keeps its ends and folds the middle."""
        # Given
        lines = [_commit(c) for c in "abcdef"]
        # When
        out = fold_runs(lines, keep=frozenset())
        # Then
        assert out == [lines[0], GraphFold(prefix="* ", hidden=4), lines[-1]]

    def test_short_run_unfolded(self):
        """Verify a run shorter than the fold minimum is left alone."""
        # Given
        lines = [_commit(c) for c in "abcdef"[: FOLD_MIN_RUN - 1]]
        # When
        out = fold_runs(lines, keep=frozenset())
        # Then
        assert out == lines

    def test_decorated_commit_never_folds(self):
        """Verify a commit with refs breaks the run and stays visible."""
        # Given
        lines = [_commit(c) for c in "abc"] + [_commit("d", refs="tag: v1")]
        lines += [_commit(c) for c in "efg"]
        # When
        out = fold_runs(lines, keep=frozenset())
        # Then
        assert out == lines

    def test_kept_sha_never_folds(self):
        """Verify a fork point stays visible inside a long run."""
        # Given
        lines = [_commit(c) for c in "abcdefg"]
        # When
        out = fold_runs(lines, keep=frozenset({"d" * 40}))
        # Then
        assert out == lines

    def test_connector_and_prefix_change_split_runs(self):
        """Verify runs do not fold across a connector line or a lane change."""
        # Given
        lane_a = [_commit(c, prefix="| * ") for c in "abc"]
        lane_b = [_commit(c) for c in "def"]
        lines = [*lane_a, *lane_b, "|/  ", *[_commit(c) for c in "ghi"]]
        # When
        out = fold_runs(lines, keep=frozenset())
        # Then
        assert out == lines


class TestShortAge:
    """Tests for compact commit ages."""

    @pytest.mark.parametrize(
        ("elapsed", "expected"),
        [
            (0, "0s"),
            (45, "45s"),
            (40 * 60, "40m"),
            (3 * 3600, "3h"),
            (2 * 86400, "2d"),
            (15 * 86400, "2w"),
            (90 * 86400, "3mo"),
            (800 * 86400, "2y"),
            (-10, "0s"),
        ],
    )
    def test_units(self, elapsed, expected):
        """Verify the largest whole unit is used."""
        # When/Then
        assert short_age(NOW - elapsed, NOW) == expected


class TestRenderGraphLine:
    """Tests for styling graph lines."""

    def test_commit_line(self):
        """Verify refs and subject come before the compact age."""
        # Given
        commit = _commit("a", refs="HEAD -> main")
        # When
        text = render_graph_line(commit, now=NOW)
        # Then
        assert text.plain == "* aaaaaaa (HEAD -> main) commit a  3d"

    def test_commit_line_with_author(self):
        """Verify the author follows the age when requested."""
        # When
        text = render_graph_line(_commit("a"), now=NOW, show_author=True)
        # Then
        assert text.plain == "* aaaaaaa commit a  3d Nate"

    def test_metadata_dropped_when_too_wide(self):
        """Verify the age is dropped before the subject is cut."""
        # Given
        commit = _commit("a")
        # When
        text = render_graph_line(commit, now=NOW, width=len("* aaaaaaa commit a"))
        # Then
        assert text.plain == "* aaaaaaa commit a"

    def test_fold_line_keeps_lanes(self):
        """Verify a fold marker replaces the commit node and keeps other lanes."""
        # When
        text = render_graph_line(GraphFold(prefix="| * | ", hidden=5), now=NOW)
        # Then
        assert text.plain == "| ┊ | … 5 more commits"

    def test_connector_line(self):
        """Verify connector lines pass through."""
        # When
        text = render_graph_line("|\\  ", now=NOW)
        # Then
        assert text.plain == "|\\  "
