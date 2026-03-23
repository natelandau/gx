"""Status subcommand for gx."""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer
from rich.panel import Panel

from gx.lib.branch import collect_branch_data, current_branch

if TYPE_CHECKING:
    from rich.text import Text
    from rich.tree import Tree
from gx.lib.console import console, error
from gx.lib.display import render_branch_panel
from gx.lib.git import check_git_repo, git, repo_root
from gx.lib.status_panel import StatusPanel, _info_text

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

app = typer.Typer(rich_markup_mode="rich", context_settings=CONTEXT_SETTINGS)


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

    file_panel = None
    if show_files:
        file_panel = StatusPanel(porcelain_output, repo_root().name).render()

    branch_panel = None
    if show_branches:
        rows = collect_branch_data(show_all=show_all, current_porcelain=porcelain_output)
        branch_panel = render_branch_panel(rows)

    if file_panel is None and branch_panel is None:
        console.print(Panel(_info_text("Everything clean"), border_style="dim"))
        return

    _print_status_output(file_panel, branch_panel)
