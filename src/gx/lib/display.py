"""Shared display helpers for rendering Rich panels and grids.

Provides reusable renderers for branch status panels, working tree status,
and key-value grids used across gx commands (status, info).

Usage in commands:
    from gx.lib.display import kv_grid, render_branch_panel, render_working_tree_panel
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

if TYPE_CHECKING:
    from gx.lib.branch import BranchRow

_COMMIT_TYPES = "feat|fix|refactor|perf|build|ci|docs|style|test|chore|bump"


def commit_text(line: str) -> Text:
    """Color SHAs, conventional-commit types/scopes, and PR refs in a commit line."""
    text = Text(line)
    text.highlight_regex(r"\b[0-9a-f]{7,12}\b", "yellow")
    text.highlight_regex(rf"(?:{_COMMIT_TYPES})(?:\([^)]+\))?:", "cyan")
    text.highlight_regex(r"\(#\d+\)", "magenta")
    return text


def kv_grid(rows: list[tuple[str | Text, str | Text]]) -> Table:
    """Build a right-aligned label / left-aligned value grid for info panels.

    Args:
        rows: Pairs of (label, value) where value may be a plain string or
            a pre-styled Rich Text object.

    Returns:
        A Rich Table configured as a two-column grid.
    """
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim", justify="right")
    grid.add_column(style="default")
    for label, value in rows:
        grid.add_row(label, value)
    return grid


def _tracking_ref_text(row: BranchRow) -> Text:
    """Return the tracking ref as styled Text, or empty Text if none.

    Args:
        row: The branch row containing the tracking_ref field.
    """
    text = Text()
    if row.tracking_ref:
        text.append(row.tracking_ref, style="cyan")
    return text


def _ahead_behind_text(row: BranchRow) -> Text:
    """Return ahead/behind arrows as styled Text.

    Renders ↑N for commits ahead and ↓N for commits behind relative to the
    tracking remote ref. Returns empty Text when both are zero or absent.

    Args:
        row: The branch row with ahead_remote and behind_remote fields.
    """
    text = Text()
    ahead = row.ahead_remote or 0
    behind = row.behind_remote or 0

    if ahead:
        text.append(f"↑{ahead}", style="green")
    if ahead and behind:
        text.append(" ")
    if behind:
        text.append(f"↓{behind}", style="red")

    return text


def _file_counts_text(row: BranchRow) -> Text:
    """Return file count sigils as styled Text.

    Renders +N ~N !N ?N for staged, modified, unmerged, and untracked counts.
    Only includes non-zero counts.

    Args:
        row: The branch row with staged, modified, unmerged, untracked fields.
    """
    text = Text()
    parts: list[tuple[str, int, str]] = [
        ("+", row.staged, "green"),
        ("~", row.modified, "red"),
        ("!", row.unmerged, "bold yellow"),
        ("?", row.untracked, "cyan"),
    ]
    first = True
    for sigil, count, style in parts:
        if count:
            if not first:
                text.append(" ")
            text.append(f"{sigil}{count}", style=style)
            first = False
    return text


def render_branch_panel(rows: list[BranchRow]) -> Panel | None:
    """Render branch rows as a Rich Panel with a columnar grid layout.

    Each branch occupies one row showing: current-branch marker, branch name,
    tracking ref, ahead/behind arrows, file-count sigils, and stash count.
    Returns None when the row list is empty.

    Args:
        rows: The collected BranchRow data to render.

    Returns:
        A Rich Panel ready for console output, or None if rows is empty.
    """
    if not rows:
        return None

    grid = Table.grid(padding=(0, 1))
    grid.add_column()  # marker + branch name
    grid.add_column()  # tracking ref
    grid.add_column()  # ahead/behind
    grid.add_column()  # file counts
    grid.add_column()  # stash

    for row in rows:
        name_text = Text()
        if row.is_current:
            name_text.append("* ", style="bold default")
        else:
            name_text.append("  ")
        name_text.append(row.branch, style="bold default" if row.is_current else "default")
        if row.is_worktree:
            name_text.append(" [wt]", style="dim")

        stash_text = Text()
        if row.stashes:
            stash_text.append(f"≡{row.stashes}", style="cyan")

        grid.add_row(
            name_text,
            _tracking_ref_text(row),
            _ahead_behind_text(row),
            _file_counts_text(row),
            stash_text,
        )

    return Panel(grid, title="Branches", border_style="dim")


def render_working_tree_panel(
    *,
    staged: int,
    modified: int,
    unmerged: int,
    untracked: int,
) -> Panel:
    """Render condensed working tree file status as a Rich Panel.

    Shows counts for each category when non-zero, or a clean indicator when
    all counts are zero.

    Args:
        staged: Number of staged files.
        modified: Number of modified (unstaged) files.
        unmerged: Number of files with merge conflicts.
        untracked: Number of untracked files.

    Returns:
        A Rich Panel showing working tree status.
    """
    text = Text()
    total = staged + modified + unmerged + untracked

    if total == 0:
        text.append("✓ Clean", style="green")
    else:
        parts: list[tuple[str, int, str]] = [
            (f"+{staged} staged", staged, "green"),
            (f"~{modified} modified", modified, "red"),
            (f"!{unmerged} unmerged", unmerged, "bold yellow"),
            (f"?{untracked} untracked", untracked, "cyan"),
        ]
        first = True
        for label, count, style in parts:
            if count:
                if not first:
                    text.append("  ")
                text.append(label, style=style)
                first = False

    return Panel(text, title="Working Tree", border_style="dim")
