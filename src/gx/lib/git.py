"""Run git commands with dry-run and verbosity-aware streaming.

Provides the shared ``git()`` invocation and the ``raise_on_error()`` helper that
gx commands use instead of calling ``subprocess`` or ``run_command`` directly.

Usage:
    check_git_repo()
    raise_on_error(git("push", "origin", "main"))

    # git diff --quiet returns 1 specifically to signal "changes present" -- not an
    # error, so inspect the returncode rather than checking .ok.
    result = git("diff", "--quiet")
    if result.returncode == 1:
        info("Working tree has changes")
"""

from __future__ import annotations

from pathlib import Path

import typer
from nclutils import pp
from nclutils.git import is_git_installed, is_git_repo
from nclutils.pp.constants import Verbosity
from nclutils.sh import CompletedCommand, run_command

from gx.constants import READ_ONLY_GIT_COMMANDS, READ_ONLY_GIT_COMPOUND_COMMANDS

_dry_run: bool = False


def set_dry_run(*, enabled: bool) -> None:
    """Set the global dry-run mode."""
    global _dry_run  # noqa: PLW0603
    _dry_run = enabled


def get_dry_run() -> bool:
    """Return whether dry-run mode is active."""
    return _dry_run


def _is_read_only(args: tuple[str, ...]) -> bool:
    """Return True if the git subcommand is read-only.

    Supports simple commands (always read-only like `status`, `log`) and compound
    commands (read-only only with specific subcommands/flags like `branch --merged`
    but not `branch -d`).
    """
    if not args:
        return False

    cmd = args[0]

    if cmd in READ_ONLY_GIT_COMMANDS:
        return True

    if cmd in READ_ONLY_GIT_COMPOUND_COMMANDS and len(args) > 1:
        return args[1] in READ_ONLY_GIT_COMPOUND_COMMANDS[cmd]

    return False


def git(*args: str, timeout: int = 30, cwd: Path | None = None) -> CompletedCommand:
    """Execute a git command and return the nclutils :class:`CompletedCommand`.

    With -vv, stream output to the terminal as it arrives instead of buffering.
    In dry-run mode, mutating commands are skipped and a synthetic success result
    is returned; read-only commands always execute.

    Args:
        *args: Git subcommand and arguments (e.g., "push", "origin", "main").
        timeout: Seconds before the command is killed. Defaults to 30.
        cwd: Working directory for the command. Defaults to None (uses process cwd).
    """
    argv = ("git", *args)

    if _dry_run and not _is_read_only(args):
        pp.dryrun(" ".join(argv))
        return CompletedCommand(
            argv=argv, returncode=0, stdout="", stderr="", duration=0.0, cwd=cwd
        )

    stream = pp.get_default().verbosity >= Verbosity.TRACE

    return run_command(
        list(argv),
        timeout=timeout,
        cwd=cwd,
        check=False,
        stream=stream,
    )


def raise_on_error(result: CompletedCommand) -> CompletedCommand:
    """Print stderr and exit if a CompletedCommand failed; otherwise return it.

    Use to bail on a single command without writing a manual if/error/exit at every
    call site. Returns the passed-in result so it can be chained.

    Raises:
        typer.Exit: When ``result.ok`` is False.
    """
    if not result.ok:
        pp.error(result.stderr or f"Command failed: {result.command_line}")
        raise typer.Exit(1)
    return result


def repo_root() -> Path:
    """Return the repository root path.

    Raises:
        typer.Exit: If not inside a git repository.
    """
    result = raise_on_error(git("rev-parse", "--show-toplevel"))
    return Path(result.stdout)


def check_git_installed() -> None:
    """Bail with a friendly error if git is not installed."""
    if not is_git_installed():
        pp.error("git is not installed or not found in PATH.")
        raise typer.Exit(1)


def check_git_repo() -> None:
    """Bail with a friendly error if not inside a git repository."""
    if not is_git_repo():
        pp.error("Not a git repository.")
        raise typer.Exit(1)
