"""Global console configuration and leveled print helpers.

Provides a shared Rich Console with centralized theme styling and verbosity-aware
print functions. Commands import helpers instead of using Rich markup directly.

Usage in commands:
    from gx.lib.console import console, info, debug, trace, dryrun, warning, error

    info("Pushing to origin/main...")       # Always shown (green)
    debug("Resolved remote: origin")        # Shown with -v (cyan)
    trace("push origin main")               # Shown with -vv, prefixed '  git> ' (dim)
    dryrun("git push origin main")          # Always shown, bold cyan, '[DRY RUN]' prefix
    warning("Branch has no upstream")       # Always shown on stderr (yellow)
    error("Failed to push")                 # Always shown on stderr (bold red)
    console.print(table)                    # Direct Rich output (tables, panels, etc.)
"""

from typing import Any, ClassVar

from rich.console import Console
from rich.highlighter import RegexHighlighter
from rich.theme import Theme

from gx.constants import Verbosity


class GitHighlighter(RegexHighlighter):
    """Highlight git-related tokens in output text."""

    base_style: str = "git."
    highlights: ClassVar[list[str]] = [
        r"(?P<sha>\b[0-9a-f]{7,12}\b)",
        r"(?P<type>(?:feat|fix|refactor|perf|build|ci|docs|style|test|chore|bump))"
        r"(?P<scope>\([^)]+\))?(?P<colon>:)",
        r"(?P<pr>\(#\d+\))",
    ]


GX_THEME = Theme(
    {
        "info": "green",
        "debug": "cyan",
        "dryrun": "bold cyan",
        "trace": "dim",
        "warning": "yellow",
        "error": "bold red",
        "staged": "green",
        "unstaged": "red",
        "untracked": "cyan",
        "branch_current": "bold green",
        "branch_marker": "bold green",
        "branch_target": "dim",
        "branch_wt": "dim",
        "branch_label": "dim",
        "branch_sep": "dim",
        "ahead": "green",
        "behind": "red",
        "clean": "green",
        "log_sha": "yellow",
        "log_time": "green",
        "log_author": "bold blue",
        "log_ref_tag": "bold yellow",
        "log_body": "dim",
        "log_graph": "dim",
        "step.success": "green",
        "step.fail": "red",
        "step.message": "bold default",
        "step.spinner": "cyan",
        "sub.pipe": "bright_black",
        "git.sha": "yellow",
        "git.type": "cyan",
        "git.scope": "blue",
        "git.colon": "default",
        "git.pr": "magenta",
        "debug.marker": "cyan",
        "debug.message": "cyan",
        "trace.marker": "bright_black",
        "trace.message": "bright_black",
        "warning.marker": "yellow",
        "warning.message": "bold yellow",
        "warning.detail": "yellow",
        "error.marker": "bold red",
        "error.message": "bold red",
        "error.detail": "red",
        "dryrun.marker": "bold cyan",
        "dryrun.message": "bold cyan",
    }
)

highlighter = GitHighlighter()
console = Console(theme=GX_THEME, highlighter=highlighter)
err_console = Console(theme=GX_THEME, stderr=True)

_verbosity: Verbosity = Verbosity.INFO


def set_verbosity(level: int) -> None:
    """Set the global verbosity level, clamping to valid range."""
    global _verbosity  # noqa: PLW0603
    clamped = max(Verbosity.INFO, min(level, Verbosity.TRACE))
    _verbosity = Verbosity(clamped)


def get_verbosity() -> Verbosity:
    """Return the current global verbosity level."""
    return _verbosity


def info(message: str, **kwargs: Any) -> None:
    """Print info-level output to stdout. Always shown."""
    console.print(message, style="info", **kwargs)


def debug(message: str, **kwargs: Any) -> None:
    """Print debug-level output to stdout. Shown with -v or higher."""
    if _verbosity >= Verbosity.DEBUG:
        console.print(message, style="debug", **kwargs)


def trace(message: str, **kwargs: Any) -> None:
    """Print trace-level git output to stdout. Shown with -vv, prefixed with '  git> '."""
    if _verbosity >= Verbosity.TRACE:
        console.print(f"  git> {message}", style="trace", **kwargs)


def dryrun(message: str, **kwargs: Any) -> None:
    """Print a dry-run notice to stdout. Always shown regardless of verbosity."""
    console.print(f"[DRY RUN] {message}", style="dryrun", **kwargs)


def warning(message: str, **kwargs: Any) -> None:
    """Print warning output to stderr. Always shown."""
    err_console.print(message, style="warning", **kwargs)


def error(message: str, **kwargs: Any) -> None:
    """Print error output to stderr. Always shown."""
    err_console.print(message, style="error", **kwargs)
