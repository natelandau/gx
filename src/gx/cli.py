"""GX CLI - A wrapper around common git commands."""

from __future__ import annotations

import typer
from typer import rich_utils

from gx import __version__
from gx.commands import clean, done, feat, log, pull, push, status
from gx.lib.console import set_verbosity
from gx.lib.git import check_git_installed, git
from gx.lib.options import VERBOSE_OPTION

rich_utils.STYLE_HELPTEXT = ""  # ty:ignore[invalid-assignment]
CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}


app = typer.Typer(rich_markup_mode="rich", context_settings=CONTEXT_SETTINGS)
app.add_typer(push.app, name="push")
app.add_typer(pull.app, name="pull")
app.add_typer(feat.app, name="feat")
app.add_typer(clean.app, name="clean")
app.add_typer(done.app, name="done")
app.add_typer(status.app, name="status")
app.add_typer(log.app, name="log")


def _version_callback(value: bool) -> None:  # noqa: FBT001
    """Print version and exit."""
    if value:
        typer.echo(f"gx {__version__}")
        raise typer.Exit


def _is_git_repo() -> bool:
    """Return True if the current directory is inside a git repository."""
    result = git("rev-parse", "--is-inside-work-tree")
    return result.success


@app.callback(invoke_without_command=True)
def callback(
    ctx: typer.Context,
    verbose: int = VERBOSE_OPTION,
    _version: bool | None = typer.Option(  # noqa: FBT001
        None,
        "--version",
        "-V",
        callback=_version_callback,
        is_flag=True,
        expose_value=False,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Streamline your git workflow.

    GX wraps common git operations with sensible defaults, safety guards, and helpful summaries. Every command supports --dry-run and --verbose flags.

    Run [bold]gx COMMAND -h[/bold] for details on a specific command.

    [bold]Common workflows:[/bold]

      Start a feature branch:     gx feat
      Push your work:             gx push
      Pull latest changes:        gx pull
      Clean stale branches:       gx clean
      Finish a merged PR:         gx done
      View status dashboard:      gx status

    Configure defaults in ~/.config/gx/config.toml
    """
    set_verbosity(verbose)
    check_git_installed()
    if ctx.invoked_subcommand is None:
        if _is_git_repo():
            status_cmd = getattr(ctx.command, "commands", {}).get("status")
            if status_cmd:
                ctx.invoke(status_cmd)
        else:
            typer.echo(ctx.get_help())


def main() -> None:
    """Entry point for the gx CLI."""
    app()
