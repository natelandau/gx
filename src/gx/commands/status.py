"""Status subcommand for gx."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import typer
from rich.panel import Panel
from rich.text import Text
from rich.tree import Tree

if TYPE_CHECKING:
    from pathlib import Path

from gx.lib.branch import (
    ahead_behind,
    all_local_branches,
    current_branch,
    default_branch,
    stash_counts,
    tracking_remote_ref,
)
from gx.lib.console import console, error
from gx.lib.git import check_git_repo, git, repo_root
from gx.lib.worktree import list_worktrees

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

app = typer.Typer(rich_markup_mode="rich", context_settings=CONTEXT_SETTINGS)

DOT_CHAR = "\u00b7"

# Minimum line length for a valid porcelain entry: 2-char code + space + 1-char path
_PORCELAIN_MIN_LINE_LEN = 4

# Minimum characters required to have a valid XY status code pair
_STATUS_CODE_MIN_LEN = 2

LEADER_WIDTH = 50


def _parse_porcelain(output: str) -> list[tuple[str, str]]:
    """Parse `git status --porcelain=v1` output into (status_code, filepath) pairs.

    Handles renames by extracting the destination path from "old -> new" format.

    Args:
        output: Raw stdout from `git status --porcelain`.

    Returns:
        List of (two-char status code, file path) tuples.
    """
    if not output:
        return []

    entries: list[tuple[str, str]] = []
    for line in output.splitlines():
        if len(line) < _PORCELAIN_MIN_LINE_LEN:
            continue
        code = line[:2]
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        entries.append((code, path))

    return entries


def _status_text(code: str) -> Text:
    """Build a colored Text for a two-character status code.

    Index char colored green (staged), work-tree char colored red (unstaged).
    Untracked (??) gets cyan for both chars.
    """
    text = Text()
    index_char = code[0]
    worktree_char = code[1]

    if code == "??":
        text.append(code, style="untracked")
    else:
        if index_char != " ":
            text.append(index_char, style="staged")
        else:
            text.append(index_char)
        if worktree_char != " ":
            text.append(worktree_char, style="unstaged")
        else:
            text.append(worktree_char)

    return text


def _file_entry_text(filename: str, code: str) -> Text:
    """Build a file entry with dot-filled leader and colored status code.

    Args:
        filename: The file basename.
        code: The two-character porcelain status code.
    """
    text = Text()
    text.append(filename)
    dots_needed = max(2, LEADER_WIDTH - len(filename) - 3)
    text.append(f" {DOT_CHAR * dots_needed} ", style="dim")
    text.append_text(_status_text(code))
    return text


def _build_file_tree(entries: list[tuple[str, str]], root_name: str) -> Tree | None:
    """Build a Rich Tree from parsed porcelain entries.

    Groups files by directory, creating nested tree nodes. Directories appear
    as intermediate nodes; files appear as leaves with dot-leader status codes.

    Args:
        entries: List of (status_code, filepath) from _parse_porcelain().
        root_name: Label for the tree root (repo directory name).

    Returns:
        A Rich Tree, or None if entries is empty.
    """
    if not entries:
        return None

    tree = Tree(f"\U0001f333 {root_name}")
    dir_nodes: dict[str, Tree] = {}

    for code, filepath in sorted(entries, key=lambda e: e[1]):
        parts = filepath.split("/")
        filename = parts[-1]
        dirs = parts[:-1]

        parent = tree
        for i, d in enumerate(dirs):
            dir_key = "/".join(dirs[: i + 1])
            if dir_key not in dir_nodes:
                dir_nodes[dir_key] = parent.add(f"{d}/")
            parent = dir_nodes[dir_key]

        parent.add(_file_entry_text(filename, code))

    return tree


@dataclass(frozen=True)
class BranchRow:
    """Data for one branch in the status display."""

    branch: str
    target: str
    ahead_target: int
    behind_target: int
    ahead_remote: int | None
    behind_remote: int | None
    staged: int
    modified: int
    unmerged: int
    untracked: int
    stashes: int
    is_current: bool
    is_worktree: bool
    worktree_path: Path | None

    @property
    def is_active(self) -> bool:
        """Return True if this branch has any non-zero metric."""
        return (
            self.ahead_target != 0
            or self.behind_target != 0
            or (self.ahead_remote is not None and self.ahead_remote != 0)
            or (self.behind_remote is not None and self.behind_remote != 0)
            or self.staged != 0
            or self.modified != 0
            or self.unmerged != 0
            or self.untracked != 0
            or self.stashes != 0
        )


def _count_file_statuses(porcelain_output: str) -> tuple[int, int, int, int]:
    """Count staged, modified, unmerged, and untracked files from porcelain output.

    Parses the two-character XY codes from `git status --porcelain` to bucket
    each file into one of four categories for dashboard display.

    Args:
        porcelain_output: Raw stdout from `git status --porcelain`.

    Returns:
        A (staged, modified, unmerged, untracked) count tuple.
    """
    staged = modified = unmerged = untracked = 0
    if not porcelain_output:
        return (0, 0, 0, 0)
    for line in porcelain_output.splitlines():
        if len(line) < _STATUS_CODE_MIN_LEN:
            continue
        x, y = line[0], line[1]
        if x == "?" and y == "?":
            untracked += 1
        elif x == "U" or y == "U" or (x == "A" and y == "A") or (x == "D" and y == "D"):
            unmerged += 1
        else:
            if x not in (" ", "?"):
                staged += 1
            if y not in (" ", "?"):
                modified += 1
    return (staged, modified, unmerged, untracked)


def _branch_remote_counts(branch: str, target: str) -> tuple[int, int, int | None, int | None]:
    """Return ahead/behind counts for a branch relative to target and remote.

    Args:
        branch: The local branch name.
        target: The default branch to compare against.

    Returns:
        A (ahead_target, behind_target, ahead_remote, behind_remote) tuple,
        where remote values are None when no tracking ref is configured.
    """
    if branch == target:
        at_ahead, at_behind = 0, 0
    else:
        ab = ahead_behind(branch, target)
        at_ahead, at_behind = ab or (0, 0)

    ar_ahead: int | None = None
    ar_behind: int | None = None
    remote_ref = tracking_remote_ref(branch)
    if remote_ref:
        remote_ab = ahead_behind(branch, remote_ref)
        if remote_ab:
            ar_ahead, ar_behind = remote_ab

    return (at_ahead, at_behind, ar_ahead, ar_behind)


def _branch_file_statuses(*, is_current: bool, wt_path: Path | None) -> tuple[int, int, int, int]:
    """Fetch and count working-tree file statuses for a branch.

    Only queries git for branches that are currently checked out (current branch
    or branches with a worktree), since other branches have no working tree state.

    Args:
        is_current: Whether this is the currently active branch.
        wt_path: Path to the branch's worktree, if any.

    Returns:
        A (staged, modified, unmerged, untracked) count tuple.
    """
    if not is_current and not wt_path:
        return (0, 0, 0, 0)

    cwd = None if is_current else wt_path
    result = git("status", "--porcelain", cwd=cwd)
    if result.success:
        return _count_file_statuses(result.stdout)
    return (0, 0, 0, 0)


def _collect_branch_data(
    *, show_all: bool, current_porcelain: str | None = None
) -> list[BranchRow]:
    """Collect metrics for all local branches.

    Gathers ahead/behind counts relative to the default branch and any remote
    tracking ref, plus working-tree file counts for current and worktree branches.
    Inactive branches (all metrics zero) are excluded unless show_all is True.

    Args:
        show_all: When True, include branches with no activity.
        current_porcelain: Pre-fetched porcelain output for the current branch,
            to avoid a redundant git status call when the caller already has it.

    Returns:
        A list of BranchRow instances sorted with the current branch first.
    """
    cur = current_branch()
    target = default_branch()
    branches = all_local_branches()
    stashes = stash_counts()
    worktrees = list_worktrees()

    wt_map: dict[str, Path] = {}
    for wt in worktrees:
        if wt.branch and not wt.is_main:
            wt_map[wt.branch] = wt.path
    for wt in worktrees:
        if wt.is_main and wt.branch:
            wt_map[wt.branch] = wt.path
            break

    rows: list[BranchRow] = []
    for branch in sorted(branches):
        is_current = branch == cur
        at_ahead, at_behind, ar_ahead, ar_behind = _branch_remote_counts(branch, target)

        wt_path = wt_map.get(branch)
        if is_current and current_porcelain is not None:
            staged, modified, unmerged, untracked = _count_file_statuses(current_porcelain)
        else:
            staged, modified, unmerged, untracked = _branch_file_statuses(
                is_current=is_current, wt_path=wt_path
            )

        row = BranchRow(
            branch=branch,
            target=target,
            ahead_target=at_ahead,
            behind_target=at_behind,
            ahead_remote=ar_ahead,
            behind_remote=ar_behind,
            staged=staged,
            modified=modified,
            unmerged=unmerged,
            untracked=untracked,
            stashes=stashes.get(branch, 0),
            is_current=is_current,
            is_worktree=wt_path is not None and not is_current,
            worktree_path=wt_path if not is_current else None,
        )

        if show_all or row.is_active or is_current:
            rows.append(row)

    rows.sort(key=lambda r: (not r.is_current, r.branch))
    return rows


def _ahead_behind_segment(label: str, ahead: int, behind: int) -> Text:
    """Build a labeled ahead/behind Rich Text segment.

    Args:
        label: The metric label (e.g. "target", "remote").
        ahead: Number of commits ahead.
        behind: Number of commits behind.
    """
    seg = Text()
    seg.append(f"{label}: ", style="branch_label")
    if ahead:
        seg.append(f"{ahead}↑", style="ahead")
    if ahead and behind:
        seg.append(" ")
    if behind:
        seg.append(f"{behind}↓", style="behind")
    return seg


def _build_metric_segments(row: BranchRow) -> list[Text]:
    """Build the list of non-zero metric segments for a branch row.

    Each segment is a Rich Text with the label in dim and the value in its
    metric-specific color. Only non-zero metrics are included.

    Args:
        row: The branch data to build metrics for.

    Returns:
        List of Rich Text segments, one per non-zero metric.
    """
    segments: list[Text] = []

    is_default = row.branch == row.target

    if not is_default and (row.ahead_target or row.behind_target):
        segments.append(_ahead_behind_segment("target", row.ahead_target, row.behind_target))

    has_remote_tracking = row.ahead_remote is not None or row.behind_remote is not None
    if has_remote_tracking:
        if row.ahead_remote or row.behind_remote:
            segments.append(
                _ahead_behind_segment("remote", row.ahead_remote or 0, row.behind_remote or 0)
            )
    elif row.is_active:
        seg = Text()
        seg.append("remote: ", style="branch_label")
        seg.append("—", style="branch_label")
        segments.append(seg)

    metric_map: list[tuple[str, int, str]] = [
        ("staged", row.staged, "staged"),
        ("modified", row.modified, "unstaged"),
        ("unmerged", row.unmerged, "warning"),
        ("untracked", row.untracked, "untracked"),
        ("stashes", row.stashes, "untracked"),
    ]
    for label, value, style in metric_map:
        if value:
            seg = Text()
            seg.append(f"{label}: ", style="branch_label")
            seg.append(str(value), style=style)
            segments.append(seg)

    return segments


def _render_branch_status(rows: list[BranchRow]) -> Text | None:
    """Render branch status as a two-line-per-branch text display.

    Each branch gets a name line and an indented metrics line. Only non-zero
    metrics are shown. Clean branches display a checkmark.

    Args:
        rows: The collected BranchRow data to render.

    Returns:
        A Rich Text object ready for console output, or None if rows is empty.
    """
    if not rows:
        return None

    sep = Text("  │  ", style="branch_sep")
    output = Text()

    for i, row in enumerate(rows):
        if row.is_current:
            output.append("► ", style="branch_marker")
        else:
            output.append("  ")
        output.append(row.branch, style="branch_current")

        output.append(f" → {row.target}", style="branch_target")

        if row.is_worktree:
            output.append("  [wt]", style="branch_wt")

        output.append("\n")

        segments = _build_metric_segments(row)
        if segments:
            output.append("    ")
            for j, seg in enumerate(segments):
                if j > 0:
                    output.append_text(sep)
                output.append_text(seg)
        else:
            output.append("    ")
            output.append("✓ clean", style="clean")

        if i < len(rows) - 1:
            output.append("\n\n")

    return output


def _info_text(message: str) -> Text:
    """Build an info-styled Text with checkmark marker."""
    text = Text()
    text.append("✓", style="info.marker")
    text.append(f"  {message}", style="info.message")
    return text


def _render_file_panel(
    porcelain_output: str,
    show_files: bool,  # noqa: FBT001
) -> Tree | Text | None:
    """Build the file tree or clean-tree message from porcelain output.

    Args:
        porcelain_output: Raw stdout from `git status --porcelain`.
        show_files: Whether the file panel was requested.

    Returns:
        A Rich Tree (changed files), Text (clean message), or None (panel not requested).
    """
    if not show_files:
        return None
    if porcelain_output:
        entries = _parse_porcelain(porcelain_output)
        root = repo_root()
        return _build_file_tree(entries, root.name)
    return _info_text("Working tree clean")


def _print_status_output(
    file_panel: Tree | Text | None,
    branch_table: Text | None,
) -> None:
    """Print the assembled status panels to the console.

    Args:
        file_panel: Built Rich Tree or clean-tree Text to display in a panel, or None.
        branch_table: Rendered branch dashboard text, or None.
    """
    if file_panel is not None:
        branch_name = current_branch() or git("rev-parse", "--short", "HEAD").stdout
        console.print(Panel(file_panel, title=branch_name, border_style="dim"))

    if branch_table is not None:
        if file_panel is not None:
            console.print()
        console.print(Panel(branch_table, title="Branch Status", border_style="dim"))


FILES_OPTION: bool = typer.Option(
    False,  # noqa: FBT003
    "--files",
    "-F",
    help="Show only the current branch file tree.",
)
BRANCHES_OPTION: bool = typer.Option(
    False,  # noqa: FBT003
    "--branches",
    "-b",
    help="Show only the branch dashboard table.",
)
ALL_OPTION: bool = typer.Option(
    False,  # noqa: FBT003
    "--all",
    "-a",
    help="Include inactive/clean branches in the dashboard.",
)


@app.callback(invoke_without_command=True)
def status(
    ctx: typer.Context,  # noqa: ARG001
    files: bool = FILES_OPTION,  # noqa: FBT001
    branches: bool = BRANCHES_OPTION,  # noqa: FBT001
    show_all: bool = ALL_OPTION,  # noqa: FBT001
) -> None:
    """Show a rich status dashboard for the current repository.

    Displays a two-panel view: a color-coded file tree for the current branch and a two-line-per-branch status display for all active branches.

    [bold]Panels:[/bold]

    - [bold]File tree[/bold] — changed files on the current branch, with git status codes
    - [bold]Branch status[/bold] — all active branches with ahead/behind counts, file metrics, stashes

    [bold]Examples:[/bold]

      gx status              Full dashboard (both panels)
      gx status -F           File tree only
      gx status -b           Branch table only
      gx status -a           Include inactive branches
    """
    check_git_repo()

    if files and branches:
        error("--files and --branches are mutually exclusive.")
        raise typer.Exit(1)

    show_files = not branches
    show_branches = not files

    porcelain_output = ""
    result = git("status", "--porcelain")
    if result.success:
        porcelain_output = result.stdout

    file_panel = _render_file_panel(porcelain_output, show_files)

    branch_table = None
    if show_branches:
        rows = _collect_branch_data(show_all=show_all, current_porcelain=porcelain_output)
        branch_table = _render_branch_status(rows)

    if file_panel is None and branch_table is None:
        console.print(Panel(_info_text("Everything clean"), border_style="dim"))
        return

    _print_status_output(file_panel, branch_table)
