"""Branch graph rendering for `gx log --graph`.

Lays out the commit graph itself from `git log --topo-order` parent data, so
lanes connect with box-drawing glyphs and each branch keeps its own lane. The
commit window reaches back past the oldest fork point, and long runs of plain
commits fold into a single line so branch tips, tags, and fork points stay on
screen together.

Usage:
    from gx.lib.log_graph import LogGraph

    lines = LogGraph(count=15).render()
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

import typer
from nclutils import pp
from nclutils.git import all_local_branches
from rich.text import Text

from gx.constants import LOG_ALL_REFS_ARGS
from gx.lib.branch import find_default_branch, has_commits
from gx.lib.config import config
from gx.lib.git import git, raise_on_error
from gx.lib.graph_layout import (
    Cell,
    Charset,
    GraphOrderError,
    LayoutCommit,
    NodeKind,
    PipeKind,
    Row,
    charset_for,
    fade_cells,
    fold_cells,
    layout,
    row_cells,
)

_FIELD_SEP = "\x1f"
_GRAPH_FORMAT = "%H%x1f%P%x1f%h%x1f%at%x1f%an%x1f%D%x1f%s"
_GRAPH_FIELDS = 7

# Commits of default-branch history shown below the oldest fork point, so the
# fork itself reads as a branch leaving a line rather than the bottom edge.
FORK_CONTEXT = 2

# (seconds, suffix) pairs for the compact commit age, largest unit first.
_AGE_UNITS = (
    (365 * 86400, "y"),
    (30 * 86400, "mo"),
    (7 * 86400, "w"),
    (86400, "d"),
    (3600, "h"),
    (60, "m"),
    (1, "s"),
)

# Runs shorter than this stay unfolded; folding two lines into one saves nothing.
FOLD_MIN_RUN = 4


@dataclass(frozen=True)
class CommitRecord:
    """One commit parsed from `git log` in the layout format."""

    sha: str
    parents: tuple[str, ...]
    short_sha: str
    timestamp: int
    author: str
    refs: str
    subject: str


@dataclass(frozen=True)
class GraphEntry:
    """A commit paired with its laid-out row."""

    commit: CommitRecord
    row: Row


@dataclass(frozen=True)
class LaneFold:
    """A run of plain commits collapsed into one line within a lane."""

    lane: int
    lanes: frozenset[int]
    hidden: int


GraphLine = GraphEntry | LaneFold


def parse_commit_line(line: str) -> CommitRecord | None:
    """Parse one `git log` line produced with the layout format.

    Args:
        line: One line of output using `_GRAPH_FORMAT`.

    Returns:
        A CommitRecord, or None when the line is malformed.
    """
    # The subject is last, so splitting on a bounded count keeps any separator it contains.
    parts = line.split(_FIELD_SEP, _GRAPH_FIELDS - 1)
    if len(parts) != _GRAPH_FIELDS:
        return None
    sha, parents, short_sha, timestamp, author, refs, subject = parts
    if not sha:
        return None
    return CommitRecord(
        sha=sha,
        parents=tuple(parents.split()),
        short_sha=short_sha,
        timestamp=int(timestamp) if timestamp.isascii() and timestamp.isdigit() else 0,
        author=author,
        refs=refs,
        subject=subject,
    )


def is_straight(row: Row) -> bool:
    """Report whether a row is a plain pass-through commit in a single lane.

    Args:
        row: A laid-out row.

    Returns:
        bool: True when the row has one STARTS pipe, at most one TERMINATES pipe, and
            no pipe changes lane.
    """
    starts = 0
    terminates = 0
    for pipe in row.pipes:
        if pipe.from_lane != pipe.to_lane:
            return False
        if pipe.kind is PipeKind.STARTS:
            starts += 1
        elif pipe.kind is PipeKind.TERMINATES:
            terminates += 1
    return starts == 1 and terminates <= 1


def _open_lanes(row: Row) -> frozenset[int]:
    """Return the lanes whose lines continue below a row.

    Args:
        row: A laid-out row.

    Returns:
        frozenset[int]: Target lanes of every pipe that does not terminate on the row.
    """
    return frozenset(p.to_lane for p in row.pipes if p.kind is not PipeKind.TERMINATES)


def fold_entries(entries: list[GraphEntry], keep: frozenset[str]) -> list[GraphEntry | LaneFold]:
    """Collapse long runs of plain commits that stay in one lane.

    A run is consecutive straight rows in the same lane with the same open
    lanes, none carrying a ref or listed in `keep`. A run of FOLD_MIN_RUN or
    more keeps its first and last entry and the middle becomes one LaneFold.

    Args:
        entries: Laid-out commits in display order.
        keep: Full SHAs that must never fold, such as branch fork points.
    """
    out: list[GraphEntry | LaneFold] = []
    run: list[GraphEntry] = []
    run_lanes: frozenset[int] = frozenset()

    def flush() -> None:
        if len(run) >= FOLD_MIN_RUN:
            out.append(run[0])
            out.append(LaneFold(lane=run[1].row.lane, lanes=run_lanes, hidden=len(run) - 2))
            out.append(run[-1])
        else:
            out.extend(run)
        run.clear()

    for entry in entries:
        if entry.commit.refs or entry.commit.sha in keep or not is_straight(entry.row):
            flush()
            out.append(entry)
            continue
        lanes = _open_lanes(entry.row)
        if run and (run[0].row.lane != entry.row.lane or run_lanes != lanes):
            flush()
        if not run:
            run_lanes = lanes
        run.append(entry)
    flush()
    return out


def short_age(timestamp: int, now: int) -> str:
    """Format the time since a commit as a compact age such as `40m` or `3d`.

    Args:
        timestamp: Commit time as a Unix timestamp.
        now: Current time as a Unix timestamp.
    """
    elapsed = max(now - timestamp, 0)
    for seconds, suffix in _AGE_UNITS:
        if elapsed >= seconds:
            return f"{elapsed // seconds}{suffix}"
    return "0s"


def _node_kind(entry: GraphEntry) -> NodeKind:
    refs = [r.strip() for r in entry.commit.refs.split(",")]
    if any(r == "HEAD" or r.startswith("HEAD -> ") for r in refs):
        return NodeKind.HEAD
    return NodeKind.MERGE if entry.row.is_merge else NodeKind.COMMIT


def _graph_text(cells: list[Cell], charset: Charset) -> Text:
    """Draw cells as dim glyphs, leaving commit, merge and HEAD node characters unstyled."""
    text = Text()
    for cell in cells:
        glyph = charset.glyph(cell)
        if cell.node is None or cell.node in (NodeKind.FOLD, NodeKind.FADE):
            text.append(glyph, style="dim")
        else:
            text.append(glyph[0])
            text.append(glyph[1:], style="dim")
    text.rstrip()
    return text


def render_line(
    line: GraphLine,
    charset: Charset,
    *,
    now: int,
    width: int | None = None,
    show_author: bool = False,
) -> Text:
    """Style one graph line for the terminal.

    The subject comes before the age and author so it survives a narrow
    terminal: when the full line does not fit `width`, the trailing metadata is
    dropped before any of the subject is cut.

    Args:
        line: A laid-out commit or a fold marker.
        charset: Glyph tables for the lane graph.
        now: Current time as a Unix timestamp, for the commit age.
        width: Available columns, or None to always include the metadata.
        show_author: Whether to append the author after the age.
    """
    if isinstance(line, LaneFold):
        text = _graph_text(fold_cells(line.lanes, line.lane), charset)
        noun = "commit" if line.hidden == 1 else "commits"
        text.append(" ")
        text.append(f"… {line.hidden} more {noun}", style="dim italic")
        return text

    commit = line.commit
    text = _graph_text(row_cells(line.row, _node_kind(line)), charset)
    text.append(" ")
    text.append(commit.short_sha, style="yellow")
    text.append(" ")
    if commit.refs:
        text.append("(", style="dim")
        text.append(commit.refs, style="bold magenta")
        text.append(") ", style="dim")
    text.append(commit.subject)

    meta = Text("  ")
    meta.append(short_age(commit.timestamp, now), style="green")
    if show_author:
        meta.append(" ")
        meta.append(commit.author, style="blue")
    if width is None or text.cell_len + meta.cell_len <= width:
        text.append_text(meta)
    return text


def join_blocks(main: list[CommitRecord], extra: list[CommitRecord]) -> list[CommitRecord]:
    """Concatenate two disjoint topologically ordered blocks so children precede parents.

    The extra block's query excludes everything the main block's refs reach, so an
    extra commit is never an ancestor of a main commit. The extra block goes after
    the main one unless one of its commits descends from a main commit.

    Args:
        main: Commits from the main query.
        extra: Commits from the query for unrelated histories.

    Returns:
        list[CommitRecord]: Both blocks in an order the layout accepts.
    """
    main_shas = {c.sha for c in main}
    if any(parent in main_shas for c in extra for parent in c.parents):
        return [*extra, *main]
    return [*main, *extra]


def _escape_glob(ref: str) -> str:
    """Escape glob metacharacters so `--exclude` matches the ref name literally."""
    return re.sub(r"([\\*?\[])", r"\\\1", ref)


class LogGraph:
    """Branch graph of every ref, windowed to show where local branches fork.

    The window reaches FORK_CONTEXT commits below the oldest point where a
    local branch leaves the default branch. `count` sets a floor: when the fork
    window holds fewer commits, the newest `count` commits are shown instead.

    Args:
        count: Minimum number of commits to include.
        fold: Whether to collapse long runs of plain commits.
    """

    def __init__(self, count: int = 15, *, fold: bool = True) -> None:
        self.count = count
        self.fold = fold

    def render(self, width: int | None = None) -> list[Text]:
        """Fetch the graph from git and return one styled Text per line.

        The author is shown only when the visible commits have more than one,
        since a single author on every line adds width without information.

        Args:
            width: Available columns, used to drop trailing metadata before
                cutting a subject. None always includes it.

        Raises:
            typer.Exit: If git fails.
        """
        resolved = self._resolve_default(find_default_branch()) if has_commits() else None
        default, tip = resolved or (None, None)
        fork_points = self._fork_points(default)
        blocks = [self._fetch(revs) for revs in self._window_queries(fork_points)]
        commits = join_blocks(*blocks) if len(blocks) > 1 else blocks[0]
        if not commits:
            return []

        try:
            rows = layout(
                [LayoutCommit(c.sha, c.parents) for c in commits], self._trunk(commits, tip)
            )
        except GraphOrderError as exc:
            pp.error("git returned commits out of topological order", details=[str(exc)])
            raise typer.Exit(1) from exc

        entries = [GraphEntry(commit=c, row=r) for c, r in zip(commits, rows, strict=True)]
        lines: list[GraphLine] = [*fold_entries(entries, fork_points)] if self.fold else [*entries]
        authors = {line.commit.author for line in lines if isinstance(line, GraphEntry)}
        charset = charset_for(config.graph_style, pp.console().encoding or "")
        now = int(time.time())
        out = [
            render_line(line, charset, now=now, width=width, show_author=len(authors) > 1)
            for line in lines
        ]
        fade = fade_cells(rows[-1])
        if fade is not None:
            out.append(_graph_text(fade, charset))
        return out

    @staticmethod
    def _resolve_default(name: str | None) -> tuple[str, str] | None:
        """Return a ref that resolves to the default branch tip, with the tip's SHA.

        The local branch may be gone (deleted in a worktree-heavy clone), in which case
        the remote-tracking ref is used instead.

        Args:
            name: The default branch name, or None if there is none.

        Returns:
            tuple[str, str] | None: The ref (`name`, or `<remote>/<name>` for the first
                remote that has it) and its commit SHA, or None when nothing resolves.
        """
        if not name:
            return None
        local = git("rev-parse", "--verify", "--quiet", f"{name}^{{commit}}")
        if local.ok and local.stdout:
            return name, local.stdout

        remotes = git("remote")
        if not remotes.ok:
            return None
        # `origin` first, since it is the remote a default branch is normally read from.
        for remote in sorted(remotes.stdout.split(), key=lambda r: r != "origin"):
            ref = f"{remote}/{name}"
            result = git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
            if result.ok and result.stdout:
                return ref, result.stdout
        return None

    @staticmethod
    def _trunk(commits: list[CommitRecord], tip: str | None) -> frozenset[str]:
        """Return the default branch's first-parent chain within the window.

        Walks the parsed commits in memory instead of asking git for a second
        `rev-list --first-parent`, which would cover the same commits.

        Args:
            commits: The parsed commits in the window.
            tip: Full SHA of the default branch tip, or None if there is none.
        """
        by_sha = {c.sha: c for c in commits}
        trunk: set[str] = set()
        sha = tip
        while sha in by_sha:
            trunk.add(sha)
            parents = by_sha[sha].parents
            sha = parents[0] if parents else None
        return frozenset(trunk)

    @staticmethod
    def _fork_points(target: str | None) -> frozenset[str]:
        """Return the full SHA where each local branch leaves the default branch."""
        if not target:
            return frozenset()

        points: set[str] = set()
        for branch in all_local_branches():
            if branch == target:
                continue
            result = git("merge-base", target, branch)
            if result.ok and result.stdout:
                points.add(result.stdout)
        return frozenset(points)

    @staticmethod
    def _fetch(revs: list[str]) -> list[CommitRecord]:
        """Run one windowed `git log` and parse its commits.

        Args:
            revs: Revision and limiting arguments for the query.

        Returns:
            list[CommitRecord]: The commits in topological order.

        Raises:
            typer.Exit: If git fails.
        """
        result = raise_on_error(git("log", "--topo-order", *revs, f"--format={_GRAPH_FORMAT}"))
        return [c for line in result.stdout.splitlines() if (c := parse_commit_line(line))]

    def _window_queries(self, fork_points: frozenset[str]) -> list[list[str]]:
        """Build the revision arguments for each `git log` query the window needs.

        Returns:
            list[list[str]]: The main query, then a date-bounded query for histories
                unrelated to the window when any exist.
        """
        newest = [[*LOG_ALL_REFS_ARGS, f"-n{self.count}"]]
        if not fork_points:
            return newest

        oldest = git("merge-base", "--octopus", *fork_points)
        if not oldest.ok or not oldest.stdout:
            return newest

        stop = git("log", "-1", "--format=%H %ct", f"{oldest.stdout}~{FORK_CONTEXT}")
        if not stop.ok or not stop.stdout:
            # History below the oldest fork is shorter than the context, so show it all.
            return [list(LOG_ALL_REFS_ARGS)]

        stop_sha, stop_time = stop.stdout.split()
        unrelated = self._unrelated_refs(stop_sha)
        excludes = [f"--exclude={_escape_glob(ref)}" for ref in unrelated]
        main = [*excludes, *LOG_ALL_REFS_ARGS, f"^{stop_sha}"]
        in_window = git("rev-list", "--count", *main)
        if in_window.ok and in_window.stdout.isdigit() and int(in_window.stdout) < self.count:
            return newest
        if not unrelated:
            return [main]
        # `^stop` cannot bound a history unrelated to it (an orphan gh-pages branch),
        # so those refs get a date limit in a query of their own. A date limit on the
        # main query would drop old commits that a recent merge brought in.
        return [main, [*unrelated, f"--since=@{stop_time}", "--not", *excludes, *LOG_ALL_REFS_ARGS]]

    @staticmethod
    def _unrelated_refs(stop_sha: str) -> list[str]:
        """Return refs whose history never meets the window's stop commit.

        Args:
            stop_sha: The commit the window stops at.

        Returns:
            list[str]: Full ref names, such as `refs/heads/gh-pages`.
        """
        # Roots that `^stop` does not exclude belong to histories unrelated to it.
        roots = git("rev-list", "--max-parents=0", *LOG_ALL_REFS_ARGS, f"^{stop_sha}")
        if not roots.ok or not roots.stdout:
            return []
        refs = git(
            "for-each-ref",
            "--format=%(refname)",
            f"--no-contains={stop_sha}",
            *(f"--contains={root}" for root in roots.stdout.split()),
        )
        return refs.stdout.split() if refs.ok else []
