"""Status subcommand for gx."""

from __future__ import annotations

import typer
from rich.panel import Panel
from rich.text import Text
from rich.tree import Tree

from gx.lib.branch import collect_branch_data, current_branch
from gx.lib.console import console, error
from gx.lib.display import render_branch_panel
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
    branch_panel: Panel | None,
) -> None:
    """Print the assembled status panels to the console.

    Args:
        file_panel: Built Rich Tree or clean-tree Text to display in a panel, or None.
        branch_panel: Rendered branch panel, or None.
    """
    if file_panel is not None:
        branch_name = current_branch() or git("rev-parse", "--short", "HEAD").stdout
        console.print(Panel(file_panel, title=branch_name, border_style="dim"))

    if branch_panel is not None:
        if file_panel is not None:
            console.print()
        console.print(branch_panel)


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
    """Show file changes and branch status for the current repository.

    Displays a two-panel view: a color-coded file tree for the current branch and a branch panel with ahead/behind counts, file metrics, and stash indicators.

    [bold]Panels:[/bold]

    - [bold]File tree[/bold] — changed files on the current branch, with git status codes
    - [bold]Branches[/bold] — all active branches with ahead/behind, file counts, stashes

    [bold]Examples:[/bold]

      gx status              Both panels
      gx status -F           File tree only
      gx status -b           Branch panel only
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

    branch_panel = None
    if show_branches:
        rows = collect_branch_data(show_all=show_all, current_porcelain=porcelain_output)
        branch_panel = render_branch_panel(rows)

    if file_panel is None and branch_panel is None:
        console.print(Panel(_info_text("Everything clean"), border_style="dim"))
        return

    _print_status_output(file_panel, branch_panel)
