"""Log subcommand for gx."""

from __future__ import annotations

import re

import typer
from rich.text import Text

from gx.lib.console import console, error, set_verbosity
from gx.lib.git import check_git_repo, git, set_dry_run
from gx.lib.log_panel import LogPanel
from gx.lib.options import DRY_RUN_OPTION, VERBOSE_OPTION

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

app = typer.Typer(rich_markup_mode="rich", context_settings=CONTEXT_SETTINGS)

_GRAPH_FORMAT = "%h %ar <%an> %s%d"

_SHA_RE = re.compile(r"([a-f0-9]{7,})")
_TIME_RE = re.compile(r"(\d+ \w+ ago)")
_AUTHOR_RE = re.compile(r"<([^>]+)>")
_REFS_RE = re.compile(r"\(([^)]+)\)")
_CONNECTOR_RE = re.compile(r"^[\s*/|\\]+$")

COUNT_OPTION: int = typer.Option(
    15,
    "--count",
    "-c",
    help="Number of commits to show.",
)
FULL_OPTION: bool = typer.Option(
    False,  # noqa: FBT003
    "--full",
    help="Show full commit bodies.",
)
GRAPH_OPTION: bool = typer.Option(
    False,  # noqa: FBT003
    "--graph",
    "-g",
    help="Show branch graph.",
)


def colorize_graph_line(line: str) -> Text:
    """Apply Rich styling to a single git log --graph output line.

    Commit lines get per-field coloring (SHA, time, author, refs).
    Connector-only lines (just graph characters) are styled dim.

    Args:
        line: A single line from `git log --graph` output.

    Returns:
        A styled Rich Text object representing the line.
    """
    if not line:
        return Text("")

    if _CONNECTOR_RE.match(line):
        return Text(line, style="log_graph")

    text = Text()
    remaining = line

    sha_match = _SHA_RE.search(remaining)
    if not sha_match:
        return Text(line)

    text.append(remaining[: sha_match.start()])
    text.append(sha_match.group(1), style="log_sha")
    remaining = remaining[sha_match.end() :]

    time_match = _TIME_RE.search(remaining)
    if time_match:
        text.append(remaining[: time_match.start()])
        text.append(time_match.group(1), style="log_time")
        remaining = remaining[time_match.end() :]

    author_match = _AUTHOR_RE.search(remaining)
    if author_match:
        text.append(remaining[: author_match.start()])
        text.append(author_match.group(1), style="log_author")
        remaining = remaining[author_match.end() :]

    refs_match = _REFS_RE.search(remaining)
    if refs_match:
        text.append(remaining[: refs_match.start()])
        text.append("(", style="log_graph")
        text.append(refs_match.group(1), style="branch_current")
        text.append(")", style="log_graph")
        remaining = remaining[refs_match.end() :]

    if remaining:
        text.append(remaining)

    return text


def _run_graph_mode(count: int) -> None:
    """Execute graph passthrough rendering mode."""
    result = git("log", "--graph", f"-n{count}", f"--format={_GRAPH_FORMAT}")
    result.raise_on_error()

    if not result.stdout:
        console.print("No commits found.", style="warning")
        return

    for line in result.stdout.splitlines():
        styled = colorize_graph_line(line)
        console.print(styled)


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
    - --graph: branch/merge graph with colorized output

    [bold]Examples:[/bold]

      gx log                Show last 15 commits
      gx log -c 30          Show last 30 commits
      gx log --full         Include commit bodies
      gx log --graph        Show branch graph
    """
    if verbose:
        set_verbosity(verbose)
    if dry_run:
        set_dry_run(enabled=True)
    check_git_repo()

    if full and graph:
        error("--full and --graph are mutually exclusive.")
        raise typer.Exit(1)

    if graph:
        _run_graph_mode(count)
    else:
        panel = LogPanel(count=count, title="Log", show_body=full).render()
        if panel:
            console.print(panel)
        else:
            console.print("No commits found.", style="warning")
