"""Log subcommand for gx."""

from __future__ import annotations

import typer
from nclutils import pp

from gx.lib.git import check_git_repo, set_dry_run
from gx.lib.log_graph import LogGraph
from gx.lib.log_panel import LogPanel
from gx.lib.options import DRY_RUN_OPTION, VERBOSE_OPTION

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

app = typer.Typer(rich_markup_mode="rich", context_settings=CONTEXT_SETTINGS)


COUNT_OPTION: int = typer.Option(
    15,
    "--count",
    "-c",
    help="Number of commits to show.",
)
FULL_OPTION: bool = typer.Option(
    False,  # noqa: FBT003
    "--full",
    help="Show full commit bodies, or every commit with --graph.",
)
GRAPH_OPTION: bool = typer.Option(
    False,  # noqa: FBT003
    "--graph",
    "-g",
    help="Show branch graph.",
)


def _run_graph_mode(count: int, *, fold: bool) -> None:
    """Execute graph rendering mode."""
    lines = LogGraph(count=count, fold=fold).render(width=pp.console().width)
    if not lines:
        pp.warning("No commits found.")
        return

    # Wrapped lines would spill into the graph lanes, so long ones are cut instead.
    for line in lines:
        pp.console().print(line, no_wrap=True, overflow="ellipsis", crop=True)


@app.callback(invoke_without_command=True)
def log(
    ctx: typer.Context,  # noqa: ARG001
    count: int = COUNT_OPTION,
    full: bool = FULL_OPTION,  # noqa: FBT001
    graph: bool = GRAPH_OPTION,  # noqa: FBT001
    verbose: int = VERBOSE_OPTION,
    dry_run: bool = DRY_RUN_OPTION,  # noqa: FBT001
) -> None:
    """Show a pretty commit log.

    Displays a scannable list of recent commits with color-coded SHA, relative time, subject, and author. Inline badges show where branches and tags point.

    [bold]Modes:[/bold]

    - Default: clean grid with aligned columns inside a panel
    - --full: includes commit bodies below each entry
    - --graph: branch graph reaching back to where each local branch forks, with long runs of commits folded, each branch colored, and a color legend below
    - --graph --full: branch graph with every commit shown

    [bold]Examples:[/bold]

      gx log                Show last 15 commits
      gx log -c 30          Show last 30 commits
      gx log --full         Include commit bodies
      gx log --graph        Show graph of all branches
      gx log --graph --full Show graph without folding commits
    """
    if verbose:
        pp.configure(verbosity=verbose)
    if dry_run:
        set_dry_run(enabled=True)
    check_git_repo()

    if graph:
        _run_graph_mode(count, fold=not full)
    else:
        panel = LogPanel(count=count, title="Log", show_body=full).render()
        if panel:
            pp.console().print(panel)
        else:
            pp.warning("No commits found.")
