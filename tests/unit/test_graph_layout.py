"""Tests for the commit graph lane layout."""

from __future__ import annotations

import random

import pytest

from gx.lib.graph_layout import (
    ASCII,
    BRANCH_SYMBOLS,
    UNICODE,
    Cell,
    Charset,
    GraphOrderError,
    LayoutCommit,
    NodeKind,
    Pipe,
    PipeKind,
    Row,
    charset_for,
    draw,
    fade_cells,
    fold_cells,
    layout,
    row_cells,
)

DAG_SIZE = 200
DAG_WINDOW = 12


def _c(sha: str, *parents: str) -> LayoutCommit:
    return LayoutCommit(sha=sha, parents=tuple(parents))


def _lanes(rows: list[Row]) -> list[int]:
    return [row.lane for row in rows]


def _random_dag(seed: int) -> list[LayoutCommit]:
    """Build a topologically ordered random DAG, newest commit first."""
    rng = random.Random(seed)
    commits: list[LayoutCommit] = []
    for i in range(DAG_SIZE):
        candidates = list(range(i + 1, min(i + DAG_WINDOW, DAG_SIZE)))
        roll = rng.random()
        count = 1 if roll < 0.85 else 2 if roll < 0.97 else 3
        count = min(count, len(candidates))
        parents = rng.sample(candidates, count)
        commits.append(_c(str(i), *(str(p) for p in parents)))
    return commits


def test_linear_chain_stays_in_lane_zero():
    """Verify a linear history occupies lane 0 and roots emit no STARTS pipe."""
    # Given
    commits = [_c("a", "b"), _c("b", "c"), _c("c")]

    # When
    rows = layout(commits)

    # Then
    assert _lanes(rows) == [0, 0, 0]
    assert rows[2].pipes == (Pipe("b", "c", 0, 0, PipeKind.TERMINATES),)


def test_feature_tip_avoids_trunk_lane():
    """Verify a feature branch stays out of lane 0 when a trunk is given."""
    # Given
    commits = [_c("f2", "f1"), _c("f1", "m2"), _c("m3", "m2"), _c("m2", "m1"), _c("m1")]

    # When
    rows = layout(commits, trunk=frozenset({"m3", "m2", "m1"}))

    # Then
    assert _lanes(rows) == [1, 1, 0, 0, 0]


def test_unrelated_history_takes_first_free_non_trunk_lane():
    """Verify an unrelated commit takes the lowest free lane at or above 1."""
    # Given
    commits = [_c("m1", "m2"), _c("o1"), _c("m2")]

    # When
    rows = layout(commits, trunk=frozenset({"m1", "m2"}))

    # Then
    assert _lanes(rows) == [0, 1, 0]


def test_parents_deduplicated_and_self_parent_dropped():
    """Verify duplicate and self parents are removed before layout."""
    # Given
    commits = [_c("a", "b", "b", "a"), _c("b")]

    # When
    rows = layout(commits)

    # Then
    assert rows[0].is_merge is False
    assert [p.to_sha for p in rows[0].pipes] == ["b"]


def test_parent_before_child_raises():
    """Verify a parent listed before its child is rejected."""
    # Given
    commits = [_c("b"), _c("a", "b")]

    # When / Then
    with pytest.raises(GraphOrderError):
        layout(commits)


def test_same_sha_twice_raises():
    """Verify a sha listed twice is rejected."""
    # Given
    commits = [_c("a", "b"), _c("b"), _c("b")]

    # When / Then
    with pytest.raises(GraphOrderError):
        layout(commits)


def test_main_merged_into_feature():
    """Verify a trunk parent of a feature merge never routes through lane 0."""
    # Given
    commits = [_c("F", "f1", "m2"), _c("f1", "m1"), _c("m2", "m1"), _c("m1")]

    # When
    rows = layout(commits, trunk=frozenset({"m2", "m1"}))

    # Then
    assert _lanes(rows) == [1, 1, 0, 0]
    assert all(p.to_lane != 0 for p in rows[0].pipes)
    assert all(p.to_lane != 0 for p in rows[1].pipes if p.kind is not PipeKind.TERMINATES)


@pytest.mark.parametrize("seed", range(20))
def test_width_stays_bounded_on_random_dag(seed: int):
    """Verify lane compaction keeps the graph no wider than its peak open pipes."""
    # Given
    commits = _random_dag(seed)

    # When
    rows = layout(commits)

    # Then
    peak = max(sum(1 for p in r.pipes if p.kind is not PipeKind.TERMINATES) for r in rows)
    width = max(p.to_lane for r in rows for p in r.pipes) + 1
    assert width <= peak + 1


def _parse(spec: str) -> list[LayoutCommit]:
    """Parse `1:2  2:3,4  3:` into commits."""
    commits = []
    for token in spec.split():
        sha, _, parents = token.partition(":")
        commits.append(_c(sha, *(p for p in parents.split(",") if p)))
    return commits


def _render(
    commits: list[LayoutCommit], trunk: frozenset[str] = frozenset(), charset: Charset = UNICODE
) -> str:
    lines = []
    width = max(len(c.sha) for c in commits)
    for row in layout(commits, trunk):
        node = NodeKind.MERGE if row.is_merge else NodeKind.COMMIT
        sha = row.sha.ljust(width)
        lines.append(f"{sha} {draw(row_cells(row, node), charset)}".rstrip())
    return "\n".join(lines)


FIXTURES = [
    pytest.param(
        "1:2  2:3,4  4:3,5  3:5  5:6  6:7",
        frozenset(),
        "1 ●\n2 ◎─╮\n4 │ ◎─╮\n3 ●─╯ │\n5 ●───╯\n6 ●",
        id="room-to-move-left",
    ),
    pytest.param(
        "1:2  2:3,4  4:3,5  Z:Y  3:5  5:6  6:7",
        frozenset(),
        "1 ●\n2 ◎─╮\n4 │ ◎─╮\nZ │ │ │ ●\n3 ●─╯ │ │\n5 ●───╯ │\n6 ● ╭───╯",
        id="new-commit",
    ),
    pytest.param(
        "1:2  2:  A:B  B:",
        frozenset(),
        "1 ●\n2 ●\nA ●\nB ●",
        id="root-then-unrelated",
    ),
    pytest.param(
        "1:2,A  2:3  A:  3:",
        frozenset(),
        "1 ◎─╮\n2 ● │\nA │ ●\n3 ●",
        id="merge-of-unrelated",
    ),
    pytest.param(
        "1:2  2:3,4  3:5,4  5:7,8  4:7  7:11",
        frozenset(),
        "1 ●\n2 ◎─╮\n3 ◎─│─╮\n5 ◎─│─│─╮\n4 │ ●─╯ │\n7 ●─╯ ╭─╯",
        id="continues-a",
    ),
    pytest.param(
        "1:2  2:3,4  3:5,4  5:7,8  7:4,A  4:B  B:C",
        frozenset(),
        "1 ●\n2 ◎─╮\n3 ◎─│─╮\n5 ◎─│─│─╮\n7 ◎─│─│─│─╮\n4 ●─┴─╯ │ │\nB ● ╭───╯ │",
        id="continues-b",
    ),
    pytest.param(
        "1:2,3  3:2  2:4,5  4:6,7  6:8",
        frozenset(),
        "1 ◎─╮\n3 │ ●\n2 ◎─│\n4 ◎─│─╮\n6 ● │ │",
        id="continues-c",
    ),
    pytest.param(
        "1:2,3,4,5  4:2  2:A  A:6,B  B:C",
        frozenset(),
        "1 ◎─┬─┬─╮\n4 │ │ ● │\n2 ●─│─╯ │\nA ◎─│─╮ │\nB │ │ ● │",
        id="octopus-fills-gap",
    ),
    pytest.param(
        "1:2  2:3,4  3:5,4  5:7,8  7:4,A  4:B  B:C  C:D",
        frozenset(),
        "1 ●\n2 ◎─╮\n3 ◎─│─╮\n5 ◎─│─│─╮\n7 ◎─│─│─│─╮\n4 ●─┴─╯ │ │\nB ● ╭───╯ │\nC ● │ ╭───╯",
        id="continues-d",
    ),
    pytest.param(
        "f2:f1  f1:m2  m3:m2  m2:m1  m1:",
        frozenset({"m3", "m2", "m1"}),
        "f2   ●\nf1   ●\nm3 ● │\nm2 ●─╯\nm1 ●",
        id="feature-off-trunk",
    ),
    pytest.param(
        "M:m1,f1  f1:m1  m1:",
        frozenset({"M", "m1"}),
        "M  ◎─╮\nf1 │ ●\nm1 ●─╯",
        id="feature-merged-into-trunk",
    ),
    pytest.param(
        "F:f1,m2  f1:m1  m2:m1  m1:",
        frozenset({"m2", "m1"}),
        "F    ◎─╮\nf1   ● │\nm2 ●─│─╯\nm1 ●─╯",
        id="main-merged-into-feature",
    ),
    pytest.param(
        "1:2,3,4  4:2 3:2  2:",
        frozenset(),
        "1 ◎─┬─╮\n4 │ │ ●\n3 │ ● │\n2 ●─┴─╯",
        id="octopus-3-parents",
    ),
    pytest.param(
        "0:3  1:2,3,4  4:2 3:2  2:",
        frozenset(),
        "0 ●\n1 │ ◎─┬─╮\n4 │ │ │ ●\n3 ●─│─╯ │\n2 ●─┴───╯",
        id="octopus-3-parents-lane-in-use",
    ),
    pytest.param(
        "1:2,3,4,5  5:2 4:2 3:2  2:",
        frozenset(),
        "1 ◎─┬─┬─╮\n5 │ │ │ ●\n4 │ │ ● │\n3 │ ● │ │\n2 ●─┴─┴─╯",
        id="octopus-4-parents",
    ),
    pytest.param(
        "0:3  1:2,3,4,5  5:2 4:2 3:2  2:",
        frozenset(),
        "0 ●\n1 │ ◎─┬─┬─╮\n5 │ │ │ │ ●\n4 │ │ │ ● │\n3 ●─│─╯ │ │\n2 ●─┴───┴─╯",
        id="octopus-4-parents-lane-in-use",
    ),
    pytest.param(
        "1:2,3,4,5,6  6:2 5:2 4:2 3:2  2:",
        frozenset(),
        "1 ◎─┬─┬─┬─╮\n6 │ │ │ │ ●\n5 │ │ │ ● │\n4 │ │ ● │ │\n3 │ ● │ │ │\n2 ●─┴─┴─┴─╯",
        id="octopus-5-parents",
    ),
    pytest.param(
        "0:3  1:2,3,4,5,6  6:2 5:2 4:2 3:2  2:",
        frozenset(),
        "0 ●\n1 │ ◎─┬─┬─┬─╮\n6 │ │ │ │ │ ●\n5 │ │ │ │ ● │\n4 │ │ │ ● │ │\n3 ●─│─╯ │ │ │\n2 ●─┴───┴─┴─╯",
        id="octopus-5-parents-lane-in-use",
    ),
    pytest.param(
        "1:2,3,4,5,6,7  7:2 6:2 5:2 4:2 3:2  2:",
        frozenset(),
        "1 ◎─┬─┬─┬─┬─╮\n7 │ │ │ │ │ ●\n6 │ │ │ │ ● │\n5 │ │ │ ● │ │\n4 │ │ ● │ │ │\n3 │ ● │ │ │ │\n2 ●─┴─┴─┴─┴─╯",
        id="octopus-6-parents",
    ),
    pytest.param(
        "0:3  1:2,3,4,5,6,7  7:2 6:2 5:2 4:2 3:2  2:",
        frozenset(),
        "0 ●\n1 │ ◎─┬─┬─┬─┬─╮\n7 │ │ │ │ │ │ ●\n6 │ │ │ │ │ ● │\n5 │ │ │ │ ● │ │\n4 │ │ │ ● │ │ │\n3 ●─│─╯ │ │ │ │\n2 ●─┴───┴─┴─┴─╯",
        id="octopus-6-parents-lane-in-use",
    ),
    pytest.param(
        "a:r  b:r  c:r  d:r  r:",
        frozenset(),
        "a ●\nb │ ●\nc │ │ ●\nd │ │ │ ●\nr ●─┴─┴─╯",
        id="parallel-siblings",
    ),
    pytest.param(
        "a:r  b:r  c:r  r:",
        frozenset({"r"}),
        "a   ●\nb   │ ●\nc   │ │ ●\nr ●─┴─┴─╯",
        id="parallel-siblings-trunk",
    ),
    pytest.param(
        "a:x  b:y  c:z  y:  n:m  x:z  m:z  z:",
        frozenset(),
        "a ●\nb │ ●\nc │ │ ●\ny │ ● │\nn │ ● │\nx ● │ │\nm │ ● │\nz ●─┴─╯",
        id="branch-between-lanes",
    ),
    pytest.param(
        "a:x  b:y  c:z  y:  x:  z:",
        frozenset(),
        "a ●\nb │ ●\nc │ │ ●\ny │ ● │\nx ● ╭─╯\nz   ●",
        id="lanes-collapse-left",
    ),
    pytest.param(
        "a:s  m:p,s  p:r  s:r  r:",
        frozenset(),
        "a ●\nm │ ◎─╮\np │ ● │\ns ●─│─╯\nr ●─╯",
        id="merge-side-left-of-node",
    ),
    pytest.param(
        "f:t2  m:t2,s  s:t1  t2:t1  t1:",
        frozenset({"m", "t2", "t1"}),
        "f    ●\nm  ◎─│─╮\ns  │ │ ●\nt2 ●─╯ │\nt1 ●───╯",
        id="merge-side-left-of-trunk-node",
    ),
    pytest.param(
        "a:b,c  b:d  c:d  d:",
        frozenset(),
        "a ◎─╮\nb ● │\nc │ ●\nd ●─╯",
        id="diamond",
    ),
    pytest.param(
        "a:b,c,e  b:d  c:d  e:d  d:",
        frozenset(),
        "a ◎─┬─╮\nb ● │ │\nc │ ● │\ne │ │ ●\nd ●─┴─╯",
        id="diamond-three-lanes",
    ),
    pytest.param(
        "a:b,b  b:c,c,b  c:",
        frozenset(),
        "a ●\nb ●\nc ●",
        id="duplicate-parents",
    ),
]


@pytest.mark.parametrize(("spec", "trunk", "expected"), FIXTURES)
def test_lazygit_fixture(spec: str, trunk: frozenset[str], expected: str):
    """Verify rendered rows match the lazygit graph fixtures."""
    # Given
    commits = _parse(spec)

    # When
    rendered = _render(commits, trunk)

    # Then
    assert rendered == expected


def test_ascii_charset_renders_same_shape():
    """Verify the ASCII charset draws the same shape with ASCII glyphs."""
    # Given
    commits = _parse("1:2  2:3,4  4:3,5  3:5  5:6  6:7")

    # When
    rendered = _render(commits, charset=ASCII)

    # Then
    assert rendered == "1 *\n2 M-.\n4 | M-.\n3 *-' |\n5 *---'\n6 *"


def test_fade_row_marks_open_lanes():
    """Verify the fade row draws a fade node on lanes that continue past the window."""
    # Given
    rows = layout([_c("a", "b")])

    # When
    cells = fade_cells(rows[-1])

    # Then
    assert cells is not None
    assert draw(cells, UNICODE) == "╎"


def test_fade_row_absent_when_all_lanes_closed():
    """Verify no fade row is produced when the last row only terminates pipes."""
    # Given
    rows = layout([_c("a", "b"), _c("b")])

    # When
    cells = fade_cells(rows[-1])

    # Then
    assert cells is None


def test_fold_cells():
    """Verify the fold row keeps open lanes and puts the marker on the given lane."""
    # Given
    lanes = frozenset({0, 1})

    # When
    drawn = draw(fold_cells(lanes, 1), UNICODE)

    # Then
    assert drawn == "│ ┊"


def test_fold_cells_record_lane_pipes():
    """Verify each fold cell records the open pipe that owns its lane."""
    # Given pipes in lanes 0 and 1
    p0 = Pipe("a", "x", 0, 0, PipeKind.CONTINUES)
    p1 = Pipe("b", "y", 1, 1, PipeKind.CONTINUES)

    # When
    cells = fold_cells(frozenset({0, 1}), 1, [p0, p1])

    # Then
    assert cells[0].vertical == p0
    assert cells[1].vertical == p1


def test_fold_cells_skip_terminating_pipes():
    """Verify a terminating pipe is never recorded on a fold cell."""
    # Given a terminating pipe into lane 0
    pipe = Pipe("a", "x", 0, 0, PipeKind.TERMINATES)

    # When
    cells = fold_cells(frozenset({0}), 0, [pipe])

    # Then
    assert cells[0].vertical is None


def test_fold_cells_lane_without_pipe_has_no_vertical():
    """Verify a fold lane that no pipe targets records no vertical."""
    # Given a pipe into lane 0 only
    pipe = Pipe("a", "x", 0, 0, PipeKind.CONTINUES)

    # When a fold spans lanes 0 and 1
    cells = fold_cells(frozenset({0, 1}), 1, [pipe])

    # Then lane 1 has nothing to record
    assert cells[0].vertical == pipe
    assert cells[1].vertical is None


def test_fold_cells_last_pipe_wins_when_lanes_collide():
    """Verify the later pipe owns a lane that several pipes target, as row_cells does."""
    # Given two pipes into lane 0
    first = Pipe("a", "x", 0, 0, PipeKind.CONTINUES)
    second = Pipe("b", "x", 1, 0, PipeKind.CONTINUES)

    # When
    cells = fold_cells(frozenset({0}), 0, [first, second])

    # Then
    assert cells[0].vertical == second


def test_fold_cells_without_pipes_unchanged():
    """Verify omitting pipes leaves vertical unset and drawing unchanged."""
    # When
    cells = fold_cells(frozenset({0, 1}), 1)

    # Then
    assert all(c.vertical is None for c in cells)
    assert draw(cells, UNICODE) == "│ ┊"


def test_fade_cells_record_open_pipe():
    """Verify the fade cell records the open pipe in its lane."""
    # Given
    rows = layout([_c("a", "b")])

    # When
    cells = fade_cells(rows[-1])

    # Then
    assert cells is not None
    assert cells[0].vertical == Pipe("a", "b", 0, 0, PipeKind.STARTS)


def test_head_node():
    """Verify a HEAD node draws as a distinct glyph in each charset."""
    # Given
    row = layout([_c("a", "b")])[0]

    # When
    cells = row_cells(row, NodeKind.HEAD)

    # Then
    assert draw(cells, UNICODE) == "◉"
    assert draw(cells, ASCII) == "@"


def test_charsets_are_hashable():
    """Charsets work as set members and dict keys."""
    # When
    charsets = {UNICODE, ASCII, BRANCH_SYMBOLS, UNICODE}

    # Then
    assert len(charsets) == 3


@pytest.mark.parametrize("charset", [UNICODE, ASCII, BRANCH_SYMBOLS], ids=lambda c: c.name)
def test_charsets_are_total(charset: Charset):
    """Verify every glyph table is complete and every lane is two columns wide."""
    # Given
    keys = [
        (u, d, left, r)
        for u in (False, True)
        for d in (False, True)
        for left in (False, True)
        for r in (False, True)
    ]

    # When / Then
    for key in keys:
        assert len(charset.lines[key]) == 2
    for kind in NodeKind:
        assert len(charset.nodes[kind]) == 1
    for shape in charset.node_shapes.values():
        assert len(shape) == 1
    assert len(charset.horizontal) == 1


@pytest.mark.parametrize("seed", range(20))
def test_branch_symbols_cover_produced_cells(seed: int):
    """Verify every glyph the layout produces uses only the original kitty range or spaces."""
    # Given
    rows = layout(_random_dag(seed))

    # When
    produced = {
        (c.up, c.down, c.left, c.right)
        for row in rows
        for c in row_cells(row, NodeKind.COMMIT)
        if c.node is None
    }

    # Then
    for key in produced:
        for char in BRANCH_SYMBOLS.lines[key]:
            assert char == " " or 0xF5D0 <= ord(char) <= 0xF5FB, key


@pytest.mark.parametrize(
    ("style", "encoding", "expected"),
    [
        ("auto", "utf-8", UNICODE),
        ("auto", "UTF-8", UNICODE),
        ("auto", "UTF_8", UNICODE),
        ("auto", "utf8", UNICODE),
        ("unicode", "ascii", UNICODE),
        ("branch-symbols", "utf-8", BRANCH_SYMBOLS),
        ("ascii", "utf-8", ASCII),
    ],
)
def test_charset_for(style: str, encoding: str, expected: Charset) -> None:
    """Verify the style picks the charset, with explicit styles beating the encoding."""
    # When resolving the charset
    result = charset_for(style, encoding)

    # Then the expected charset is returned
    assert result is expected


def test_auto_falls_back_to_ascii() -> None:
    """Verify auto uses ASCII for non-UTF encodings."""
    # Then
    assert charset_for("auto", "ascii") is ASCII
    assert charset_for("auto", "cp1252") is ASCII


def _trunk_dag(seed: int) -> tuple[list[LayoutCommit], frozenset[str], int]:
    """Build a random DAG plus the first-parent trunk walked from a random early tip."""
    commits = _random_dag(seed)
    by_sha = {c.sha: c for c in commits}
    tip = random.Random(seed).randrange(20)
    trunk: set[str] = set()
    sha: str | None = str(tip)
    while sha in by_sha:
        trunk.add(sha)
        parents = by_sha[sha].parents
        sha = parents[0] if parents else None
    return commits, frozenset(trunk), tip


@pytest.mark.parametrize("seed", range(40))
def test_trunk_invariants_on_random_dag(seed: int):
    """Verify lane 0 is reserved for the trunk and width stays bounded around it."""
    # Given
    commits, trunk, tip = _trunk_dag(seed)

    # When
    rows = layout(commits, trunk)

    # Then
    tip_seen = False
    for row in rows:
        tip_seen = tip_seen or row.sha == str(tip)
        assert (row.sha in trunk) == (row.lane == 0)
        for pipe in row.pipes:
            if pipe.kind is not PipeKind.TERMINATES and pipe.to_lane == 0:
                assert pipe.to_sha in trunk
            if not tip_seen:
                assert 0 not in (pipe.from_lane, pipe.to_lane)
    peak = max(sum(1 for p in r.pipes if p.kind is not PipeKind.TERMINATES) for r in rows)
    width = max(max(p.to_lane for p in r.pipes) for r in rows if r.pipes) + 1
    assert width <= peak + 2


def _pipes(row: Row) -> set[tuple[str, str, int, int, PipeKind]]:
    return {(p.from_sha, p.to_sha, p.from_lane, p.to_lane, p.kind) for p in row.pipes}


def test_extra_parents_start_on_lowest_free_lanes():
    """Verify extra merge parents skip lanes held by continuing pipes."""
    # Given a merge whose left neighbor pipe is open on lane 0
    commits = _parse("0:3  1:2,3,4  4:2  3:2  2:")

    # When
    rows = layout(commits)

    # Then the first parent stays on the node's lane and the rest take the next free lanes
    assert {p for p in _pipes(rows[1]) if p[4] is PipeKind.STARTS} == {
        ("1", "2", 1, 1, PipeKind.STARTS),
        ("1", "3", 1, 2, PipeKind.STARTS),
        ("1", "4", 1, 3, PipeKind.STARTS),
    }


def test_extra_parents_never_start_on_trunk_lane():
    """Verify extra merge parents start at lane 1 or higher when a trunk exists."""
    # Given a trunk merge with two side parents
    commits = _parse("m:t,a,b  a:t  b:t  t:")

    # When
    rows = layout(commits, frozenset({"m", "t"}))

    # Then
    starts = {(p.to_sha, p.to_lane) for p in rows[0].pipes if p.kind is PipeKind.STARTS}
    assert starts == {("t", 0), ("a", 1), ("b", 2)}


def test_right_pipe_slides_left_into_freed_lane():
    """Verify a pipe right of the node moves left into a lane freed by a root commit."""
    # Given lanes 0, 1, 2 open and the middle one ending at a root
    commits = _parse("a:x  b:y  c:z  y:  x:  z:")

    # When
    rows = layout(commits)

    # Then the node at lane 0 pulls the lane 2 pipe over to lane 1
    assert ("c", "z", 2, 1, PipeKind.CONTINUES) in _pipes(rows[4])


def test_left_pipe_moves_left_past_a_freed_lane():
    """Verify a non-trunk pipe left of the node moves left when a lane below it is free."""
    # Given lanes 0 to 3 open, lane 1 ended, and a node on lane 3
    commits = _parse("a:x  b:y  c:z  d:w  y:  w:  x:  z:")

    # When
    rows = layout(commits)

    # Then the lane 2 pipe continues on lane 1 while lane 0 stays put
    pipes = _pipes(rows[5])
    assert rows[5].lane == 3
    assert ("c", "z", 2, 1, PipeKind.CONTINUES) in pipes
    assert ("a", "x", 0, 0, PipeKind.CONTINUES) in pipes


@pytest.mark.parametrize(
    ("kind", "up", "down", "expected"),
    [
        (NodeKind.COMMIT, True, True, "\uf5fb"),
        (NodeKind.COMMIT, False, True, "\uf5f7"),
        (NodeKind.COMMIT, True, False, "\uf5f9"),
        (NodeKind.COMMIT, False, False, "\uf5ef"),
        (NodeKind.MERGE, True, True, "\uf5fa"),
        (NodeKind.MERGE, False, True, "\uf5f6"),
        (NodeKind.MERGE, True, False, "\uf5f8"),
        (NodeKind.MERGE, False, False, "\uf5ee"),
        (NodeKind.HEAD, True, True, "\uf5fa"),
        (NodeKind.HEAD, False, True, "\uf5f6"),
        (NodeKind.HEAD, True, False, "\uf5f8"),
        (NodeKind.HEAD, False, False, "\uf5ee"),
    ],
)
def test_branch_symbols_node_shapes(kind: NodeKind, up: bool, down: bool, expected: str):
    """Verify commit, merge and head nodes pick a shape from their vertical neighbors."""
    # When
    glyph = BRANCH_SYMBOLS.glyph(Cell(up=up, down=down, node=kind))

    # Then
    assert glyph == expected + " "


@pytest.mark.parametrize("kind", [NodeKind.FOLD, NodeKind.FADE])
@pytest.mark.parametrize(("up", "down"), [(True, True), (False, False), (True, False)])
def test_branch_symbols_fold_and_fade_use_the_fill_glyph(kind: NodeKind, up: bool, down: bool):
    """Verify fold and fade nodes ignore their neighbors and draw the fill glyph."""
    # When
    glyph = BRANCH_SYMBOLS.glyph(Cell(up=up, down=down, node=kind))

    # Then
    assert glyph == "\uf5d4 "


def test_ascii_fade_draws_colon():
    """Verify the ASCII fade node is a colon."""
    # When / Then
    assert ASCII.glyph(Cell(node=NodeKind.FADE)) == ": "


@pytest.mark.parametrize(
    ("charset", "expected"),
    [(UNICODE, "●─"), (ASCII, "*-"), (BRANCH_SYMBOLS, "\uf5ef\uf5d0")],
    ids=lambda v: v.name if isinstance(v, Charset) else None,
)
def test_node_with_right_neighbor_adds_horizontal(charset: Charset, expected: str):
    """Verify a node whose row continues right draws the horizontal next to it."""
    # When
    glyph = charset.glyph(Cell(node=NodeKind.COMMIT, right=True))

    # Then
    assert glyph == expected
