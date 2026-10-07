"""Tests for LogGraph parsing, folding, and rendering."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import typer
from nclutils.sh import CompletedCommand

from gx.lib.config import GxConfig
from gx.lib.graph_layout import (
    ASCII,
    UNICODE,
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
    render_line,
    short_age,
)

if TYPE_CHECKING:
    from rich.text import Text

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
        assert out[1] == LaneFold(lane=0, lanes=frozenset({0}), hidden=4)
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
        assert folds == [LaneFold(lane=1, lanes=frozenset({1}), hidden=4)]
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


def _style_at(text: Text, index: int) -> str:
    """Return the style of the innermost span covering a plain-text offset."""
    covering = [str(s.style) for s in text.spans if s.start <= index < s.end]
    return covering[-1] if covering else ""


def _tip(name: str, refs: str = "", *, parents: tuple[str, ...] = ("z",)) -> GraphEntry:
    return _entries([_record(name, parents, refs)])[0]


class TestRenderLine:
    """Styling of laid-out graph lines."""

    def test_commit_line_layout(self) -> None:
        """An entry draws graph, SHA, subject, and age."""
        # Given / When
        text = render_line(_tip("a"), UNICODE, now=NOW + 3 * 86400)

        # Then
        assert text.plain == "● aaaaaaa commit a  3d"

    def test_ascii_charset(self) -> None:
        """The ascii charset draws an asterisk node."""
        # Given / When
        text = render_line(_tip("a"), ASCII, now=NOW)

        # Then
        assert text.plain.startswith("* aaaaaaa")

    def test_commit_line_with_refs_and_author(self) -> None:
        """Refs sit in parentheses before the subject and the author follows the age."""
        # Given / When
        text = render_line(_tip("a", "tag: v1"), UNICODE, now=NOW, show_author=True)

        # Then
        assert text.plain == "● aaaaaaa (tag: v1) commit a  0s Nate"

    @pytest.mark.parametrize("refs", ["HEAD -> main", "HEAD"])
    def test_head_commit_uses_head_node(self, refs: str) -> None:
        """A HEAD ref draws the HEAD node."""
        # Given / When
        text = render_line(_tip("a", refs), UNICODE, now=NOW)

        # Then
        assert text.plain.startswith("◉ ")

    def test_merge_commit_uses_merge_node(self) -> None:
        """A merge commit draws the merge node."""
        # Given
        entries = _entries([_record("a", ("b", "c")), _record("b", ("z",)), _record("c", ("z",))])

        # When
        text = render_line(entries[0], UNICODE, now=NOW)

        # Then
        assert text.plain.startswith("◎")

    def test_graph_cells_are_dim_and_node_is_not(self) -> None:
        """Line glyphs are dim while the node keeps the default style."""
        # Given a commit with a lane continuing beside it
        entries = _entries([_record("a", ("c",)), _record("b", ("c",)), _record("c")])
        text = render_line(entries[1], UNICODE, now=NOW)

        # When
        styles = {text.plain[s.start : s.end]: str(s.style) for s in text.spans}

        # Then
        assert styles["│ "] == "dim"
        assert "●" not in "".join(k for k, v in styles.items() if v == "dim")
        assert text.plain[2] == "●"

    def test_fold_marker_is_dim(self) -> None:
        """The fold glyph is dim along with the rest of the fold line."""
        # Given / When
        text = render_line(LaneFold(lane=0, lanes=frozenset({0}), hidden=3), UNICODE, now=NOW)

        # Then
        assert text.plain.startswith("┊")
        assert _style_at(text, 0) == "dim"

    def test_fade_marker_is_dim(self) -> None:
        """The fade glyph is dim."""
        # Given a graph whose last commit leaves a lane open
        text = _graph_text(fade_cells(_tip("a").row) or [], UNICODE)

        # Then
        assert text.plain == "╎"
        assert _style_at(text, 0) == "dim"

    def test_metadata_dropped_before_subject_cut(self) -> None:
        """The age is dropped before the subject is cut."""
        # Given / When
        text = render_line(_tip("a"), UNICODE, now=NOW, width=len("● aaaaaaa commit a"))

        # Then
        assert text.plain == "● aaaaaaa commit a"

    def test_fold_line(self) -> None:
        """A fold draws the fold marker in its lane and keeps other lanes."""
        # Given / When
        text = render_line(LaneFold(lane=1, lanes=frozenset({0, 1}), hidden=5), UNICODE, now=NOW)

        # Then
        assert text.plain == "│ ┊ … 5 more commits"
        assert text.spans[-1].style == "dim italic"

    def test_fold_line_singular(self) -> None:
        """One hidden commit uses the singular noun."""
        # Given / When
        text = render_line(LaneFold(lane=0, lanes=frozenset({0}), hidden=1), UNICODE, now=NOW)

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
        lines = [render_line(e, UNICODE, now=NOW, width=20) for e in entries]

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
        mocker.patch("gx.lib.log_graph.has_commits", return_value=True)
        mocker.patch("gx.lib.log_graph.find_default_branch", return_value=default)
        mocker.patch.object(LogGraph, "_fork_points", return_value=frozenset())
        mocker.patch.object(LogGraph, "_window_queries", return_value=[[]])
        mocker.patch("gx.lib.log_graph.config", GxConfig(graph_style="unicode"))
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
