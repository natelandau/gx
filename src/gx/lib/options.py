"""Shared Typer options and arguments for gx commands."""

import typer

VERBOSE_OPTION: int = typer.Option(
    0,
    "--verbose",
    "-v",
    count=True,
    help="Increase verbosity (-v debug, -vv trace).",
)

DRY_RUN_OPTION: bool = typer.Option(
    False,  # noqa: FBT003
    "--dry-run",
    "-n",
    help="Show what would be done without making changes.",
)
