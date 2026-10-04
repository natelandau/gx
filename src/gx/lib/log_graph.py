"""Branch graph rendering for `gx log --graph`.

Wraps `git log --graph` so the view shows where each local branch forks off
the default branch: the commit window reaches back past the oldest fork point,
and long runs of plain commits fold into a single line so branch tips, tags,
and fork points stay on screen together.

Usage:
    from gx.lib.log_graph import LogGraph

    lines = LogGraph(count=15).render()
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from nclutils.git import all_local_branches
from rich.text import Text

from gx.constants import LOG_ALL_REFS_ARGS
from gx.lib.branch import find_default_branch, has_commits
from gx.lib.git import git, raise_on_error

_FIELD_SEP = "\x1f"
# Every commit line carries the separator, so its absence marks a connector-only line.
_GRAPH_FORMAT = "%x1f%H%x1f%h%x1f%at%x1f%an%x1f%D%x1f%s"
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
class GraphCommit:
    """One commit line from `git log --graph`, split into graph prefix and fields."""

    prefix: str
    sha: str
    short_sha: str
    timestamp: int
    author: str
    refs: str
    subject: str


@dataclass(frozen=True)
class GraphFold:
    """A run of plain commits collapsed into one line."""

    prefix: str
    hidden: int


GraphLine = GraphCommit | GraphFold | str


def parse_graph_line(line: str) -> GraphCommit | str:
    """Split a raw `git log --graph` line into a commit, or pass a connector line through.

    Args:
        line: One line of `git log --graph` output produced with the module's format.

    Returns:
        A GraphCommit for commit lines, or the line unchanged for connector-only lines.
    """
    parts = line.split(_FIELD_SEP)
    if len(parts) != _GRAPH_FIELDS:
        return line
    prefix, sha, short_sha, timestamp, author, refs, subject = parts
    return GraphCommit(
        prefix=prefix,
        sha=sha,
        short_sha=short_sha,
        timestamp=int(timestamp) if timestamp.isdigit() else 0,
        author=author,
        refs=refs,
        subject=subject,
    )


def fold_runs(lines: list[GraphCommit | str], keep: frozenset[str]) -> list[GraphLine]:
    """Collapse long runs of plain commits that share one graph lane.

    A run is a sequence of consecutive commit lines with an identical graph
    prefix, none of which carries a ref or is in `keep`. Connector lines, a
    prefix change, or a kept commit end the run. A run of FOLD_MIN_RUN or more
    keeps its first and last commit so the lane's ends stay visible, and the
    middle becomes one GraphFold.

    Args:
        lines: Parsed graph lines in display order.
        keep: Full SHAs that must never fold, such as branch fork points.
    """
    out: list[GraphLine] = []
    run: list[GraphCommit] = []

    def flush() -> None:
        if len(run) >= FOLD_MIN_RUN:
            out.append(run[0])
            out.append(GraphFold(prefix=run[1].prefix, hidden=len(run) - 2))
            out.append(run[-1])
        else:
            out.extend(run)
        run.clear()

    for line in lines:
        if isinstance(line, str):
            flush()
            out.append(line)
            continue
        if line.refs or line.sha in keep:
            flush()
            out.append(line)
            continue
        if run and run[0].prefix != line.prefix:
            flush()
        run.append(line)
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


def render_graph_line(
    line: GraphLine, *, now: int, width: int | None = None, show_author: bool = False
) -> Text:
    """Style one graph line for the terminal.

    The subject comes before the age and author so it survives a narrow
    terminal: when the full line does not fit `width`, the trailing metadata is
    dropped before any of the subject is cut.

    Args:
        line: A parsed commit, a fold marker, or a connector-only line.
        now: Current time as a Unix timestamp, for the commit age.
        width: Available columns, or None to always include the metadata.
        show_author: Whether to append the author after the age.
    """
    if isinstance(line, str):
        return Text(line, style="dim")

    if isinstance(line, GraphFold):
        noun = "commit" if line.hidden == 1 else "commits"
        text = Text(line.prefix.replace("*", "┊", 1), style="dim")
        text.append(f"… {line.hidden} more {noun}", style="dim italic")
        return text

    text = Text(line.prefix)
    text.append(line.short_sha, style="yellow")
    text.append(" ")
    if line.refs:
        text.append("(", style="dim")
        text.append(line.refs, style="bold magenta")
        text.append(") ", style="dim")
    text.append(line.subject)

    meta = Text("  ")
    meta.append(short_age(line.timestamp, now), style="green")
    if show_author:
        meta.append(" ")
        meta.append(line.author, style="blue")
    if width is None or text.cell_len + meta.cell_len <= width:
        text.append_text(meta)
    return text


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
        fork_points = self._fork_points()
        result = raise_on_error(
            git(
                "log",
                "--graph",
                *LOG_ALL_REFS_ARGS,
                *self._window_args(fork_points),
                f"--format={_GRAPH_FORMAT}",
            )
        )
        if not result.stdout:
            return []

        parsed = [parse_graph_line(line) for line in result.stdout.splitlines()]
        lines: list[GraphLine] = fold_runs(parsed, fork_points) if self.fold else list(parsed)
        authors = {line.author for line in lines if isinstance(line, GraphCommit)}
        now = int(time.time())
        return [
            render_graph_line(line, now=now, width=width, show_author=len(authors) > 1)
            for line in lines
        ]

    @staticmethod
    def _fork_points() -> frozenset[str]:
        """Return the full SHA where each local branch leaves the default branch."""
        if not has_commits():
            return frozenset()

        target = find_default_branch()
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

    def _window_args(self, fork_points: frozenset[str]) -> list[str]:
        """Build the revision-limiting args for the graph window."""
        newest = [f"-n{self.count}"]
        if not fork_points:
            return newest

        oldest = git("merge-base", "--octopus", *fork_points)
        if not oldest.ok or not oldest.stdout:
            return newest

        stop = git("log", "-1", "--format=%H %ct", f"{oldest.stdout}~{FORK_CONTEXT}")
        if not stop.ok or not stop.stdout:
            # History below the oldest fork is shorter than the context, so show it all.
            return []

        stop_sha, stop_time = stop.stdout.split()
        # `^stop` cannot bound histories unrelated to it (an orphan gh-pages
        # branch), so the date limit keeps those from showing in full.
        window = [f"^{stop_sha}", f"--since=@{stop_time}"]
        in_window = git("rev-list", "--count", *LOG_ALL_REFS_ARGS, *window)
        if in_window.ok and in_window.stdout.isdigit() and int(in_window.stdout) < self.count:
            return newest
        return window
