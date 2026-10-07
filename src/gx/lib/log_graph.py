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
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import typer
from nclutils import pp
from rich.text import Text

from gx.constants import LOG_ALL_REFS_ARGS
from gx.lib.branch import find_default_branch
from gx.lib.config import config
from gx.lib.git import git, raise_on_error
from gx.lib.graph_layout import (
    ASCII,
    Cell,
    Charset,
    GraphOrderError,
    LayoutCommit,
    NodeKind,
    PipeKind,
    Row,
    charset_for,
    entering_lanes,
    fade_cells,
    fold_cells,
    layout,
    row_cells,
    uncommitted_cells,
)
from gx.lib.log_badges import BadgeSymbols, badge_symbols, render_badges
from gx.lib.log_context import (
    DIM,
    BranchState,
    LogContext,
    build_log_context,
    dimmed,
    read_branch_refs,
)
from gx.lib.refs import parse_refs

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from gx.lib.log_context import FileCounts
    from gx.lib.refs import RefDecoration

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
    uncommitted_above: bool = False


@dataclass(frozen=True)
class LaneFold:
    """A run of plain commits collapsed into one line within a lane."""

    lane: int
    lanes: frozenset[int]
    hidden: int
    row: Row | None = None


@dataclass(frozen=True)
class UncommittedRow:
    """A pseudo-row for a branch's uncommitted changes, drawn above its tip commit."""

    branch: str
    counts: FileCounts
    row: Row
    node_up: bool
    named: bool


GraphLine = GraphEntry | LaneFold | UncommittedRow


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
            out.append(
                LaneFold(
                    lane=run[1].row.lane,
                    lanes=run_lanes,
                    hidden=len(run) - 2,
                    row=run[1].row,
                )
            )
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


def describe_uncommitted(counts: FileCounts) -> str:
    """Summarize working-tree changes for the pseudo-row.

    Args:
        counts: Staged, modified, unmerged, and untracked file counts.

    Returns:
        str: `uncommitted: ` followed by each non-zero count.
    """
    labels = ("staged", "modified", "conflicted", "untracked")
    parts = [f"{n} {label}" for n, label in zip(counts, labels, strict=True) if n]
    return f"uncommitted: {', '.join(parts)}"


def insert_uncommitted(lines: Sequence[GraphLine], context: LogContext) -> list[GraphLine]:
    """Add a pseudo-row above the tip of every branch with uncommitted changes.

    Branches sharing a tip stack their rows, current branch first, then by name.

    Args:
        lines: Graph lines in display order.
        context: Branch context supplying each branch's tip and change counts.

    Returns:
        list[GraphLine]: The lines with pseudo-rows inserted; unchanged when none apply.
    """
    dirty_by_tip: dict[str, list[tuple[str, FileCounts]]] = {}
    for branch in sorted(context.branches.values(), key=lambda b: (not b.is_current, b.name)):
        if branch.dirty and branch.tip is not None:
            dirty_by_tip.setdefault(branch.tip, []).append((branch.name, branch.dirty))

    out: list[GraphLine] = []
    for line in lines:
        if not isinstance(line, GraphEntry) or line.commit.sha not in dirty_by_tip:
            out.append(line)
            continue
        dirty = dirty_by_tip[line.commit.sha]
        entered = line.row.lane in entering_lanes(line.row)
        out.extend(
            UncommittedRow(
                branch=name,
                counts=counts,
                row=line.row,
                node_up=index > 0 or entered,
                named=len(dirty) > 1,
            )
            for index, (name, counts) in enumerate(dirty)
        )
        out.append(replace(line, uncommitted_above=True))
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


def _node_kind(entry: GraphEntry, refs: RefDecoration) -> NodeKind:
    if refs.head is not None or refs.detached:
        return NodeKind.HEAD
    return NodeKind.MERGE if entry.row.is_merge else NodeKind.COMMIT


def _graph_text(
    cells: list[Cell], charset: Charset, context: LogContext, *, node_style: str = ""
) -> Text:
    """Draw cells with each glyph styled by the branch its pipe belongs to.

    Args:
        cells: Lane cells of one row.
        charset: Glyph tables for the lane graph.
        context: Branch context supplying pipe styles.
        node_style: Style for node characters, which carry no pipe of their own.
    """
    text = Text()
    for cell in cells:
        glyph = charset.glyph(cell)
        horizontal = context.pipe_style(cell.horizontal) if cell.horizontal else ""
        line_pipe = cell.vertical or cell.horizontal
        if cell.node is not None:
            first = node_style
        elif line_pipe is not None:
            first = context.pipe_style(line_pipe)
        else:
            first = ""
        text.append(glyph[0], style=first)
        text.append(glyph[1:], style=horizontal)
    text.rstrip()
    return text


def render_line(
    line: GraphLine,
    charset: Charset,
    *,
    context: LogContext,
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
        context: Branch context supplying colors and emphasis.
        now: Current time as a Unix timestamp, for the commit age.
        width: Available columns, or None to always include the metadata.
        show_author: Whether to append the author after the age.
    """
    if isinstance(line, UncommittedRow):
        branch = context.branches.get(line.branch)
        color = branch.color if branch is not None else ""
        tip_sha = line.row.sha
        text = _graph_text(
            uncommitted_cells(line.row, node_up=line.node_up),
            charset,
            context,
            node_style=color if tip_sha in context.head_reachable else dimmed(color),
        )
        label = describe_uncommitted(line.counts) + (f" on {line.branch}" if line.named else "")
        text.append(" ")
        text.append(label, style="dim italic")
        return text

    if isinstance(line, LaneFold):
        row = line.row
        node_style = dimmed(context.commit_style(row.sha)) if row else DIM
        text = _graph_text(
            fold_cells(line.lanes, line.lane, row.pipes if row else ()),
            charset,
            context,
            node_style=node_style,
        )
        noun = "commit" if line.hidden == 1 else "commits"
        owner = context.owner(row.sha) if row else None
        label = f"… {line.hidden} more {noun}" + (f" on {owner.name}" if owner else "")
        text.append(" ")
        text.append(label, style="dim italic")
        return text

    commit = line.commit
    owner = context.owner(commit.sha)
    refs = parse_refs(commit.refs, context.remotes)
    symbols = badge_symbols(charset, nerd_font=config.nerd_font)
    cells = row_cells(line.row, _node_kind(line, refs))
    if line.uncommitted_above:
        cells = [replace(c, up=True) if c.node is not None else c for c in cells]
    text = _graph_text(
        cells,
        charset,
        context,
        node_style=context.commit_style(commit.sha),
    )
    # Lanes beside the node carry their own dim; only the commit's text dims here.
    graph_end = len(text.plain)
    text.append(" ")
    text.append(commit.short_sha, style=context.sha_style(commit.sha))
    if commit.sha in context.unpushed:
        text.append(symbols.unpushed, style="dim")
    text.append(" ")
    badges = render_badges(refs, context, symbols)
    if badges:
        text.append_text(badges)
        text.append(" ")
    text.append(commit.subject, style="bold" if owner and owner.is_current else "")

    meta = Text("  ")
    meta.append(short_age(commit.timestamp, now), style="dim")
    if show_author:
        meta.append(" ")
        meta.append(commit.author, style="blue")
    if width is None or text.cell_len + meta.cell_len <= width:
        text.append_text(meta)
    if commit.sha not in context.head_reachable:
        text.stylize("dim", graph_end)
    return text


def _legend_marks(
    branch: BranchState, context: LogContext, symbols: BadgeSymbols, *, mark_local: bool
) -> list[str]:
    marks: list[str] = []
    if branch.is_current:
        marks.append("(current)")
    if mark_local and not branch.is_default and not branch.has_remote_upstream:
        marks.append("local")
    if branch.worktree is not None:
        marks.append(symbols.worktree.strip().removesuffix(":"))
    # A tip in the window shows its changes as a pseudo-row, so only off-window ones need a mark.
    if branch.dirty and branch.tip not in context.parents:
        marks.append(symbols.dirty)
    return marks


def render_legend(
    context: LogContext,
    charset: Charset,
    width: int | None,
    *,
    symbols: BadgeSymbols | None = None,
) -> Text | None:
    """Build the one-line legend mapping branch colors to names.

    Lists the default branch first, then the current branch, then the rest by name.
    When the line would exceed `width`, trailing entries collapse into a `+N more` tail
    when it fits. The first entry always shows.

    Args:
        context: Branch context supplying the visible branches and their colors.
        charset: Glyph tables, which decide the bullet character.
        width: Available columns, or None for no limit.
        symbols: Glyphs for the worktree and dirty marks; defaults to the charset's own.

    Returns:
        Text | None: The legend, or None when no branch besides the default is visible.
    """
    branches = sorted(
        context.branches.values(), key=lambda b: (not b.is_default, not b.is_current, b.name)
    )
    if not any(not b.is_default for b in branches):
        return None

    symbols = symbols or badge_symbols(charset)
    bullet = "*" if charset is ASCII else "●"
    # With no tracked branch every branch is local, so the mark would say nothing.
    mark_local = any(b.has_remote_upstream for b in branches)
    entries: list[Text] = []
    for branch in branches:
        entry = Text()
        entry.append(bullet, style=branch.color)
        entry.append(f" {branch.name}")
        for mark in _legend_marks(branch, context, symbols, mark_local=mark_local):
            entry.append(" ")
            entry.append(mark, style="dim")
        entries.append(entry)

    sep = "  "
    legend = Text()
    remaining = sum(len(sep) + entry.cell_len for entry in entries[1:])
    for index, entry in enumerate(entries):
        # The first entry always shows; print() crops overflow, so it is cut, never wrapped.
        # A tail is reserved only once the remaining entries cannot all fit.
        if index and width is not None and legend.cell_len + remaining > width:
            hidden_after = len(entries) - index - 1
            used = legend.cell_len + len(sep) + entry.cell_len
            tail = len(sep) + len(f"+{hidden_after} more") if hidden_after else 0
            if used + tail > width:
                more = f"+{len(entries) - index} more"
                if legend.cell_len + len(sep) + len(more) <= width:
                    legend.append(sep)
                    legend.append(more, style="dim")
                return legend
        if index:
            legend.append(sep)
            remaining -= len(sep) + entry.cell_len
        legend.append_text(entry)
    return legend


def render_clean_hint(context: LogContext) -> Text | None:
    """Build the line telling how many branches `gx clean` can remove.

    Args:
        context: Branch context holding every stale local branch.

    Returns:
        Text | None: The dim hint, or None when no branch is stale.
    """
    count = len(context.stale)
    if not count:
        return None
    noun = "branch" if count == 1 else "branches"
    hint = Text()
    hint.append(f"{count} {noun} can be cleaned up: gx clean", style="dim")
    return hint


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
    With `cap`, `count` is a ceiling instead and only the newest `count` commits
    are shown, even when that cuts off fork points.

    Args:
        count: Minimum number of commits to include, or the maximum with `cap`.
        fold: Whether to collapse long runs of plain commits.
        cap: Whether `count` limits the window instead of setting its floor.
    """

    def __init__(self, count: int = 15, *, fold: bool = True, cap: bool = False) -> None:
        self.count = count
        self.fold = fold
        self.cap = cap

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
        # The default branch can resolve while HEAD is unborn (an orphan checkout).
        resolved = self._resolve_default(find_default_branch())
        default, tip = resolved or (None, None)
        refs = read_branch_refs()
        fork_points = self._fork_points(default, refs.tips)
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
        context = build_log_context(
            {c.sha: c.parents for c in commits}, default=default, default_tip=tip, refs=refs
        )
        lines = insert_uncommitted(lines, context)
        now = int(time.time())
        out = [
            render_line(
                line, charset, context=context, now=now, width=width, show_author=len(authors) > 1
            )
            for line in lines
        ]
        fade = fade_cells(rows[-1])
        if fade is not None:
            out.append(_graph_text(fade, charset, context, node_style="dim"))
        legend = render_legend(
            context, charset, width, symbols=badge_symbols(charset, nerd_font=config.nerd_font)
        )
        hint = render_clean_hint(context)
        if legend is not None:
            out.extend([Text(""), legend])
        if hint is not None:
            if legend is None:
                out.append(Text(""))
            out.append(hint)
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
    def _fork_points(target: str | None, branches: Iterable[str]) -> frozenset[str]:
        """Return the full SHA where each local branch leaves the default branch.

        Args:
            target: The default branch ref, or None if there is none.
            branches: Local branch names.
        """
        if not target:
            return frozenset()

        points: set[str] = set()
        for branch in branches:
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
        if self.cap or not fork_points:
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
