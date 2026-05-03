"""GitHub CLI wrapper for executing gh commands.

Provides a gh() function analogous to git() that wraps subprocess calls
to the GitHub CLI, with result objects for consistent error handling.

Usage:
    from gx.lib.github import gh, gh_available, is_github_remote

    if gh_available() and is_github_remote(remote_url):
        result = gh("repo", "view", "--json", "description")
        if result.success:
            data = json.loads(result.stdout)
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

from gx.lib.git import git


@dataclass(frozen=True)
class GhResult:
    """Result of a gh CLI command execution."""

    command: str
    returncode: int
    stdout: str
    stderr: str

    @property
    def success(self) -> bool:
        """Return True if the command exited with code 0."""
        return self.returncode == 0


def gh_available() -> bool:
    """Return whether the gh CLI is installed and on PATH."""
    return shutil.which("gh") is not None


def is_github_remote(remote_url: str) -> bool:
    """Return whether a remote URL points to GitHub.

    Args:
        remote_url: The git remote URL to check.
    """
    return "github.com" in remote_url


def gh(*args: str, timeout: int = 15) -> GhResult:
    """Execute a gh CLI command and return a GhResult.

    Args:
        *args: gh subcommand and arguments (e.g., "repo", "view", "--json", "description").
        timeout: Seconds before the command is killed. Defaults to 15.
    """
    cmd = ["gh", *args]
    cmd_str = " ".join(cmd)

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)  # noqa: S603, PLW1510

    return GhResult(
        command=cmd_str,
        returncode=proc.returncode,
        stdout=proc.stdout.strip("\n"),
        stderr=proc.stderr.strip("\n"),
    )


def pr_state(branch: str) -> str | None:
    """Return the PR state for a branch via gh, or None if it cannot be determined.

    Useful as an authoritative merge signal before destructive cleanup operations.
    Returns the state string (typically "MERGED", "OPEN", or "CLOSED") only when
    gh is installed, the origin remote is on GitHub, and a PR exists for the branch.

    Args:
        branch: The local branch name to look up a PR for.

    Returns:
        The PR state string, or None when gh is unavailable, the remote is not on
        GitHub, no PR exists for the branch, or the gh call fails.
    """
    if not gh_available():
        return None

    remote_result = git("config", "--get", "remote.origin.url")
    if not remote_result.success or not is_github_remote(remote_result.stdout):
        return None

    result = gh("pr", "view", branch, "--json", "state", "-q", ".state")
    if not result.success or not result.stdout:
        return None

    return result.stdout
