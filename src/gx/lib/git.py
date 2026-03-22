"""Git subprocess wrapper for executing git commands.

Provides a shared git() function that wraps subprocess.run with result objects,
dry-run support for mutating commands, and verbosity-aware output piping.

Usage in commands:
    from gx.lib.git import git, check_git_repo

    check_git_repo()
    result = git("push", "origin", "main").raise_on_error()
    result = git("diff", "--quiet")
    if result.returncode == 1:
        info("Working tree has changes")
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import typer

from gx.constants import READ_ONLY_GIT_COMMANDS, READ_ONLY_GIT_COMPOUND_COMMANDS
from gx.lib.console import debug, dryrun, error, trace


@dataclass(frozen=True)
class GitResult:
    """Result of a git command execution.

    Use raise_on_error() to bail on failure, or inspect returncode/stdout/stderr directly
    for commands where non-zero exit codes carry meaning (e.g., git diff --quiet).
    """

    command: str
    returncode: int
    stdout: str
    stderr: str

    @property
    def success(self) -> bool:
        """Return True if the command exited with code 0."""
        return self.returncode == 0

    def raise_on_error(self) -> GitResult:
        """Print stderr and exit if the command failed.

        Returns:
            GitResult: Self, for chaining on success.
        """
        if not self.success:
            error(self.stderr or f"Command failed: {self.command}")
            raise typer.Exit(1)
        return self


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


def git(*args: str, timeout: int = 30, cwd: Path | None = None) -> GitResult:
    """Execute a git command and return a GitResult.

    Route command logging through debug() (visible with -v) and pipe command output
    through trace() (visible with -vv). In dry-run mode, mutating commands are skipped
    and a synthetic success result is returned.

    Args:
        *args: Git subcommand and arguments (e.g., "push", "origin", "main").
        timeout: Seconds before the command is killed. Defaults to 30.
        cwd: Working directory for the command. Defaults to None (uses process cwd).
    """
    cmd = ["git", *args]
    cmd_str = " ".join(cmd)

    if _dry_run and not _is_read_only(args):
        dryrun(cmd_str)
        return GitResult(command=cmd_str, returncode=0, stdout="", stderr="")

    debug(cmd_str)

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)  # noqa: S603, PLW1510

    stdout = proc.stdout.strip("\n")
    stderr = proc.stderr.strip("\n")

    if stdout:
        for line in stdout.splitlines():
            trace(line)
    if stderr:
        for line in stderr.splitlines():
            trace(line)

    return GitResult(
        command=cmd_str,
        returncode=proc.returncode,
        stdout=stdout,
        stderr=stderr,
    )


def repo_root() -> Path:
    """Return the repository root path.

    Raises:
        typer.Exit: If not inside a git repository.
    """
    result = git("rev-parse", "--show-toplevel")
    result.raise_on_error()
    return Path(result.stdout)


def check_git_installed() -> None:
    """Bail with a friendly error if git is not installed."""
    if not shutil.which("git"):
        error("git is not installed or not found in PATH.")
        raise typer.Exit(1)


def check_git_repo() -> None:
    """Bail with a friendly error if not inside a git repository."""
    result = git("rev-parse", "--is-inside-work-tree")
    if not result.success:
        error("Not a git repository.")
        raise typer.Exit(1)
