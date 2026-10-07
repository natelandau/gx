"""Tests for LogGraph parsing, folding, and rendering."""

from __future__ import annotations

import re
from io import StringIO
from typing import TYPE_CHECKING

import pytest
import typer
from nclutils.sh import CompletedCommand
from rich.console import Console
from rich.text import Text

from gx.lib.config import GxConfig
from gx.lib.graph_layout import (
    ASCII,
    BRANCH_SYMBOLS,
    UNICODE,
    Cell,
    GraphOrderError,
    LayoutCommit,
    NodeKind,
    Pipe,
    PipeKind,
    Row,
    draw,
    fade_cells,
    layout,
    row_cells,
)
from gx.lib.log_context import BranchRefs, BranchState, LogContext
from gx.lib.log_graph import (
    FOLD_MIN_RUN,
    CommitRecord,
    GraphEntry,
    LaneFold,
    LogGraph,
    _escape_glob,
    _graph_text,
    fold_entries,
    is_straight,
    join_blocks,
    parse_commit_line,
    render_legend,
    render_line,
    short_age,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

NOW = 1_000_000


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


def _sha(name: str) -> str:
    return name * 40


def _record(name: str, parents: tuple[str, ...] = (), refs: str = "") -> CommitRecord:
    return CommitRecord(
        sha=_sha(name),
        parents=tuple(_sha(p) for p in parents),
        short_sha=name * 7,
        timestamp=NOW,
        author="Nate",
        refs=refs,
        subject=f"commit {name}",
    )


def _entries(records: list[CommitRecord], trunk: frozenset[str] = frozenset()) -> list[GraphEntry]:
    rows = layout([LayoutCommit(r.sha, r.parents) for r in records], trunk)
    return [GraphEntry(commit=r, row=row) for r, row in zip(records, rows, strict=True)]


def _chain(names: str, refs: dict[str, str] | None = None) -> list[CommitRecord]:
    # The last commit points at an unlisted parent so it stays a straight row.
    refs = refs or {}
    return [
        _record(n, (names[i + 1] if i + 1 < len(names) else "z",), refs.get(n, ""))
        for i, n in enumerate(names)
    ]


def _context(
    owners: Mapping[str, str] | None = None,
    *,
    current: str | None = None,
    head_reachable: frozenset[str] | None = None,
    parents: Mapping[str, tuple[str, ...]] | None = None,
    everything_reachable: bool = True,
    remotes: frozenset[str] = frozenset({"origin"}),
    unpushed: frozenset[str] = frozenset(),
    upstreams: Mapping[str, BranchState] | None = None,
) -> LogContext:
    """Build a context with `main` as the colorless default and `feat` colored cyan.

    `upstreams` replaces the default branch states by name, to attach upstream data.
    """
    owners = owners or {}
    parents = parents or {}
    if head_reachable is None:
        head_reachable = (
            frozenset(parents) | frozenset(owners) | {_sha("a")}
            if everything_reachable
            else frozenset()
        )
    branches = {
        "main": BranchState(name="main", color="", is_current=current == "main", is_default=True),
        "feat": BranchState(
            name="feat", color="cyan", is_current=current == "feat", is_default=False
        ),
        **(upstreams or {}),
    }
    return LogContext(
        default="main",
        current=current,
        branches=branches,
        owners=owners,
        head_reachable=head_reachable,
        parents=parents,
        unpushed=unpushed,
        remotes=remotes,
    )


class TestParseCommitLine:
    """Parsing of the layout-format commit line."""

    def test_splits_parents(self) -> None:
        """Space-separated parents become a tuple and fields are mapped."""
        # Given a merge commit line
        line = (
            "a" * 40
            + "\x1f"
            + "b" * 40
            + " "
            + "c" * 40
            + "\x1faaaaaaa\x1f1700000000\x1fNate\x1fHEAD -> main\x1ffix: x"
        )

        # When parsed
        c = parse_commit_line(line)

        # Then both parents and the other fields are present
        assert c is not None
        assert c.parents == ("b" * 40, "c" * 40)
        assert c.timestamp == 1_700_000_000
        assert c.refs == "HEAD -> main"

    def test_root_has_no_parents(self) -> None:
        """A root commit has an empty parents field."""
        # Given a root commit line
        line = "a" * 40 + "\x1f\x1faaaaaaa\x1f1\x1fN\x1f\x1fs"

        # When parsed
        c = parse_commit_line(line)

        # Then it has no parents
        assert c is not None
        assert c.parents == ()

    def test_malformed_returns_none(self) -> None:
        """A line without the expected fields is rejected."""
        # Given / When / Then
        assert parse_commit_line("garbage") is None

    def test_too_few_fields_returns_none(self) -> None:
        """A line missing its subject field is rejected."""
        # Given six fields instead of seven
        line = "\x1f".join(["a" * 40, "", "aaaaaaa", "1", "N", ""])

        # When / Then
        assert parse_commit_line(line) is None

    def test_separator_in_subject_is_kept(self) -> None:
        """A field separator inside the subject stays part of the subject."""
        # Given a subject containing the separator
        line = "\x1f".join(["a" * 40, "", "aaaaaaa", "1", "N", "", "left\x1fright"])

        # When
        c = parse_commit_line(line)

        # Then the commit is not dropped
        assert c is not None
        assert c.subject == "left\x1fright"

    @pytest.mark.parametrize("timestamp", ["abc", "", "\u0663", "-5"])
    def test_non_digit_timestamp_falls_back_to_zero(self, timestamp: str) -> None:
        """A timestamp that is not plain ASCII digits parses as zero."""
        # Given
        line = "\x1f".join(["a" * 40, "", "aaaaaaa", timestamp, "N", "", "s"])

        # When
        c = parse_commit_line(line)

        # Then
        assert c is not None
        assert c.timestamp == 0

    def test_empty_sha_returns_none(self) -> None:
        """A line whose sha field is empty is rejected."""
        # Given
        line = "\x1f\x1faaaaaaa\x1f1\x1fN\x1f\x1fs"

        # When / Then
        assert parse_commit_line(line) is None


class TestFoldEntries:
    """Folding of straight runs of plain commits on layout rows."""

    def test_long_run_folds_middle(self) -> None:
        """Six plain commits keep first and last around a fold of four."""
        # Given a linear chain of six commits
        entries = _entries(_chain("abcdef"))

        # When folded
        out = fold_entries(entries, frozenset())

        # Then the middle four are hidden
        assert out[0] == entries[0]
        assert out[1] == LaneFold(lane=0, lanes=frozenset({0}), hidden=4, row=entries[1].row)
        assert out[2] == entries[-1]
        assert len(out) == 3

    def test_short_run_unfolded(self) -> None:
        """Runs shorter than FOLD_MIN_RUN are untouched."""
        # Given a chain one commit short of the threshold
        entries = _entries(_chain("abcdef"[: FOLD_MIN_RUN - 1]))

        # When folded
        out = fold_entries(entries, frozenset())

        # Then nothing changes
        assert out == entries

    def test_decorated_commit_never_folds(self) -> None:
        """A commit with refs breaks the run."""
        # Given a decorated commit in the middle of a chain
        entries = _entries(_chain("abcdefg", {"d": "tag: v1"}))

        # When folded
        out = fold_entries(entries, frozenset())

        # Then the decorated commit is shown and neither side folds
        assert entries[3] in out
        assert not any(isinstance(o, LaneFold) for o in out)

    def test_kept_sha_never_folds(self) -> None:
        """A commit in keep breaks the run."""
        # Given a chain with a kept commit in the middle
        entries = _entries(_chain("abcdefg"))

        # When folded
        out = fold_entries(entries, frozenset({_sha("d")}))

        # Then the kept commit is shown and neither side folds
        assert entries[3] in out
        assert not any(isinstance(o, LaneFold) for o in out)

    def test_run_in_side_lane_beside_trunk(self) -> None:
        """A long feature run folds in lane 1 above the trunk tip."""
        # Given six feature commits off a two-commit trunk
        records = [
            _record("a", ("b",)),
            _record("b", ("c",)),
            _record("c", ("d",)),
            _record("d", ("e",)),
            _record("e", ("f",)),
            _record("f", ("h",)),
            _record("g", ("h",)),
            _record("h"),
        ]
        entries = _entries(records, frozenset({_sha("g"), _sha("h")}))

        # When folded
        out = fold_entries(entries, frozenset())

        # Then the feature run folds in lane 1
        folds = [o for o in out if isinstance(o, LaneFold)]
        assert folds == [LaneFold(lane=1, lanes=frozenset({1}), hidden=4, row=entries[1].row)]
        assert out.index(folds[0]) < out.index(entries[6])

    def test_fork_row_breaks_run(self) -> None:
        """A row whose terminating pipe changes lane is not straight."""
        # Given a fork row: lane-1 pipe terminates into a lane-0 commit
        fork = Row(
            sha=_sha("c"),
            lane=0,
            pipes=(
                Pipe(_sha("a"), _sha("c"), 1, 0, PipeKind.TERMINATES),
                Pipe(_sha("c"), _sha("d"), 0, 0, PipeKind.STARTS),
            ),
            is_merge=False,
        )
        straight = _entries(_chain("abcdefgh"))
        entries = [*straight[:2], GraphEntry(straight[2].commit, fork), *straight[3:]]

        # When folded
        out = fold_entries(entries, frozenset())

        # Then the fork row is not straight and stays visible
        assert not is_straight(fork)
        assert entries[2] in out

    def test_lane_set_change_breaks_run(self) -> None:
        """Rows with different open lanes never join one run."""
        # Given straight rows in lane 0 whose open lanes differ halfway
        records = _chain("abcdefgh")
        base = _entries(records)
        extra = Pipe(_sha("z"), _sha("y"), 1, 1, PipeKind.CONTINUES)
        entries = [
            *base[:4],
            *(
                GraphEntry(e.commit, Row(e.row.sha, 0, (*e.row.pipes, extra), is_merge=False))
                for e in base[4:]
            ),
        ]

        # When folded
        out = fold_entries(entries, frozenset())

        # Then each four-commit half folds on its own
        folds = [o for o in out if isinstance(o, LaneFold)]
        assert [f.lanes for f in folds] == [frozenset({0}), frozenset({0, 1})]


def _style_at(text: Text, index: int) -> str | None:
    """Return the style of the innermost span covering a plain-text offset, or None if none does."""
    covering = [str(s.style) for s in text.spans if s.start <= index < s.end]
    return covering[-1] if covering else None


def _tip(name: str, refs: str = "", *, parents: tuple[str, ...] = ("z",)) -> GraphEntry:
    return _entries([_record(name, parents, refs)])[0]


class TestRenderLine:
    """Styling of laid-out graph lines."""

    def test_commit_line_layout(self) -> None:
        """An entry draws graph, SHA, subject, and age."""
        # Given / When
        text = render_line(_tip("a"), UNICODE, context=_context(), now=NOW + 3 * 86400)

        # Then
        assert text.plain == "● aaaaaaa commit a  3d"

    def test_ascii_charset(self) -> None:
        """The ascii charset draws an asterisk node."""
        # Given / When
        text = render_line(_tip("a"), ASCII, context=_context(), now=NOW)

        # Then
        assert text.plain.startswith("* aaaaaaa")

    def test_commit_line_with_refs_and_author(self) -> None:
        """Badges sit before the subject and the author follows the age."""
        # Given / When
        text = render_line(
            _tip("a", "tag: v1"), UNICODE, context=_context(), now=NOW, show_author=True
        )

        # Then
        assert text.plain == "● aaaaaaa ◆ v1 commit a  0s Nate"

    def test_refs_render_as_badges(self) -> None:
        """Refs become typed badges with no raw magenta ref text."""
        text = render_line(
            _tip("a", "HEAD -> feat, origin/main, tag: v1"),
            UNICODE,
            context=_context({_sha("a"): "feat"}, current="feat"),
            now=NOW,
        )
        assert "[feat] ◆ v1 origin/main commit a" in text.plain
        assert _style_at(text, text.plain.index("[feat]")) == "reverse cyan"
        assert _style_at(text, text.plain.index("◆ v1")) == "bold"
        assert _style_at(text, text.plain.index("origin/main")) == "dim"

    def test_badges_ascii(self) -> None:
        """The ascii charset uses the ascii tag glyph."""
        text = render_line(_tip("a", "tag: v1"), ASCII, context=_context(), now=NOW)
        assert "# v1 commit a" in text.plain

    def test_unpushed_marker_ascii(self) -> None:
        """The ascii unpushed marker is `+`, never git's parent-of `^`."""
        text = render_line(
            _tip("a"), ASCII, context=_context(unpushed=frozenset({_sha("a")})), now=NOW
        )
        assert "aaaaaaa+ commit a" in text.plain

    def test_detached_head_node_and_badge(self) -> None:
        """A detached HEAD draws the HEAD node and a plain HEAD badge."""
        text = render_line(_tip("a", "HEAD"), UNICODE, context=_context(), now=NOW)
        assert text.plain.startswith("◉ ")
        assert "[HEAD] commit a" in text.plain

    def test_unpushed_marker_after_sha(self) -> None:
        """An unpushed commit gets a dim marker glued to its SHA."""
        text = render_line(
            _tip("a"), UNICODE, context=_context(unpushed=frozenset({_sha("a")})), now=NOW
        )
        assert "aaaaaaa↑ commit a" in text.plain
        assert _style_at(text, text.plain.index("↑")) == "dim"

    def test_pushed_commit_has_no_marker(self) -> None:
        """A commit outside the unpushed set has no marker."""
        assert "↑" not in render_line(_tip("a"), UNICODE, context=_context(), now=NOW).plain

    def test_metadata_dropped_before_subject_cut_with_badges(self) -> None:
        """Badges count toward the width, so metadata drops while badges stay."""
        line = _tip("a", "HEAD -> feat, tag: v1")
        full = render_line(line, UNICODE, context=_context(current="feat"), now=NOW)
        narrow = render_line(
            line, UNICODE, context=_context(current="feat"), now=NOW, width=len(full.plain) - 1
        )
        assert narrow.plain.endswith("commit a")
        assert "[feat] ◆ v1" in narrow.plain

    def test_badges_without_color_snapshot(self) -> None:
        """A small graph renders the expected badges, sync marks, unpushed marker, and legend."""
        # Given feat checked out one commit ahead, main in sync with origin/main,
        # a solo branch with no upstream, and a detached HEAD row
        records = [
            _record("a", ("b",), "HEAD -> feat"),
            _record("b", ("c",), "main, origin/main, tag: v1"),
            _record("c", ("d",), "solo"),
            _record("d", ("z",), "HEAD"),
        ]
        context = _context(
            current="feat",
            unpushed=frozenset({_sha("a")}),
            upstreams={
                "feat": BranchState(
                    name="feat",
                    color="cyan",
                    is_current=True,
                    is_default=False,
                    upstream="origin/feat",
                    ahead=1,
                    has_remote_upstream=True,
                ),
                "main": BranchState(
                    name="main",
                    color="",
                    is_current=False,
                    is_default=True,
                    upstream="origin/main",
                    has_remote_upstream=True,
                ),
                "solo": BranchState(
                    name="solo", color="magenta", is_current=False, is_default=False
                ),
            },
        )

        # When rendered without color
        console = Console(file=StringIO(), no_color=True, width=120, force_terminal=False)
        for entry in _entries(records):
            console.print(render_line(entry, UNICODE, context=context, now=NOW))
        legend = render_legend(context, UNICODE, None)
        assert legend is not None
        console.print(legend)

        # Then each line matches the badge rules
        assert console.file.getvalue() == (
            "◉ aaaaaaa↑ [feat ↑1] commit a  0s\n"
            "● bbbbbbb (main ⇅) ◆ v1 commit b  0s\n"
            "● ccccccc (solo) commit c  0s\n"
            "◉ ddddddd [HEAD] commit d  0s\n"
            "● main  ● feat (current)  ● solo local\n"
        )

    @pytest.mark.parametrize("refs", ["HEAD -> main", "HEAD"])
    def test_head_commit_uses_head_node(self, refs: str) -> None:
        """A HEAD ref draws the HEAD node."""
        # Given / When
        text = render_line(_tip("a", refs), UNICODE, context=_context(), now=NOW)

        # Then
        assert text.plain.startswith("◉ ")

    def test_merge_commit_uses_merge_node(self) -> None:
        """A merge commit draws the merge node."""
        # Given
        entries = _entries([_record("a", ("b", "c")), _record("b", ("z",)), _record("c", ("z",))])

        # When
        text = render_line(entries[0], UNICODE, context=_context(), now=NOW)

        # Then
        assert text.plain.startswith("◎")

    def test_fold_marker_is_dim(self) -> None:
        """The fold glyph is dim along with the rest of the fold line."""
        # Given / When
        text = render_line(
            LaneFold(lane=0, lanes=frozenset({0}), hidden=3), UNICODE, context=_context(), now=NOW
        )

        # Then
        assert text.plain.startswith("┊")
        assert _style_at(text, 0) == "dim"

    def test_fade_marker_is_dim(self) -> None:
        """The fade glyph is dim."""
        # Given a graph whose last commit leaves a lane open
        text = _graph_text(fade_cells(_tip("a").row) or [], UNICODE, _context(), node_style="dim")

        # Then
        assert text.plain == "╎"
        assert _style_at(text, 0) == "dim"

    def test_line_glyph_takes_pipe_style(self) -> None:
        """A lane glyph's first character takes its pipe's style, the second its horizontal's."""
        # Given a feat-owned vertical and a main-owned horizontal
        vertical = Pipe(_sha("a"), _sha("c"), 0, 0, PipeKind.STARTS)
        horizontal = Pipe(_sha("a"), _sha("b"), 0, 1, PipeKind.STARTS)
        context = _context(
            {_sha("a"): "feat", _sha("b"): "main"},
            parents={_sha("a"): (_sha("c"), _sha("b"))},
        )

        # When
        only_vertical = _graph_text([Cell(up=True, down=True, vertical=vertical)], UNICODE, context)
        only_horizontal = _graph_text(
            [Cell(up=True, right=True, horizontal=horizontal)], UNICODE, context
        )
        both = _graph_text(
            [Cell(up=True, right=True, vertical=vertical, horizontal=horizontal)], UNICODE, context
        )

        # Then the lone vertical colors its glyph and leaves the pad unstyled
        assert only_vertical.plain == "│"
        assert _style_at(only_vertical, 0) == "cyan"
        # And a lone horizontal colors both characters by the main pipe
        assert only_horizontal.plain == "╰─"
        assert _style_at(only_horizontal, 0) is None
        assert _style_at(only_horizontal, 1) is None
        # And a vertical beside a horizontal keeps the vertical color on the first character only
        assert _style_at(both, 0) == "cyan"
        assert _style_at(both, 1) is None

    def test_crossing_uses_vertical_color(self) -> None:
        """Where a horizontal crosses a vertical, the first character takes the vertical's color."""
        # Given a crossing whose vertical belongs to feat and horizontal to main
        vertical = Pipe(_sha("a"), _sha("c"), 0, 0, PipeKind.STARTS)
        horizontal = Pipe(_sha("a"), _sha("b"), 0, 2, PipeKind.STARTS)
        context = _context(
            {_sha("a"): "feat", _sha("b"): "main"},
            parents={_sha("a"): (_sha("c"), _sha("b"))},
        )
        cell = Cell(
            up=True, down=True, left=True, right=True, vertical=vertical, horizontal=horizontal
        )

        # When
        text = _graph_text([cell, Cell(up=True)], UNICODE, context)

        # Then the crossing glyph is feat-colored and its trailing connector is main's (plain)
        assert text.plain.startswith("│─")
        assert _style_at(text, 0) == "cyan"
        assert _style_at(text, 1) is None

        # And with the roles swapped the connector takes the horizontal's color
        swapped = _context(
            {_sha("a"): "main", _sha("b"): "feat"},
            parents={_sha("a"): (_sha("c"), _sha("b"))},
        )
        text = _graph_text([cell], UNICODE, swapped)
        assert _style_at(text, 0) is None
        assert _style_at(text, 1) == "cyan"

    def test_side_lane_takes_its_pipe_color(self) -> None:
        """A lane beside the node is colored by its owner: feat literal, main plain, unowned dim."""
        # Given a feature tip and a main tip sharing a parent, laid out for real
        entries = _entries(
            [_record("a", ("c",)), _record("b", ("c",)), _record("c")],
            frozenset({_sha("b"), _sha("c")}),
        )
        parents = {_sha(n): (_sha("c"),) for n in "ab"} | {_sha("c"): ()}

        def side_lane_style(owners: dict[str, str]) -> str:
            context = _context(owners, parents=parents)
            text = render_line(entries[1], UNICODE, context=context, now=NOW)
            lane = text.plain.index("│")
            return _style_at(text, lane)

        # When / Then
        assert side_lane_style({_sha("a"): "feat", _sha("b"): "main"}) == "cyan"
        assert side_lane_style({_sha("a"): "main", _sha("b"): "main"}) is None
        assert side_lane_style({_sha("b"): "main"}) == "dim"

    def test_fold_pass_through_lane_is_colored(self) -> None:
        """Another branch's lane running past a fold keeps its color."""
        # Given a feat tip x beside a six-commit main run that folds, laid out for real
        records = [
            _record("x", ("h",)),
            *[_record(n, (nxt,)) for n, nxt in zip("abcde", "bcdef", strict=True)],
            _record("f", ("h",)),
            _record("h"),
        ]
        entries = _entries(records, frozenset({_sha("h")}))
        folds = [o for o in fold_entries(entries, frozenset()) if isinstance(o, LaneFold)]
        assert len(folds) == 1
        owners = {_sha("x"): "feat", **{_sha(n): "main" for n in "abcdefh"}}
        parents = {r.sha: r.parents for r in records}
        context = _context(owners, parents=parents)

        # When
        text = render_line(folds[0], UNICODE, context=context, now=NOW)

        # Then the pass-through lane is cyan and the marker is the run's dimmed plain style
        lane = text.plain.index("│")
        assert _style_at(text, lane) == "cyan"
        assert _style_at(text, text.plain.index("┊")) == "dim"

    def test_node_takes_commit_style(self) -> None:
        """The node character takes the owner's color."""
        # Given a commit owned by feat
        entry = _tip("a")
        context = _context({_sha("a"): "feat"})

        # When
        text = render_line(entry, UNICODE, context=context, now=NOW)

        # Then
        assert _style_at(text, 0) == "cyan"

    def test_sha_takes_owner_color(self) -> None:
        """A feature SHA is colored; default and unowned SHAs are unstyled."""
        # Given
        sha_at = len("● ")
        feat = render_line(_tip("a"), UNICODE, context=_context({_sha("a"): "feat"}), now=NOW)
        main = render_line(_tip("a"), UNICODE, context=_context({_sha("a"): "main"}), now=NOW)
        unowned = render_line(_tip("a"), UNICODE, context=_context(), now=NOW)

        # Then
        assert _style_at(feat, sha_at) == "cyan"
        assert _style_at(main, sha_at) is None
        assert _style_at(unowned, sha_at) is None

    def test_age_is_dim(self) -> None:
        """The age is dim."""
        # Given / When
        text = render_line(_tip("a"), UNICODE, context=_context(), now=NOW)

        # Then
        assert _style_at(text, len(text.plain) - 1) == "dim"

    def test_current_branch_subject_is_bold(self) -> None:
        """Subjects of commits on the checked-out branch are bold."""
        # Given
        subject_at = len("● aaaaaaa ")
        current = render_line(
            _tip("a"), UNICODE, context=_context({_sha("a"): "feat"}, current="feat"), now=NOW
        )
        other = render_line(
            _tip("a"), UNICODE, context=_context({_sha("a"): "feat"}, current="main"), now=NOW
        )

        # Then
        assert _style_at(current, subject_at) == "bold"
        assert _style_at(other, subject_at) is None

    def test_unreachable_line_is_dim(self) -> None:
        """A commit HEAD cannot reach dims its node and text, keeping the node's hue."""
        # Given a feat commit outside HEAD's reach
        context = _context({_sha("a"): "feat"}, everything_reachable=False)

        # When
        text = render_line(_tip("a"), UNICODE, context=context, now=NOW)

        # Then the node keeps its hue and dims
        assert _style_at(text, 0) == "cyan dim"
        # And everything after the graph is dim
        graph_end = len(text.plain.split(" ", 1)[0])
        for index in range(graph_end, len(text.plain)):
            covering = [str(sp.style) for sp in text.spans if sp.start <= index < sp.end]
            assert text.plain[index] == " " or any("dim" in style.split() for style in covering)

    def test_unreachable_line_stays_dim_when_metadata_dropped(self) -> None:
        """Dropping the metadata for width does not lose the dim on the text."""
        # Given an unreachable feat commit and a width that fits only the subject
        context = _context({_sha("a"): "feat"}, everything_reachable=False)
        width = len("● aaaaaaa commit a")

        # When
        text = render_line(_tip("a"), UNICODE, context=context, now=NOW, width=width)

        # Then
        assert text.plain == "● aaaaaaa commit a"
        for index in range(2, len(text.plain)):
            covering = [str(sp.style) for sp in text.spans if sp.start <= index < sp.end]
            assert text.plain[index] == " " or any("dim" in style.split() for style in covering)

    def test_unreachable_row_keeps_reachable_lane_undimmed(self) -> None:
        """A reachable branch's lane passing an unreachable commit's row is not dimmed."""
        # Given a reachable feat tip beside an unreachable main commit, laid out for real
        entries = _entries(
            [_record("f", ("m",)), _record("u", ("m",)), _record("m")],
            frozenset({_sha("u"), _sha("m")}),
        )
        parents = {_sha("f"): (_sha("m"),), _sha("u"): (_sha("m"),), _sha("m"): ()}
        owners = {_sha("f"): "feat", _sha("u"): "main", _sha("m"): "main"}
        context = _context(
            owners, parents=parents, head_reachable=frozenset({_sha("f"), _sha("m")})
        )

        # When the unreachable commit's row is rendered
        text = render_line(entries[1], UNICODE, context=context, now=NOW)

        # Then the passing feat lane keeps its plain color
        lane = text.plain.index("│")
        assert _style_at(text, lane) == "cyan"
        # And the unreachable node and its text are dim
        assert "dim" in (_style_at(text, text.plain.index("●")) or "").split()
        assert "dim" in (_style_at(text, text.plain.index("commit u")) or "").split()

    def test_fold_marker_takes_run_color_and_names_branch(self) -> None:
        """A fold in a feature run is colored like the run and names its branch."""
        # Given a fold whose first hidden commit belongs to feat
        row = _tip("a").row
        context = _context({_sha("a"): "feat"})
        fold = LaneFold(lane=0, lanes=frozenset({0}), hidden=5, row=row)

        # When
        text = render_line(fold, UNICODE, context=context, now=NOW)

        # Then
        assert text.plain.endswith("… 5 more commits on feat")
        assert _style_at(text, 0) == "cyan dim"

    def test_fold_label_without_owner(self) -> None:
        """An unowned run has no owner suffix and a dim marker."""
        # Given / When
        text = render_line(
            LaneFold(lane=0, lanes=frozenset({0}), hidden=5, row=_tip("a").row),
            UNICODE,
            context=_context(),
            now=NOW,
        )

        # Then
        assert text.plain.endswith("5 more commits")
        assert _style_at(text, 0) == "dim"

    def test_metadata_dropped_before_subject_cut(self) -> None:
        """The age is dropped before the subject is cut."""
        # Given / When
        text = render_line(
            _tip("a"), UNICODE, context=_context(), now=NOW, width=len("● aaaaaaa commit a")
        )

        # Then
        assert text.plain == "● aaaaaaa commit a"

    def test_fold_line(self) -> None:
        """A fold draws the fold marker in its lane and keeps other lanes."""
        # Given / When
        text = render_line(
            LaneFold(lane=1, lanes=frozenset({0, 1}), hidden=5),
            UNICODE,
            context=_context(),
            now=NOW,
        )

        # Then
        assert text.plain == "│ ┊ … 5 more commits"
        assert text.spans[-1].style == "dim italic"

    def test_fold_line_singular(self) -> None:
        """One hidden commit uses the singular noun."""
        # Given / When
        text = render_line(
            LaneFold(lane=0, lanes=frozenset({0}), hidden=1), UNICODE, context=_context(), now=NOW
        )

        # Then
        assert text.plain.endswith("1 more commit")

    def test_wide_graph_on_narrow_terminal(self) -> None:
        """A graph wider than the terminal never raises and never cuts a cell."""
        # Given 30 branch tips forking from one root
        names = [f"t{i:02d}" for i in range(30)]
        records = [_record(n, ("root",)) for n in names]
        records.append(_record("root"))
        entries = _entries(records)

        # When
        lines = [render_line(e, UNICODE, context=_context(), now=NOW, width=20) for e in entries]

        # Then the whole graph is drawn uncut and the metadata is dropped
        for entry, line in zip(entries, lines, strict=True):
            graph = draw(row_cells(entry.row, NodeKind.COMMIT), UNICODE)
            assert line.plain.startswith(f"{graph} {entry.commit.short_sha}")
            assert not line.plain.endswith("0s")


def _git_result(stdout: str, *, ok: bool = True) -> CompletedCommand:
    return CompletedCommand(
        argv=("git",),
        returncode=0 if ok else 1,
        stdout=stdout,
        stderr="",
        duration=0.0,
        cwd=None,
    )


class TestLogGraphRender:
    """LogGraph.render orchestration with git stubbed out."""

    @staticmethod
    def _line(name: str, parents: tuple[str, ...], author: str = "Nate") -> str:
        rec = _record(name, parents)
        return "\x1f".join(
            [rec.sha, " ".join(rec.parents), rec.short_sha, "1", author, "", rec.subject]
        )

    def _patch(self, mocker, lines: list[str], default: str | None = "main") -> None:
        mocker.patch("gx.lib.log_graph.find_default_branch", return_value=default)
        mocker.patch.object(LogGraph, "_fork_points", return_value=frozenset())
        mocker.patch.object(LogGraph, "_window_queries", return_value=[[]])
        mocker.patch("gx.lib.log_graph.config", GxConfig(graph_style="unicode"))
        mocker.patch("gx.lib.log_graph.build_log_context", return_value=_context())
        mocker.patch("gx.lib.log_graph.render_legend", return_value=None)
        mocker.patch(
            "gx.lib.log_graph.git",
            side_effect=lambda *a, **k: (
                _git_result("\n".join(lines)) if a[0] == "log" else _git_result("", ok=False)
            ),
        )

    def test_order_error_exits_without_drawing(self, mocker) -> None:
        """A GraphOrderError reports an error and exits 1."""
        # Given layout rejecting git's ordering
        self._patch(mocker, [self._line("a", ())])
        mocker.patch("gx.lib.log_graph.layout", side_effect=GraphOrderError("bad"))
        error = mocker.patch("gx.lib.log_graph.pp.error")

        # When / Then
        with pytest.raises(typer.Exit) as exc:
            LogGraph().render()
        assert exc.value.exit_code == 1
        error.assert_called_once()
        assert "out of topological order" in error.call_args.args[0]

    def test_fade_line_appended_when_lanes_open(self, mocker) -> None:
        """A last row whose parent is outside the window leaves a fade line."""
        # Given a single commit whose parent is not in the window
        self._patch(mocker, [self._line("a", ("z",))])

        # When
        out = LogGraph().render()

        # Then
        assert len(out) == 2
        assert out[1].plain == "╎"

    def test_no_fade_line_when_all_lanes_closed(self, mocker) -> None:
        """A root commit closes every lane, so no fade line is drawn."""
        # Given
        self._patch(mocker, [self._line("a", ())])

        # When / Then
        assert len(LogGraph().render()) == 1

    def test_legend_appended_after_blank_line(self, mocker) -> None:
        """A legend is separated from the graph by a blank line."""
        # Given a render whose legend exists
        self._patch(mocker, [self._line("a", ())])
        mocker.patch("gx.lib.log_graph.render_legend", return_value=Text("legend"))

        # When
        out = LogGraph().render()

        # Then the blank line and legend close the output
        assert [t.plain for t in out[-2:]] == ["", "legend"]

    def test_context_built_once_from_window(self, mocker) -> None:
        """The branch context is built once from the window's parents and default tip."""
        # Given a two-commit window with a resolvable default tip
        self._patch(mocker, [self._line("a", ("b",)), self._line("b", ())])
        mocker.patch.object(LogGraph, "_resolve_default", return_value=("main", _sha("a")))
        refs = BranchRefs(tips={"main": _sha("a")}, current="main", head_sha=_sha("a"))
        mocker.patch("gx.lib.log_graph.read_branch_refs", return_value=refs)
        build = mocker.patch("gx.lib.log_graph.build_log_context", return_value=_context())

        # When
        LogGraph().render()

        # Then the refs read once for fork points are reused for the context
        build.assert_called_once_with(
            {_sha("a"): (_sha("b"),), _sha("b"): ()},
            default="main",
            default_tip=_sha("a"),
            refs=refs,
        )

    def test_author_hidden_inside_fold_does_not_enable_author_column(self, mocker) -> None:
        """A second author only on folded commits leaves the author column off."""
        # Given a six-commit run where only a folded middle commit has another author
        names = "abcdef"
        lines = [
            self._line(n, (names[i + 1] if i + 1 < 6 else "z",), "Other" if n == "c" else "Nate")
            for i, n in enumerate(names)
        ]
        self._patch(mocker, lines)

        # When
        out = LogGraph().render()

        # Then
        assert any("more commits" in t.plain for t in out)
        assert not any("Other" in t.plain or "Nate" in t.plain for t in out)


class TestTrunk:
    """The in-memory first-parent walk from the default branch tip."""

    def _commits(self) -> list[CommitRecord]:
        return [_record("a", ("b",)), _record("b", ("c",)), _record("c", ())]

    def test_no_default_branch(self) -> None:
        """Without a default branch tip there is no trunk."""
        assert LogGraph._trunk(self._commits(), None) == frozenset()

    def test_tip_outside_window(self) -> None:
        """A default tip that is not in the window yields no trunk."""
        assert LogGraph._trunk(self._commits(), _sha("q")) == frozenset()

    def test_walks_first_parents(self) -> None:
        """The walk follows first parents from the tip until it leaves the window."""
        # Given a tip at b, so a is excluded
        assert LogGraph._trunk(self._commits(), _sha("b")) == frozenset({_sha("b"), _sha("c")})

    def test_falls_back_to_remote_tracking_ref(self, mocker) -> None:
        """When the local default ref is missing, the remote-tracking ref supplies the tip."""

        # Given git resolving only origin/main
        def fake(*args: str, **_: object) -> CompletedCommand:
            if args[0] == "remote":
                return _git_result("origin")
            if args[-1] == "origin/main^{commit}":
                return _git_result(_sha("b"))
            return _git_result("", ok=False)

        mocker.patch("gx.lib.log_graph.git", side_effect=fake)

        # When / Then
        assert LogGraph._resolve_default("main") == ("origin/main", _sha("b"))

    def test_local_ref_wins_over_remote(self, mocker) -> None:
        """A resolvable local default branch is used as is."""
        # Given
        mocker.patch("gx.lib.log_graph.git", return_value=_git_result(_sha("b")))

        # When / Then
        assert LogGraph._resolve_default("main") == ("main", _sha("b"))

    def test_unresolvable_everywhere(self, mocker) -> None:
        """With neither a local nor a remote ref the default resolves to nothing."""
        # Given
        mocker.patch("gx.lib.log_graph.git", return_value=_git_result("", ok=False))

        # When / Then
        assert LogGraph._resolve_default("main") is None
        assert LogGraph._resolve_default(None) is None


class TestJoinBlocks:
    """Ordering the main and unrelated-history query results."""

    def test_unrelated_block_goes_after_main(self) -> None:
        """A block with no parent in the main block follows it."""
        # Given
        main = [_record("a", ("b",)), _record("b")]
        extra = [_record("x", ("y",)), _record("y")]

        # When
        joined = join_blocks(main, extra)

        # Then
        assert [c.sha for c in joined] == [_sha(n) for n in "abxy"]

    def test_block_descending_from_main_goes_first(self) -> None:
        """A block whose commit has a parent in the main block precedes it."""
        # Given
        main = [_record("a", ("b",)), _record("b")]
        extra = [_record("x", ("a",))]

        # When
        joined = join_blocks(main, extra)

        # Then
        assert [c.sha for c in joined] == [_sha(n) for n in "xab"]


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        ("refs/heads/gh-pages", "refs/heads/gh-pages"),
        ("refs/heads/odd*[name]?", "refs/heads/odd\\*\\[name]\\?"),
    ],
)
def test_escape_glob(ref: str, expected: str) -> None:
    """Glob metacharacters in ref names are escaped for --exclude."""
    assert _escape_glob(ref) == expected


def _legend_context(
    names: list[str], *, current: str | None = None, tracked: frozenset[str] = frozenset()
) -> LogContext:
    """Build a context with `main` as default and the given branches in a fixed color.

    Branches named in `tracked` have an upstream.
    """
    branches = {
        "main": BranchState(name="main", color="", is_current=current == "main", is_default=True),
        **{
            n: BranchState(
                name=n,
                color="cyan",
                is_current=n == current,
                is_default=False,
                upstream=f"origin/{n}" if n in tracked else None,
                has_remote_upstream=n in tracked,
            )
            for n in names
        },
    }
    return LogContext(
        default="main",
        current=current,
        branches=branches,
        owners={},
        head_reachable=frozenset(),
        parents={},
    )


class TestRenderLegend:
    """Branch color legend under the graph."""

    def test_legend_order_and_marks(self) -> None:
        """Default first, then current, then the rest by name, with styled marks."""
        # Given a default, a current branch, and one more branch
        context = _legend_context(["feat-a", "feat-b"], current="feat-b")

        # When rendered
        legend = render_legend(context, UNICODE, 80)

        # Then the order, bullets, and current mark match
        assert legend is not None
        assert legend.plain == "● main  ● feat-b (current)  ● feat-a"
        styles = {legend.plain[s.start : s.end]: str(s.style) for s in legend.spans}
        assert styles["(current)"] == "dim"
        assert any(
            str(s.style) == "cyan" and legend.plain[s.start : s.end] == "●" for s in legend.spans
        )

    @pytest.mark.parametrize("charset", [ASCII, UNICODE, BRANCH_SYMBOLS])
    def test_legend_bullet(self, charset) -> None:
        """ASCII uses `*`; every other charset uses a round bullet."""
        # Given a context with two branches
        context = _legend_context(["feat"])

        # When rendered
        legend = render_legend(context, charset, 80)

        # Then the bullet matches the charset
        assert legend is not None
        assert legend.plain.startswith("* main" if charset is ASCII else "● main")

    def test_no_legend_for_default_only(self) -> None:
        """No legend when the default is the only visible branch, or none is visible."""
        # Given a default-only context and an empty one
        only_default = _legend_context([])
        empty = LogContext(
            default=None,
            current=None,
            branches={},
            owners={},
            head_reachable=frozenset(),
            parents={},
        )

        # When rendered
        # Then neither has a legend
        assert render_legend(only_default, UNICODE, 80) is None
        assert render_legend(empty, UNICODE, 80) is None

    def test_legend_marks_local_branches(self) -> None:
        """Branches without an upstream are marked local when others have one."""
        context = _legend_context(["feat", "solo"], tracked=frozenset({"feat"}))
        legend = render_legend(context, UNICODE, None)
        assert legend is not None
        assert legend.plain == "● main  ● feat  ● solo local"

    def test_legend_local_mark_for_branch_tracking_a_local_branch(self) -> None:
        """An upstream that is itself a local branch does not count as a remote one."""
        context = _legend_context(["feat", "stacked"], tracked=frozenset({"feat"}))
        stacked = BranchState(
            name="stacked",
            color="cyan",
            is_current=False,
            is_default=False,
            upstream="feat",
            has_remote_upstream=False,
        )
        context = LogContext(
            default=context.default,
            current=context.current,
            branches={**context.branches, "stacked": stacked},
            owners={},
            head_reachable=frozenset(),
            parents={},
        )
        legend = render_legend(context, UNICODE, None)
        assert legend is not None
        assert legend.plain == "● main  ● feat  ● stacked local"

    def test_legend_local_mark_after_current_mark(self) -> None:
        """The local mark follows the current mark."""
        context = _legend_context(["feat", "solo"], current="solo", tracked=frozenset({"feat"}))
        legend = render_legend(context, UNICODE, None)
        assert legend is not None
        assert legend.plain == "● main  ● solo (current) local  ● feat"

    def test_legend_local_mark_needs_a_tracked_branch(self) -> None:
        """With no upstream anywhere, every branch is local and the mark says nothing."""
        legend = render_legend(_legend_context(["feat", "solo"]), UNICODE, None)
        assert legend is not None
        assert "local" not in legend.plain

    def test_legend_truncates(self) -> None:
        """A narrow width drops entries and ends with a `+N more` tail."""
        # Given eight long branch names
        names = [f"feature-branch-number-{i}" for i in range(8)]
        context = _legend_context(names)

        # When rendered at width 40
        legend = render_legend(context, UNICODE, 40)

        # Then it fits, ends with the tail, and the counts add up
        assert legend is not None
        assert legend.cell_len <= 40
        match = re.search(r"\+(\d+) more$", legend.plain)
        assert match is not None
        shown = legend.plain.count("●")
        assert shown + int(match.group(1)) == 9

    def test_legend_keeps_default_when_nothing_fits(self) -> None:
        """The default branch shows even when the width cannot hold it."""
        # Given a width smaller than the first entry
        context = _legend_context(["feature-branch-number-1", "feature-branch-number-2"])

        # When rendered
        legend = render_legend(context, UNICODE, 4)

        # Then only the default branch shows, without a tail that would not fit
        assert legend is not None
        assert legend.plain == "● main"

    def test_legend_shows_all_entries_when_they_fit(self) -> None:
        """No entry collapses into the tail when every entry fits the width."""
        # Given a short last entry that fits where a `+1 more` tail would not
        context = _legend_context(["feature-branch-number-1", "x"])
        full = render_legend(context, UNICODE, None)
        assert full is not None

        # When rendered at exactly the full legend width
        legend = render_legend(context, UNICODE, full.cell_len)

        # Then every entry shows
        assert legend is not None
        assert legend.plain == full.plain

    def test_legend_tail_needs_room(self) -> None:
        """The `+N more` tail appears only when it fits after the first entry."""
        # Given a width that holds the default and the tail
        context = _legend_context(["feature-branch-number-1", "feature-branch-number-2"])

        # When rendered
        legend = render_legend(context, UNICODE, 20)

        # Then the default is followed by the tail
        assert legend is not None
        assert legend.plain == "● main  +2 more"
