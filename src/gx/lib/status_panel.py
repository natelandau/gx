"""Reusable status file-tree panel from git porcelain output.

Provides StatusPanel which parses `git status --porcelain` output and renders
a Rich Tree grouped by directory, shared by the status command.

Usage:
    from gx.lib.status_panel import StatusPanel

    panel = StatusPanel(porcelain_output, "my-repo").render()
    if panel:
        console.print(panel)
"""

from __future__ import annotations

from rich.text import Text
from rich.tree import Tree

DOT_CHAR = "\u00b7"

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
    text.append("\u2713", style="info.marker")
    text.append(f"  {message}", style="info.message")
    return text


class StatusPanel:
    """Parse git porcelain output and render a file-tree or clean-tree message.

    Encapsulates the parse-and-render pipeline for `git status --porcelain`
    output, producing either a Rich Tree of changed files or a clean-tree
    indicator.

    Args:
        porcelain_output: Raw stdout from `git status --porcelain`.
        repo_name: Repository directory name for the tree root label.
    """

    def __init__(self, porcelain_output: str, repo_name: str) -> None:
        self.porcelain_output = porcelain_output
        self.repo_name = repo_name

    def render(self) -> Tree | Text | None:
        """Return a file tree, a clean-tree message, or None.

        Returns:
            A Rich Tree when there are changed files, a styled Text saying
            "Working tree clean" when there are none, or None on empty input.
        """
        if not self.porcelain_output:
            return _info_text("Working tree clean")
        entries = _parse_porcelain(self.porcelain_output)
        return _build_file_tree(entries, self.repo_name)
