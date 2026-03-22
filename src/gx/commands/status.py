"""Status subcommand for gx."""

from __future__ import annotations

import typer
from rich.panel import Panel
from rich.text import Text
from rich.tree import Tree

from gx.lib.branch import BranchRow, collect_branch_data, current_branch
from gx.lib.console import console, error
from gx.lib.git import check_git_repo, git, repo_root

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

app = typer.Typer(rich_markup_mode="rich", context_settings=CONTEXT_SETTINGS)

DOT_CHAR = "\u00b7"

# Minimum line length for a valid porcelain entry: 2-char code + space + 1-char path
_PORCELAIN_MIN_LINE_LEN = 4

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
        rows = collect_branch_data(show_all=show_all, current_porcelain=porcelain_output)
        branch_table = _render_branch_status(rows)

    if file_panel is None and branch_table is None:
        console.print(Panel(_info_text("Everything clean"), border_style="dim"))
        return

    _print_status_output(file_panel, branch_table)
