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

from nclutils.git import default_branch as remote_default_branch
from nclutils.git import primary_remote
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from gx.constants import KNOWN_REMOTE_NAMES
from gx.lib.git import git
from gx.lib.github import is_github_remote

_RECORD_SEP = "\x01"
_FIELD_SEP = "\x00"
_DEFAULT_FORMAT = "%x01%h%x00%ar%x00%s%x00%an%x00%D"
_FULL_FORMAT = "%x01%h%x00%ar%x00%s%x00%an%x00%D%x00%b"
_REMOTE_REF_PARTS = 2

# Host-aware Nerd Font glyphs for the remote-head badge.
_GITHUB_GLYPH = ""
_GITLAB_GLYPH = ""
_GIT_GLYPH = ""


@dataclass(frozen=True)
class LogEntry:
    """A single parsed commit with per-commit ref decorations."""

    sha: str
    relative_time: str
    subject: str
    author: str
    branches: tuple[str, ...] = field(default_factory=tuple)
    tags: tuple[str, ...] = field(default_factory=tuple)
    remote_branches: tuple[str, ...] = field(default_factory=tuple)
    body: str = ""
    is_head: bool = False
    is_remote_head: bool = False


@dataclass(frozen=True)
class _RemoteBadges:
    """Per-render config deciding how remote branches are badged.

    Resolved once per render so the per-commit loop stays free of git calls.

    Attributes:
        labeled: True when 2+ remote branches exist in the log, switching every
            remote badge from icon-only to a "[icon] remote/branch" label.
        glyphs: Map of remote name to host-aware glyph, used in labeled mode.
        default_glyph: Glyph for the remote default branch, used in icon-only mode.
    """

    labeled: bool
    glyphs: dict[str, str]
    default_glyph: str


def _remote_glyph(url: str) -> str:
    """Pick a host-aware Nerd Font glyph for a remote URL.

    Lets the remote-head badge echo where the code actually lives (GitHub,
    GitLab, or a generic git host) instead of a one-size-fits-all icon.

    Args:
        url: The remote URL to classify.
    """
    if is_github_remote(url):
        return _GITHUB_GLYPH
    if "gitlab" in url:
        return _GITLAB_GLYPH
    return _GIT_GLYPH


def _remote_head_ref() -> tuple[str | None, str]:
    """Resolve the remote default branch ref and its host glyph.

    Resolved once per render so the per-commit loop stays free of git calls.
    The branch is resolved against the same remote whose name prefixes the ref,
    so the two never disagree (e.g. a `fork`/`origin` setup) and the ref matches
    the remote-tracking decoration git emits in the log.

    Returns:
        A (ref, glyph) tuple such as ("origin/main", ""). The ref is None when
        no remote is configured or its HEAD is not resolved, in which case no
        badge is drawn rather than guessing a ref that may match nothing.
    """
    remote = primary_remote()
    if remote is None:
        return None, ""

    target = remote_default_branch(remote=remote.name)
    if target is None:
        return None, ""

    return f"{remote.name}/{target}", _remote_glyph(remote.url)


def _remote_glyphs() -> dict[str, str]:
    """Resolve a host-aware glyph for every configured remote.

    Lets each remote/branch label echo where that remote actually lives, so an
    `origin` (GitHub) and an `upstream` (GitLab) get distinct icons in the same
    log. Resolved once per render only when labeled badges are needed.

    Returns:
        A map of remote name to glyph, e.g. {"origin": "", "upstream": ""}.
        Empty when no remotes are configured.
    """
    result = git("remote", "-v")
    if not result.ok or not result.stdout:
        return {}

    # `git remote -v` lines are "<name>\t<url> (fetch|push)" -- one call beats a
    # per-remote `get-url`, and the duplicate fetch/push rows resolve identically.
    glyphs: dict[str, str] = {}
    for line in result.stdout.splitlines():
        name, _, rest = line.partition("\t")
        url = rest.split(maxsplit=1)[0] if rest else ""
        if not name or not url:
            continue
        glyphs[name] = _remote_glyph(url)
    return glyphs


def _make_table() -> Table:
    """Create an invisible Rich Table for log column alignment."""
    table = Table(
        show_header=False,
        show_edge=False,
        box=None,
        pad_edge=False,
        padding=(0, 2),
    )
    table.add_column(style="yellow", no_wrap=True, width=7)
    table.add_column(style="green", no_wrap=True)
    table.add_column(no_wrap=False, ratio=1)
    table.add_column(style="bold blue", no_wrap=True, justify="right")
    return table


def _render_refs(entry: LogEntry, badges: _RemoteBadges) -> Text:
    """Build inline ref badge Text for a single commit.

    Args:
        entry: The commit whose refs to render.
        badges: Per-render config deciding whether remote branches show as
            icon-only (a lone main/master) or "[icon] remote/branch" labels.
    """
    refs = Text()
    items: list[tuple[str, str]] = [(f" {b} ", "reverse bold magenta") for b in entry.branches]
    if badges.labeled:
        for ref in entry.remote_branches:
            glyph = badges.glyphs.get(ref.split("/", 1)[0], _GIT_GLYPH)
            items.append((f" {glyph} {ref} ", "reverse bold blue"))
    elif entry.is_remote_head:
        items.append((f" {badges.default_glyph} ", "reverse bold blue"))
    items += [(f" \U0001f3f7 {t} ", "reverse bold cyan") for t in entry.tags]
    for i, (label, style) in enumerate(items):
        refs.append(label, style=style)
        if i < len(items) - 1:
            refs.append(" ")
    return refs


def _add_row(table: Table, entry: LogEntry, badges: _RemoteBadges, *, dim: bool = False) -> None:
    """Add a single commit row with inline ref badges to the table."""
    style = "dim" if dim else None
    subject_col = Text()
    has_remote_badge = entry.remote_branches if badges.labeled else entry.is_remote_head
    if entry.branches or entry.tags or has_remote_badge:
        subject_col.append_text(_render_refs(entry, badges))
        subject_col.append(" ")
    subject_col.append(entry.subject, style=style)
    table.add_row(
        Text(entry.sha, style=style or "yellow"),
        Text(entry.relative_time, style=style or "green"),
        subject_col,
        Text(entry.author, style=style or "bold"),
    )


def _parse_refs(
    raw_refs: str, remote_default_ref: str | None
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], bool, bool]:
    """Parse a raw ref decoration string into branches, tags, and HEAD flags.

    Filters out HEAD and HEAD -> X. Remote refs are collected separately from
    local branches; the symbolic ``<remote>/HEAD`` alias is dropped since it is
    a pointer to the default, not a branch. A remote ref matching
    ``remote_default_ref`` also flips the remote-head flag so a lone default can
    be badged with an icon.

    Args:
        raw_refs: The raw %D output for a single commit.
        remote_default_ref: The remote default branch ref (e.g. "origin/main"),
            or None when no remote is configured.

    Returns:
        A (branches, tags, remote_branches, is_head, is_remote_head) tuple.
    """
    branches: list[str] = []
    tags: list[str] = []
    remote_branches: list[str] = []
    is_head = False
    is_remote_head = False

    if not raw_refs.strip():
        return (), (), (), False, False

    for raw_ref in raw_refs.split(", "):
        ref = raw_ref.strip()
        if ref.startswith("HEAD -> "):
            branches.append(ref.removeprefix("HEAD -> "))
            is_head = True
        elif ref == "HEAD":
            is_head = True
        elif ref.startswith("tag: "):
            tags.append(ref.removeprefix("tag: "))
        else:
            parts = ref.split("/", 1)
            is_remote = (
                len(parts) == _REMOTE_REF_PARTS
                and "/" not in parts[0]
                and parts[0] in KNOWN_REMOTE_NAMES
            )
            if is_remote:
                if parts[1] == "HEAD":  # symbolic alias of the default, not a branch
                    continue
                remote_branches.append(ref)
                if ref == remote_default_ref:
                    is_remote_head = True
            else:
                branches.append(ref)

    return tuple(branches), tuple(tags), tuple(remote_branches), is_head, is_remote_head


def _parse_entries(
    raw: str, *, has_body: bool, remote_default_ref: str | None = None
) -> list[LogEntry]:
    """Parse raw git log output into LogEntry objects.

    Split on SOH byte (record separator), then on null byte (field separator).

    Args:
        raw: Raw stdout from git log with SOH/null-delimited format.
        has_body: Whether the format includes the body field (%b).
        remote_default_ref: The remote default branch ref (e.g. "origin/main")
            used to flag which commit the remote points to.

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
        branches, tags, remote_branches, is_head, is_remote_head = _parse_refs(
            raw_refs, remote_default_ref
        )
        body = fields[5].strip() if has_body else ""

        entries.append(
            LogEntry(
                sha=fields[0].strip(),
                relative_time=fields[1].strip(),
                subject=fields[2].strip(),
                author=fields[3].strip(),
                branches=branches,
                tags=tags,
                remote_branches=remote_branches,
                body=body,
                is_head=is_head,
                is_remote_head=is_remote_head,
            )
        )

    return entries


class LogPanel:
    """Configurable git log panel with inline branch/tag decorations.

    Fetch, parse, and render recent commits as a Rich Panel. Branch names
    render as reverse bold magenta badges; tags render as reverse bold cyan
    badges with a 🏷 icon. Remote branches render as reverse bold blue badges
    with a host-aware icon (GitHub, GitLab, or git): when the only remote branch
    is the default (main/master) the badge is icon-only, but as soon as a second
    remote branch appears every remote badge gains a "remote/branch" label.

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
        result = git("log", "--all", f"-n{self.count}", f"--format={fmt}")
        if not result.ok or not result.stdout:
            return None

        remote_default_ref, default_glyph = _remote_head_ref()
        entries = _parse_entries(
            result.stdout, has_body=self.show_body, remote_default_ref=remote_default_ref
        )
        if not entries:
            return None

        # A lone main/master stays icon-only; 2+ remote branches switch to labels.
        labeled = sum(len(e.remote_branches) for e in entries) > 1
        badges = _RemoteBadges(
            labeled=labeled,
            glyphs=_remote_glyphs() if labeled else {},
            default_glyph=default_glyph,
        )
        return self._build_panel(entries, badges)

    def _build_panel(self, entries: list[LogEntry], badges: _RemoteBadges) -> Panel:
        """Build the Rich Panel from parsed log entries."""
        head_idx = next(
            (i for i, e in enumerate(entries) if e.is_head),
            0,  # HEAD not in view — nothing dimmed
        )

        if not self.show_body:
            table = _make_table()
            for i, entry in enumerate(entries):
                _add_row(table, entry, badges, dim=i < head_idx)
            return Panel(table, title=self.title, border_style="dim")

        renderables: list[Table | Text] = []
        for i, entry in enumerate(entries):
            dim = i < head_idx
            row_table = _make_table()
            _add_row(row_table, entry, badges, dim=dim)
            if entry.body:
                row_table.add_row("", "", Text(entry.body, style="dim"), "")
                renderables.append(row_table)
                renderables.append(Text(""))
            else:
                renderables.append(row_table)
        return Panel(Group(*renderables), title=self.title, border_style="dim")
