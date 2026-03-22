"""Log subcommand for gx."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import typer
from rich.console import Group
from rich.table import Table
from rich.text import Text

from gx.lib.console import console, error, set_verbosity
from gx.lib.git import check_git_repo, git, set_dry_run
from gx.lib.options import DRY_RUN_OPTION, VERBOSE_OPTION

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

app = typer.Typer(rich_markup_mode="rich", context_settings=CONTEXT_SETTINGS)

_RECORD_SEP = "\x01"
_FIELD_SEP = "\x00"
_DEFAULT_COUNT = 15
_BODY_FIELD_INDEX = 5
_KNOWN_REMOTE_NAMES = {"origin", "upstream", "fork"}

COUNT_OPTION: int = typer.Option(
    _DEFAULT_COUNT,
    "--count",
    "-c",
    help="Number of commits to show.",
)
FULL_OPTION: bool = typer.Option(
    False,  # noqa: FBT003
    "--full",
    help="Show full commit bodies.",
)
GRAPH_OPTION: bool = typer.Option(
    False,  # noqa: FBT003
    "--graph",
    "-g",
    help="Show branch graph.",
)

_DEFAULT_FORMAT = "%x01%h%x00%ar%x00%s%x00%an%x00%D"
_FULL_FORMAT = "%x01%h%x00%ar%x00%s%x00%an%x00%D%x00%b"
_GRAPH_FORMAT = "%h %ar <%an> %s%d"

_SHA_RE = re.compile(r"([a-f0-9]{7,})")
_TIME_RE = re.compile(r"(\d+ \w+ ago)")
_AUTHOR_RE = re.compile(r"<([^>]+)>")
_REFS_RE = re.compile(r"\(([^)]+)\)")
_CONNECTOR_RE = re.compile(r"^[\s*/|\\]+$")


@dataclass(frozen=True)
class LogEntry:
    """A single parsed commit from git log output."""

    sha: str
    relative_time: str
    subject: str
    author: str
    refs: str
    body: str


@dataclass
class RefsData:
    """Grouped ref decorations extracted from log entries."""

    head_branch: str | None = None
    branches: list[str] = field(default_factory=list)
    remotes: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


def parse_log_entries(raw: str, *, has_body: bool) -> list[LogEntry]:
    """Parse raw git log output into LogEntry objects.

    Split on SOH byte (record separator) first, then on null byte (field separator)
    within each record. This handles multi-line commit bodies safely.

    Args:
        raw: Raw stdout from git log with SOH/null-delimited format.
        has_body: Whether the format includes the body field (%b).

    Returns:
        List of LogEntry objects.
    """
    if not raw.strip():
        return []

    records = raw.split(_RECORD_SEP)
    entries: list[LogEntry] = []

    for record in records:
        if not record.strip():
            continue

        fields = record.split(_FIELD_SEP)
        expected_fields = 6 if has_body else 5

        if len(fields) < expected_fields:
            continue

        body = (
            fields[_BODY_FIELD_INDEX].strip()
            if has_body and len(fields) > _BODY_FIELD_INDEX
            else ""
        )

        entries.append(
            LogEntry(
                sha=fields[0].strip(),
                relative_time=fields[1].strip(),
                subject=fields[2].strip(),
                author=fields[3].strip(),
                refs=fields[4].strip(),
                body=body,
            )
        )

    return entries


def parse_refs(entries: list[LogEntry]) -> RefsData:
    """Extract and group ref decorations from log entries.

    Scans all entries for ref strings and groups them into HEAD branch,
    other local branches, remote refs, and tags.

    Args:
        entries: Parsed log entries to scan for refs.

    Returns:
        RefsData with head_branch, branches, remotes, and tags populated.
    """
    result = RefsData()

    for entry in entries:
        if not entry.refs:
            continue
        for raw_ref in entry.refs.split(", "):
            ref = raw_ref.strip()
            if ref.startswith("HEAD -> "):
                result.head_branch = ref.removeprefix("HEAD -> ")
            elif ref.startswith("tag: "):
                result.tags.append(ref.removeprefix("tag: "))
            elif ref == "HEAD":
                pass
            else:
                # Remote refs always start with a configured remote name followed by /.
                # Local branches with slashes (e.g. feat/test) are not remote refs.
                # We detect remotes by checking if the ref starts with a known remote
                # prefix pattern: a segment without slashes followed by a slash.
                parts = ref.split("/", 1)
                if len(parts) == 2 and "/" not in parts[0] and parts[0] in _KNOWN_REMOTE_NAMES:  # noqa: PLR2004
                    result.remotes.append(ref)
                else:
                    result.branches.append(ref)

    return result


def render_ref_banner(refs: RefsData) -> Text | None:
    """Render the ref context banner as a Rich Text object.

    Shows HEAD branch with ← HEAD annotation, other branches, remote refs (dim),
    and tags (bold yellow).

    Args:
        refs: Grouped ref data from parse_refs().

    Returns:
        A styled Rich Text line, or None if no refs to display.
    """
    head = refs.head_branch
    branches = refs.branches
    remotes = refs.remotes
    tags = refs.tags

    if not head and not branches and not remotes and not tags:
        return None

    text = Text("  ")
    if head:
        text.append(head, style="branch_current")
        text.append(" ← HEAD", style="branch_current")

    for branch in branches:
        text.append("  ")
        text.append(branch, style="branch_current")

    for remote in remotes:
        text.append("  ")
        text.append(remote, style="branch_target")

    for tag in tags:
        text.append("  ")
        text.append(tag, style="log_ref_tag")

    return text


def render_log_grid(entries: list[LogEntry], *, show_body: bool) -> Group | None:
    """Render log entries as an invisible Rich grid with optional commit bodies.

    Uses a Rich Table with no visible chrome for column alignment. When show_body
    is True, commit bodies are rendered as indented dim text below each row.

    Args:
        entries: Parsed log entries to render.
        show_body: Whether to include commit bodies below rows.

    Returns:
        A Rich Group containing the table and body text, or None if entries is empty.
    """
    if not entries:
        return None

    if not show_body:
        table = Table(
            show_header=False,
            show_edge=False,
            box=None,
            pad_edge=False,
            padding=(0, 2),
        )
        table.add_column(style="log_sha", no_wrap=True, width=7)
        table.add_column(style="log_time", no_wrap=True)
        table.add_column(no_wrap=False, ratio=1)
        table.add_column(style="log_author", no_wrap=True, justify="right")

        for entry in entries:
            table.add_row(entry.sha, entry.relative_time, entry.subject, entry.author)

        return Group(table)

    # With bodies: build individual one-row tables + body text for spacing control
    renderables: list[Table | Text] = []
    for entry in entries:
        row_table = Table(
            show_header=False,
            show_edge=False,
            box=None,
            pad_edge=False,
            padding=(0, 2),
        )
        row_table.add_column(style="log_sha", no_wrap=True, width=7)
        row_table.add_column(style="log_time", no_wrap=True)
        row_table.add_column(no_wrap=False, ratio=1)
        row_table.add_column(style="log_author", no_wrap=True, justify="right")
        row_table.add_row(entry.sha, entry.relative_time, entry.subject, entry.author)
        renderables.append(row_table)

        if entry.body:
            body_text = Text(f"  {entry.body}", style="log_body")
            renderables.append(body_text)
            renderables.append(Text(""))

    return Group(*renderables)


def colorize_graph_line(line: str) -> Text:
    """Apply Rich styling to a single git log --graph output line.

    Commit lines get per-field coloring (SHA, time, author, refs).
    Connector-only lines (just graph characters) are styled dim.

    Args:
        line: A single line from `git log --graph` output.

    Returns:
        A styled Rich Text object representing the line.
    """
    if not line:
        return Text("")

    if _CONNECTOR_RE.match(line):
        return Text(line, style="log_graph")

    text = Text()
    remaining = line

    sha_match = _SHA_RE.search(remaining)
    if not sha_match:
        return Text(line)

    # Everything before SHA (graph chars)
    text.append(remaining[: sha_match.start()])
    text.append(sha_match.group(1), style="log_sha")
    remaining = remaining[sha_match.end() :]

    time_match = _TIME_RE.search(remaining)
    if time_match:
        text.append(remaining[: time_match.start()])
        text.append(time_match.group(1), style="log_time")
        remaining = remaining[time_match.end() :]

    author_match = _AUTHOR_RE.search(remaining)
    if author_match:
        text.append(remaining[: author_match.start()])
        text.append(author_match.group(1), style="log_author")
        remaining = remaining[author_match.end() :]

    refs_match = _REFS_RE.search(remaining)
    if refs_match:
        text.append(remaining[: refs_match.start()])
        text.append("(", style="log_graph")
        text.append(refs_match.group(1), style="branch_current")
        text.append(")", style="log_graph")
        remaining = remaining[refs_match.end() :]

    # Remainder is the subject line
    if remaining:
        text.append(remaining)

    return text


def _run_grid_mode(count: int, *, full: bool) -> None:
    """Execute grid rendering mode (default or --full)."""
    fmt = _FULL_FORMAT if full else _DEFAULT_FORMAT
    result = git("log", f"-n{count}", f"--format={fmt}")
    result.raise_on_error()

    entries = parse_log_entries(result.stdout, has_body=full)
    if not entries:
        console.print("No commits found.", style="warning")
        return

    refs = parse_refs(entries)
    banner = render_ref_banner(refs)
    if banner:
        console.print(banner)
        console.print()

    grid = render_log_grid(entries, show_body=full)
    if grid:
        console.print(grid)


def _run_graph_mode(count: int) -> None:
    """Execute graph passthrough rendering mode."""
    result = git("log", "--graph", f"-n{count}", f"--format={_GRAPH_FORMAT}")
    result.raise_on_error()

    if not result.stdout:
        console.print("No commits found.", style="warning")
        return

    for line in result.stdout.splitlines():
        styled = colorize_graph_line(line)
        console.print(styled)


@app.callback(invoke_without_command=True)
def log(
    ctx: typer.Context,  # noqa: ARG001
    count: int = COUNT_OPTION,
    full: bool = FULL_OPTION,  # noqa: FBT001
    graph: bool = GRAPH_OPTION,  # noqa: FBT001
    verbose: int = VERBOSE_OPTION,
    dry_run: bool = DRY_RUN_OPTION,  # noqa: FBT001
) -> None:
    """Show a pretty commit log.

    Displays a scannable list of recent commits with color-coded SHA, relative time, subject, and author. A ref banner at the top shows where HEAD, branches, and tags point.

    [bold]Modes:[/bold]

    - Default: clean grid with aligned columns
    - --full: includes commit bodies below each entry
    - --graph: branch/merge graph with colorized output

    [bold]Examples:[/bold]

      gx log                Show last 15 commits
      gx log -c 30          Show last 30 commits
      gx log --full         Include commit bodies
      gx log --graph        Show branch graph
    """
    if verbose:
        set_verbosity(verbose)
    if dry_run:
        set_dry_run(enabled=True)
    check_git_repo()

    if full and graph:
        error("--full and --graph are mutually exclusive.")
        raise typer.Exit(1)

    if graph:
        _run_graph_mode(count)
    else:
        _run_grid_mode(count, full=full)
