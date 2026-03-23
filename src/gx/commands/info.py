"""Info subcommand for gx — repository metadata dashboard."""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer
from rich.console import Group
from rich.table import Table

if TYPE_CHECKING:
    from rich.panel import Panel

from gx.lib.branch import collect_branch_data, count_file_statuses, stash_counts
from gx.lib.console import console
from gx.lib.display import render_branch_panel, render_working_tree_panel
from gx.lib.git import check_git_repo, git, repo_root
from gx.lib.info_panels import GitHubPanel, RepoPanel, StashPanel, WorktreePanel, resolve_remote
from gx.lib.log_panel import LogPanel

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}
WIDE_THRESHOLD = 100

app = typer.Typer(rich_markup_mode="rich", context_settings=CONTEXT_SETTINGS)


def _compose_dashboard(
    *,
    repo: Panel | None = None,
    github: Panel | None = None,
    branches: Panel | None = None,
    working_tree: Panel | None = None,
    stashes: Panel | None = None,
    log: Panel | None = None,
    worktrees: Panel | None = None,
) -> None:
    """Arrange panels in a responsive grid and print to the console.

    Use a wide two/three-column grid layout when the terminal is at least
    WIDE_THRESHOLD characters wide, otherwise stack all panels vertically.
    """
    wide = console.width >= WIDE_THRESHOLD

    if wide:
        parts: list[Table | Panel] = []

        if github:
            row1 = Table.grid(padding=(0, 1))
            row1.add_column(ratio=1)
            row1.add_column(ratio=1)
            row1.add_row(repo, github)
            parts.append(row1)
        elif repo:
            parts.append(repo)

        if branches:
            parts.append(branches)

        row3_panels = [p for p in (working_tree, stashes, worktrees) if p is not None]
        if row3_panels:
            row3 = Table.grid(padding=(0, 1))
            for _ in row3_panels:
                row3.add_column(ratio=1)
            row3.add_row(*row3_panels)
            parts.append(row3)

        if log:
            parts.append(log)

        if parts:
            console.print(Group(*parts))
    else:
        all_panels = [repo, github, branches, working_tree, stashes, log, worktrees]
        visible = [p for p in all_panels if p is not None]
        if visible:
            console.print(Group(*visible))


@app.callback(invoke_without_command=True)
def info(
    ctx: typer.Context,  # noqa: ARG001
) -> None:
    """Show a rich dashboard for the current repository.

    Displays repository metadata, branch status, working tree state,
    recent commits, and optionally GitHub info and worktree listings.

    [bold]Examples:[/bold]

      gx info                Full dashboard
      gx info -v             Dashboard with debug output
      gx                     Same as gx info (default command)
    """
    check_git_repo()

    root = repo_root()
    remote_name, remote_url = resolve_remote()

    repo_p = RepoPanel(root, remote_name, remote_url).render()
    github_p = GitHubPanel(remote_url).render()

    stash_data = stash_counts()
    porcelain_result = git("status", "--porcelain")
    porcelain = porcelain_result.stdout if porcelain_result.success else ""
    staged, modified, unmerged, untracked = count_file_statuses(porcelain)

    branch_rows = collect_branch_data(
        show_all=True,
        current_porcelain=porcelain,
        stashes=stash_data,
    )

    _compose_dashboard(
        repo=repo_p,
        github=github_p,
        branches=render_branch_panel(branch_rows),
        working_tree=render_working_tree_panel(
            staged=staged,
            modified=modified,
            unmerged=unmerged,
            untracked=untracked,
        ),
        stashes=StashPanel(stash_data).render(),
        log=LogPanel(count=5).render(),
        worktrees=WorktreePanel(root).render(),
    )
