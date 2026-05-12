"""GitHub CLI helpers: availability check, remote-url predicate, and PR-state lookup."""

from __future__ import annotations

from typing import Literal

from nclutils.git import primary_remote
from nclutils.sh import run_command, which

from gx.constants import GH_TIMEOUT

PrState = Literal["MERGED", "OPEN", "CLOSED"]


def gh_available() -> bool:
    """Return whether the gh CLI is installed and on PATH."""
    return which("gh") is not None


def is_github_remote(remote_url: str) -> bool:
    """Return whether a remote URL points to GitHub.

    Args:
        remote_url: The git remote URL to check.
    """
    return "github.com" in remote_url


def pr_state(branch: str) -> PrState | None:
    """Return the PR state for a branch via gh, or None if it cannot be determined.

    Useful as an authoritative merge signal before destructive cleanup operations.
    Only returns a value when gh is installed, the primary remote is on GitHub, and
    a PR exists for the branch.

    Args:
        branch: The local branch name to look up a PR for.

    Returns:
        The PR state, or None when gh is unavailable, the remote is not on GitHub,
        no PR exists for the branch, or the gh call fails.
    """
    if not gh_available():
        return None

    remote = primary_remote()
    if remote is None or not is_github_remote(remote.url):
        return None

    result = run_command(
        ["gh", "pr", "view", branch, "--json", "state", "-q", ".state"],
        timeout=GH_TIMEOUT,
        check=False,
    )
    if not result.ok:
        return None

    match result.stdout:
        case "MERGED" | "OPEN" | "CLOSED" as state:
            return state
        case _:
            return None
