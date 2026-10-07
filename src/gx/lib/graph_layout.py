"""Lane layout and glyph drawing for the commit graph.

Layout is a port of lazygit's `getNextPipes`: each row is derived from the previous
row's pipes. When a trunk is given, lane 0 is reserved for trunk commits so other
branches never displace it.

Drawing has two layers on top. `row_cells`, `fold_cells` and `fade_cells` turn rows into
per-lane `Cell`s that record which edges carry a line and which node sits there. A
`Charset` (Unicode, ASCII or branch symbols) then maps each cell to a two-column glyph,
and `draw` joins them into a line.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


class PipeKind(IntEnum):
    """Role of a pipe in a row; the integer order is the within-lane sort order."""

    STARTS = 0
    CONTINUES = 1
    TERMINATES = 2


@dataclass(frozen=True)
class LayoutCommit:
    """Minimal commit identity needed to lay out the graph."""

    sha: str
    parents: tuple[str, ...]


@dataclass(frozen=True)
class Pipe:
    """A line segment between a commit and one of its parents within a single row."""

    from_sha: str
    to_sha: str
    from_lane: int
    to_lane: int
    kind: PipeKind


@dataclass(frozen=True)
class Row:
    """A laid-out commit: its lane and every pipe drawn on its row."""

    sha: str
    lane: int
    pipes: tuple[Pipe, ...]
    is_merge: bool


class GraphOrderError(ValueError):
    """Raised when a parent appears before one of its children."""


def _lowest_free(min_lane: int, *blocked: set[int]) -> int:
    """Find the lowest lane at or above `min_lane` that no set blocks.

    Args:
        min_lane: First lane to consider.
        *blocked: Sets of lanes that are unavailable.

    Returns:
        int: The lowest free lane.
    """
    lane = min_lane
    while any(lane in b for b in blocked):
        lane += 1
    return lane


def _leftmost_free(lane: int, floor: int, blocked: set[int]) -> int:
    """Slide a lane left toward `floor` until the next lane is blocked.

    Args:
        lane: Lane to start from.
        floor: Lane to stop above; the lane itself is never reached.
        blocked: Lanes that cannot be entered.

    Returns:
        int: The leftmost lane reached.
    """
    last = lane
    for i in range(lane, floor, -1):
        if i in blocked:
            break
        last = i
    return last


def layout(commits: Sequence[LayoutCommit], trunk: frozenset[str] = frozenset()) -> list[Row]:
    """Assign each commit a lane and compute the pipes drawn on its row.

    Commits must be topologically ordered, children before parents. Trunk commits are
    pinned to lane 0 and every other branch is kept at lane 1 or higher.

    Args:
        commits: Commits in display order, newest first.
        trunk: Shas whose first-parent line is pinned to lane 0.

    Returns:
        list[Row]: One row per commit, in the same order.

    Raises:
        GraphOrderError: If a parent is listed before its child or a sha is listed twice.
    """
    min_lane = 1 if trunk else 0
    seen: set[str] = set()
    prev: list[Pipe] = []
    rows: list[Row] = []

    for commit in commits:
        if commit.sha in seen:
            msg = f"Commit {commit.sha} listed more than once"
            raise GraphOrderError(msg)
        parents = tuple(dict.fromkeys(p for p in commit.parents if p != commit.sha))
        for parent in parents:
            if parent in seen:
                msg = f"Parent {parent} listed before its child {commit.sha}"
                raise GraphOrderError(msg)

        current = [p for p in prev if p.kind is not PipeKind.TERMINATES]
        pos = _choose_lane(commit.sha, current, trunk, min_lane)

        new = _next_pipes(commit.sha, parents, current, pos, min_lane)
        rows.append(Row(sha=commit.sha, lane=pos, pipes=tuple(new), is_merge=len(parents) > 1))
        seen.add(commit.sha)
        prev = new

    return rows


def _choose_lane(sha: str, current: list[Pipe], trunk: frozenset[str], min_lane: int) -> int:
    """Pick the lane for a commit: trunk lane, under its first child, or the first free one.

    Args:
        sha: The commit being placed.
        current: Pipes still open from the row above.
        trunk: Shas pinned to lane 0.
        min_lane: Lowest lane available to non-trunk commits.

    Returns:
        int: The commit's lane.
    """
    if sha in trunk:
        return 0
    for p in current:
        if p.to_sha == sha:
            return p.to_lane
    return _lowest_free(min_lane, {p.to_lane for p in current})


def _next_pipes(
    sha: str, parents: tuple[str, ...], current: list[Pipe], pos: int, min_lane: int
) -> list[Pipe]:
    """Compute the pipes on a commit's row from the still-open pipes of the row above.

    Args:
        sha: The commit being placed.
        parents: Its de-duplicated parents, first parent first.
        current: Pipes still open from the row above.
        pos: The commit's lane.
        min_lane: Lowest lane available to non-trunk pipes.

    Returns:
        list[Pipe]: The row's pipes, sorted by target lane then kind.
    """
    taken: set[int] = {pos}
    traversed: set[int] = set()
    continuing_lanes = {p.to_lane for p in current if p.to_sha != sha}
    new: list[Pipe] = []

    def traverse(a: int, b: int) -> None:
        traversed.update(range(min(a, b), max(a, b) + 1))
        taken.add(b)

    if parents:
        new.append(Pipe(sha, parents[0], pos, pos, PipeKind.STARTS))

    for p in current:
        if p.to_sha == sha:
            new.append(Pipe(p.from_sha, p.to_sha, p.to_lane, pos, PipeKind.TERMINATES))
            traverse(p.to_lane, pos)
        elif p.to_lane < pos:
            # Lane 0 holds only trunk pipes, so they never shift.
            target = 0 if p.to_lane == 0 else _lowest_free(min_lane, traversed)
            new.append(Pipe(p.from_sha, p.to_sha, p.to_lane, target, PipeKind.CONTINUES))
            traverse(p.to_lane, target)

    for parent in parents[1:]:
        lane = _lowest_free(min_lane, taken, continuing_lanes)
        new.append(Pipe(sha, parent, pos, lane, PipeKind.STARTS))
        taken.add(lane)

    for p in current:
        if p.to_sha != sha and p.to_lane > pos:
            last = _leftmost_free(p.to_lane, pos, taken | traversed)
            new.append(Pipe(p.from_sha, p.to_sha, p.to_lane, last, PipeKind.CONTINUES))
            traverse(p.to_lane, last)

    new.sort(key=lambda p: (p.to_lane, p.kind))
    return new


class NodeKind(Enum):
    """What a node cell represents."""

    COMMIT = "commit"
    MERGE = "merge"
    HEAD = "head"
    FOLD = "fold"
    FADE = "fade"


LineKey = tuple[bool, bool, bool, bool]  # (up, down, left, right)


@dataclass(frozen=True)
class Cell:
    """One lane column of a row: which edges carry a line, and the node drawn in it."""

    up: bool = False
    down: bool = False
    left: bool = False
    right: bool = False
    node: NodeKind | None = None
    vertical: Pipe | None = None
    horizontal: Pipe | None = None


# Identity equality: the dict fields make field-based hashing impossible, and each
# charset is a module-level singleton anyway.
@dataclass(frozen=True, eq=False)
class Charset:
    """Glyph tables for drawing cells; every lane is exactly two columns wide."""

    name: str
    lines: Mapping[LineKey, str]
    nodes: Mapping[NodeKind, str]
    node_shapes: Mapping[tuple[NodeKind, bool, bool], str]
    horizontal: str

    def glyph(self, cell: Cell) -> str:
        """Return the two-character glyph for a cell.

        Args:
            cell: The cell to draw.

        Returns:
            str: Exactly two characters.
        """
        if cell.node is not None:
            node = self.node_shapes.get((cell.node, cell.up, cell.down), self.nodes[cell.node])
            return node + (self.horizontal if cell.right else " ")
        return self.lines[(cell.up, cell.down, cell.left, cell.right)]


def _both_lefts(rows: Mapping[tuple[bool, bool, bool | None, bool], str]) -> dict[LineKey, str]:
    """Expand rows whose `left` is None (any) into both concrete keys."""
    out: dict[LineKey, str] = {}
    for (up, down, left, right), glyph in rows.items():
        for value in (False, True) if left is None else (left,):
            out[(up, down, value, right)] = glyph
    return out


_T, _F = True, False

_UNICODE_LINES = _both_lefts(
    {
        (_T, _T, None, _T): "│─",
        (_T, _T, None, _F): "│ ",
        (_T, _F, _T, _T): "┴─",
        (_T, _F, _T, _F): "╯ ",
        (_T, _F, _F, _T): "╰─",
        (_T, _F, _F, _F): "╵ ",
        (_F, _T, _T, _T): "┬─",
        (_F, _T, _T, _F): "╮ ",
        (_F, _T, _F, _T): "╭─",
        (_F, _T, _F, _F): "╷ ",
        (_F, _F, _T, _T): "──",
        (_F, _F, _T, _F): "─ ",
        (_F, _F, _F, _T): "╶─",
        (_F, _F, _F, _F): "  ",
    }
)

_ASCII_LINES = _both_lefts(
    {
        (_T, _T, None, _T): "|-",
        (_T, _T, None, _F): "| ",
        (_T, _F, _T, _T): "'-",
        (_T, _F, _T, _F): "' ",
        (_T, _F, _F, _T): "'-",
        (_T, _F, _F, _F): "| ",
        (_F, _T, _T, _T): ".-",
        (_F, _T, _T, _F): ". ",
        (_F, _T, _F, _T): ".-",
        (_F, _T, _F, _F): "| ",
        (_F, _F, _T, _T): "--",
        (_F, _F, _T, _F): "- ",
        (_F, _F, _F, _T): " -",
        (_F, _F, _F, _F): "  ",
    }
)

# The original kitty range has no half-line symbols, so those keys keep the box glyphs.
_BRANCH_LINES = {
    **_UNICODE_LINES,
    **_both_lefts(
        {
            (_T, _T, None, _T): "\uf5d1\uf5d0",
            (_T, _T, None, _F): "\uf5d1 ",
            (_T, _F, _T, _T): "\uf5e5\uf5d0",
            (_T, _F, _T, _F): "\uf5d9 ",
            (_T, _F, _F, _T): "\uf5d8\uf5d0",
            (_F, _T, _T, _T): "\uf5e2\uf5d0",
            (_F, _T, _T, _F): "\uf5d7 ",
            (_F, _T, _F, _T): "\uf5d6\uf5d0",
            (_F, _F, _T, _T): "\uf5d0\uf5d0",
            (_F, _F, _T, _F): "\uf5d0 ",
        }
    ),
}

_BRANCH_FILL = "\uf5d4"

UNICODE = Charset(
    name="unicode",
    lines=_UNICODE_LINES,
    nodes={
        NodeKind.COMMIT: "●",
        NodeKind.MERGE: "◎",
        NodeKind.HEAD: "◉",
        NodeKind.FOLD: "┊",
        NodeKind.FADE: "╎",
    },
    node_shapes={},
    horizontal="─",
)

ASCII = Charset(
    name="ascii",
    lines=_ASCII_LINES,
    nodes={
        NodeKind.COMMIT: "*",
        NodeKind.MERGE: "M",
        NodeKind.HEAD: "@",
        NodeKind.FOLD: ":",
        NodeKind.FADE: ":",
    },
    node_shapes={},
    horizontal="-",
)

BRANCH_SYMBOLS = Charset(
    name="branch-symbols",
    lines=_BRANCH_LINES,
    nodes={
        NodeKind.COMMIT: "\uf5ef",
        NodeKind.MERGE: "\uf5ee",
        NodeKind.HEAD: "\uf5ee",
        NodeKind.FOLD: _BRANCH_FILL,
        NodeKind.FADE: _BRANCH_FILL,
    },
    node_shapes={
        (NodeKind.COMMIT, _T, _T): "\uf5fb",
        (NodeKind.COMMIT, _F, _T): "\uf5f7",
        (NodeKind.COMMIT, _T, _F): "\uf5f9",
        (NodeKind.COMMIT, _F, _F): "\uf5ef",
        (NodeKind.MERGE, _T, _T): "\uf5fa",
        (NodeKind.MERGE, _F, _T): "\uf5f6",
        (NodeKind.MERGE, _T, _F): "\uf5f8",
        (NodeKind.MERGE, _F, _F): "\uf5ee",
        (NodeKind.HEAD, _T, _T): "\uf5fa",
        (NodeKind.HEAD, _F, _T): "\uf5f6",
        (NodeKind.HEAD, _T, _F): "\uf5f8",
        (NodeKind.HEAD, _F, _F): "\uf5ee",
    },
    horizontal="\uf5d0",
)


class _LaneState:
    """Mutable accumulator for one lane while a row's pipes are merged."""

    __slots__ = ("down", "horizontal", "left", "node", "right", "up", "vertical")

    def __init__(self) -> None:
        self.up = False
        self.down = False
        self.left = False
        self.right = False
        self.node: NodeKind | None = None
        self.vertical: Pipe | None = None
        self.horizontal: Pipe | None = None

    def freeze(self) -> Cell:
        """Return the accumulated state as an immutable cell."""
        return Cell(
            self.up,
            self.down,
            self.left,
            self.right,
            self.node,
            self.vertical,
            self.horizontal,
        )


def row_cells(row: Row, node: NodeKind) -> list[Cell]:
    """Turn a row's pipes into one cell per lane.

    Port of lazygit's `renderPipeSet`: horizontals and verticals are merged per lane, and
    where a horizontal crosses a vertical the vertical wins.

    Args:
        row: The laid-out row.
        node: The node kind drawn at the row's lane.

    Returns:
        list[Cell]: Cells for lanes 0 through the rightmost lane used.
    """
    width = max([row.lane, *(lane for p in row.pipes for lane in (p.from_lane, p.to_lane))]) + 1
    # Mutable per-lane state, frozen once at the end: replacing frozen cells per segment is
    # too slow on windows with many thousands of commits.
    lanes = [_LaneState() for _ in range(width)]

    # STARTS first so that continuing and terminating pipes own shared segments.
    ordered = sorted(row.pipes, key=lambda p: p.kind is not PipeKind.STARTS)
    for pipe in ordered:
        low, high = sorted((pipe.from_lane, pipe.to_lane))
        if low != high:
            for lane in range(low + 1, high):
                state = lanes[lane]
                state.left = state.right = True
                state.horizontal = pipe
            lanes[low].right = True
            lanes[low].horizontal = pipe
            lanes[high].left = True
            lanes[high].horizontal = pipe
        if pipe.kind in (PipeKind.STARTS, PipeKind.CONTINUES):
            lanes[pipe.to_lane].down = True
            lanes[pipe.to_lane].vertical = pipe
        if pipe.kind in (PipeKind.TERMINATES, PipeKind.CONTINUES):
            lanes[pipe.from_lane].up = True
            lanes[pipe.from_lane].vertical = pipe

    lanes[row.lane].node = node
    return [state.freeze() for state in lanes]


def fold_cells(lanes: frozenset[int], lane: int, pipes: Sequence[Pipe] = ()) -> list[Cell]:
    """Build the marker row for a folded run of commits.

    Args:
        lanes: Lanes whose lines continue through the fold.
        lane: Lane that carries the fold marker.
        pipes: Pipes of the row the fold stands in for, used to record each lane's owner.

    Returns:
        list[Cell]: Cells for lanes 0 through the rightmost lane used.
    """
    width = max([lane, *lanes]) + 1
    # Pipes sharing a target lane keep the last one, the same overwrite order row_cells uses.
    owners = {p.to_lane: p for p in pipes if p.kind is not PipeKind.TERMINATES}
    return [
        Cell(
            up=i in lanes,
            down=i in lanes,
            node=NodeKind.FOLD if i == lane else None,
            vertical=owners.get(i),
        )
        for i in range(width)
    ]


def fade_cells(last: Row) -> list[Cell] | None:
    """Build the row that marks lanes still open below the last drawn commit.

    Args:
        last: The final row of the window.

    Returns:
        list[Cell] | None: Cells with a fade node on each open lane, or None if all lanes closed.
    """
    open_pipes = {p.to_lane: p for p in last.pipes if p.kind is not PipeKind.TERMINATES}
    if not open_pipes:
        return None
    return [
        Cell(
            node=NodeKind.FADE if i in open_pipes else None,
            vertical=open_pipes.get(i),
        )
        for i in range(max(open_pipes) + 1)
    ]


def draw(cells: Sequence[Cell], charset: Charset) -> str:
    """Join cell glyphs into a line, stripping trailing spaces.

    Args:
        cells: The cells of one row.
        charset: Glyph tables to draw with.

    Returns:
        str: The drawn line.
    """
    return "".join(charset.glyph(c) for c in cells).rstrip()


def charset_for(style: str, encoding: str) -> Charset:
    """Pick the charset for a configured graph style.

    Args:
        style: One of "auto", "unicode", "branch-symbols" or "ascii".
        encoding: The output stream encoding, consulted only for "auto".

    Returns:
        Charset: The charset to draw with. An explicit style always wins over the encoding.
    """
    if style == "unicode":
        return UNICODE
    if style == "branch-symbols":
        return BRANCH_SYMBOLS
    if style == "ascii":
        return ASCII
    normalized = encoding.lower().replace("-", "").replace("_", "")
    return UNICODE if normalized.startswith("utf") else ASCII
