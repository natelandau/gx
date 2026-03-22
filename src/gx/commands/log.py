"""Log subcommand for gx."""

from __future__ import annotations

from dataclasses import dataclass, field

import typer
from rich.text import Text

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

app = typer.Typer(rich_markup_mode="rich", context_settings=CONTEXT_SETTINGS)

_RECORD_SEP = "\x01"
_FIELD_SEP = "\x00"
_DEFAULT_COUNT = 15
_BODY_FIELD_INDEX = 5
_KNOWN_REMOTE_NAMES = {"origin", "upstream", "fork"}


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
