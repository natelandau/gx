"""Reusable log panel with inline branch/tag badge decorations.

Provides LogEntry (parsed commit data) and LogPanel (configurable Rich Panel
renderer) shared by the log and info commands.

Usage:
    from gx.lib.log_panel import LogPanel

    panel = LogPanel(count=15, title="Log").render()
    if panel:
        console.print(panel)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from gx.constants import KNOWN_REMOTE_NAMES
from gx.lib.git import git

_RECORD_SEP = "\x01"
_FIELD_SEP = "\x00"
_DEFAULT_FORMAT = "%x01%h%x00%ar%x00%s%x00%an%x00%D"
_FULL_FORMAT = "%x01%h%x00%ar%x00%s%x00%an%x00%D%x00%b"
_REMOTE_REF_PARTS = 2


@dataclass(frozen=True)
class LogEntry:
    """A single parsed commit with per-commit ref decorations."""

    sha: str
    relative_time: str
    subject: str
    author: str
    branches: tuple[str, ...] = field(default_factory=tuple)
    tags: tuple[str, ...] = field(default_factory=tuple)
    body: str = ""


def _make_table() -> Table:
    """Create an invisible Rich Table for log column alignment."""
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
    return table


def _render_refs(entry: LogEntry) -> Text:
    """Build inline ref badge Text for a single commit."""
    refs = Text()
    items: list[tuple[str, str]] = [(f" {b} ", "ref.branch") for b in entry.branches] + [
        (f" \U0001f3f7 {t} ", "ref.tag") for t in entry.tags
    ]
    for i, (label, style) in enumerate(items):
        refs.append(label, style=style)
        if i < len(items) - 1:
            refs.append(" ")
    return refs


def _add_row(table: Table, entry: LogEntry) -> None:
    """Add a single commit row with inline ref badges to the table."""
    subject_col = Text()
    if entry.branches or entry.tags:
        subject_col.append_text(_render_refs(entry))
        subject_col.append(" ")
    subject_col.append(entry.subject)
    table.add_row(entry.sha, entry.relative_time, subject_col, entry.author)


def _parse_refs(raw_refs: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Parse a raw ref decoration string into branches and tags tuples.

    Filters out HEAD, HEAD -> X, and remote refs.

    Args:
        raw_refs: The raw %D output for a single commit.

    Returns:
        A (branches, tags) tuple.
    """
    branches: list[str] = []
    tags: list[str] = []

    if not raw_refs.strip():
        return (), ()

    for raw_ref in raw_refs.split(", "):
        ref = raw_ref.strip()
        if ref.startswith("HEAD -> "):
            branches.append(ref.removeprefix("HEAD -> "))
        elif ref.startswith("tag: "):
            tags.append(ref.removeprefix("tag: "))
        elif ref != "HEAD":
            parts = ref.split("/", 1)
            is_remote = (
                len(parts) == _REMOTE_REF_PARTS
                and "/" not in parts[0]
                and parts[0] in KNOWN_REMOTE_NAMES
            )
            if not is_remote:
                branches.append(ref)

    return tuple(branches), tuple(tags)


def _parse_entries(raw: str, *, has_body: bool) -> list[LogEntry]:
    """Parse raw git log output into LogEntry objects.

    Split on SOH byte (record separator), then on null byte (field separator).

    Args:
        raw: Raw stdout from git log with SOH/null-delimited format.
        has_body: Whether the format includes the body field (%b).

    Returns:
        List of LogEntry objects with per-commit refs parsed.
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

        raw_refs = fields[4].strip()
        branches, tags = _parse_refs(raw_refs)
        body = fields[5].strip() if has_body else ""

        entries.append(
            LogEntry(
                sha=fields[0].strip(),
                relative_time=fields[1].strip(),
                subject=fields[2].strip(),
                author=fields[3].strip(),
                branches=branches,
                tags=tags,
                body=body,
            )
        )

    return entries


class LogPanel:
    """Configurable git log panel with inline branch/tag decorations.

    Fetch, parse, and render recent commits as a Rich Panel. Branch names
    render as reverse bold magenta badges; tags render as reverse bold cyan
    badges with a 🏷 icon.

    Args:
        count: Number of commits to show.
        title: Panel title text.
        show_body: Whether to include commit bodies below each row.
    """

    def __init__(
        self,
        count: int = 15,
        title: str = "Recent Commits",
        *,
        show_body: bool = False,
    ) -> None:
        self.count = count
        self.title = title
        self.show_body = show_body

    def render(self) -> Panel | None:
        """Fetch log data from git and return a styled Rich Panel.

        Returns:
            A Rich Panel with inline ref badges, or None if no commits found
            or git fails.
        """
        fmt = _FULL_FORMAT if self.show_body else _DEFAULT_FORMAT
        result = git("log", f"-n{self.count}", f"--format={fmt}")
        if not result.success or not result.stdout:
            return None

        entries = _parse_entries(result.stdout, has_body=self.show_body)
        if not entries:
            return None

        return self._build_panel(entries)

    def _build_panel(self, entries: list[LogEntry]) -> Panel:
        """Build the Rich Panel from parsed log entries."""
        if not self.show_body:
            table = _make_table()
            for entry in entries:
                _add_row(table, entry)
            return Panel(table, title=self.title, border_style="dim")

        renderables: list[Table | Text] = []
        for entry in entries:
            row_table = _make_table()
            _add_row(row_table, entry)
            renderables.append(row_table)
            if entry.body:
                renderables.append(Text(f"  {entry.body}", style="log_body"))
                renderables.append(Text(""))
        return Panel(Group(*renderables), title=self.title, border_style="dim")
