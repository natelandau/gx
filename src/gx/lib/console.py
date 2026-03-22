"""Global console configuration and leveled print helpers.

Provides a shared Rich Console with centralized theme styling, a step() context
manager for spinner-based output, and verbosity-aware print functions.

Usage in commands:
    from gx.lib.console import console, step, debug, trace, dryrun, warning, error

    with step("Fetch from origin"):          # Spinner → ✓/✗ marker (always shown)
        git("fetch", remote).raise_on_error()
    debug("Resolved remote: origin")         # Shown with -v (cyan, > prefix)
    trace("push origin main")               # Shown with -vv (bright_black, git> prefix)
    dryrun("git push origin main")           # Always shown, bold cyan, [DRY RUN] prefix
    warning("Branch has no upstream")        # Always shown on stderr (yellow, ! prefix)
    error("Failed to push")                  # Always shown on stderr (bold red, ✗ prefix)
    console.print(table)                     # Direct Rich output (tables, panels, etc.)
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar

from rich.console import Console
from rich.highlighter import RegexHighlighter
from rich.markup import escape
from rich.theme import Theme

from gx.constants import Verbosity

if TYPE_CHECKING:
    from collections.abc import Generator


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
        "staged": "green",
        "unstaged": "red",
        "untracked": "cyan",
        "branch_current": "bold default",
        "branch_marker": "bold default",
        "branch_target": "cyan",
        "branch_wt": "cyan",
        "branch_label": "default",
        "branch_sep": "default",
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
        "info.marker": "bold default",
        "info.message": "bold default",
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


@dataclass
class Step:
    """Collect sub-items during a step for printing after completion."""

    message: str
    _subs: list[str] = field(default_factory=list, init=False)

    def sub(self, text: str) -> None:
        """Queue a sub-item to print after the step completes."""
        self._subs.append(text)


@contextmanager
def step(message: str) -> Generator[Step]:
    """Show a spinner while the block runs, then a completion marker.

    On success, prints a green checkmark followed by the message. On any exception
    (including typer.Exit), prints a red X then re-raises. Sub-items queued
    via Step.sub() are printed after the marker with a gray pipe prefix.
    """
    s = Step(message)
    escaped = escape(message)
    try:
        with console.status(
            f"[step.message]{escaped}...[/]",
            spinner="dots",
            spinner_style="step.spinner",
        ):
            yield s
        console.print(f"[step.success]✓[/] [step.message]{escaped}[/]")
    except BaseException:
        console.print(f"[step.fail]✗[/] [step.message]{escaped}[/]")
        raise
    finally:
        for sub_text in s._subs:  # noqa: SLF001
            console.print(f"  [sub.pipe]│[/] {escape(sub_text)}")


def step_result(message: str, subs: list[str] | None = None) -> None:
    """Print a step-style success marker without a spinner.

    Use for display-only output where the work already completed and no spinner
    is needed. Renders identically to a successful step() completion.
    """
    console.print(f"[step.success]✓[/] [step.message]{escape(message)}[/]")
    if subs:
        for sub_text in subs:
            console.print(f"  [sub.pipe]│[/] {escape(sub_text)}")


def debug(message: str, **kwargs: Any) -> None:
    """Print debug-level output to stdout. Shown with -v or higher."""
    if _verbosity >= Verbosity.DEBUG:
        console.print(f"  [debug.marker]›[/] [debug.message]{escape(message)}[/]", **kwargs)  # noqa: RUF001


def trace(message: str, **kwargs: Any) -> None:
    """Print trace-level git output to stdout. Shown with -vv."""
    if _verbosity >= Verbosity.TRACE:
        console.print(f"    [trace.marker]git>[/] [trace.message]{escape(message)}[/]", **kwargs)


def dryrun(message: str, **kwargs: Any) -> None:
    """Print a dry-run notice to stdout."""
    console.print(f"[dryrun.marker]\\[DRY RUN][/] [dryrun.message]{escape(message)}[/]", **kwargs)


def info(message: str, **kwargs: Any) -> None:
    """Print info-level output to stdout. Always shown."""
    style = "info.message" if kwargs.get("style", True) else "info.marker"
    marker = "[info.marker]✓[/]" if kwargs.get("marker", True) else ""
    prefix = "  " if kwargs.get("prefix", True) else ""
    console.print(f"{marker}{prefix}[{style}]{escape(message)}[/]", **kwargs)


def warning(message: str, *, detail: bool = False, **kwargs: Any) -> None:
    """Print warning output to stderr. First call bold, detail=True for subsequent lines."""
    style = "warning.detail" if detail else "warning.message"
    marker = "" if detail else "[warning.marker]![/] "
    prefix = "  " if detail else ""
    err_console.print(f"{marker}{prefix}[{style}]{escape(message)}[/]", **kwargs)


def error(message: str, *, detail: bool = False, **kwargs: Any) -> None:
    """Print error output to stderr. First call bold, detail=True for subsequent lines."""
    style = "error.detail" if detail else "error.message"
    marker = "" if detail else "[error.marker]✗[/] "
    prefix = "  " if detail else ""
    err_console.print(f"{marker}{prefix}[{style}]{escape(message)}[/]", **kwargs)
