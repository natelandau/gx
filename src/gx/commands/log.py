"""Log subcommand for gx."""

from __future__ import annotations

from dataclasses import dataclass

import typer

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

app = typer.Typer(rich_markup_mode="rich", context_settings=CONTEXT_SETTINGS)

_RECORD_SEP = "\x01"
_FIELD_SEP = "\x00"
_DEFAULT_COUNT = 15
_BODY_FIELD_INDEX = 5


@dataclass(frozen=True)
class LogEntry:
    """A single parsed commit from git log output."""

    sha: str
    relative_time: str
    subject: str
    author: str
    refs: str
    body: str


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
