"""Reusable info dashboard panels for repository metadata.

Provides RepoPanel, GitHubPanel, StashPanel, and WorktreePanel classes shared
by the info command. Each class follows the same pattern: accept data in
__init__, call render() to produce a Rich Panel (or None).

Usage:
    from gx.lib.info_panels import RepoPanel, GitHubPanel, StashPanel, WorktreePanel

    panel = RepoPanel(root, remote).render()
    console.print(panel)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from nclutils.sh import run_command
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from gx.constants import GH_TIMEOUT
from gx.lib.display import kv_grid
from gx.lib.git import git
from gx.lib.github import gh_available, is_github_remote
from gx.lib.worktree import list_worktrees

if TYPE_CHECKING:
    from nclutils.git import Remote

_BYTES_PER_UNIT = 1024
_SECONDS_PER_MINUTE = 60
_SECONDS_PER_HOUR = 3600
_SECONDS_PER_DAY = 86400


def _human_size(size_bytes: int) -> str:
    """Format a byte count as a human-readable string with appropriate unit.

    Args:
        size_bytes: Number of bytes to format.
    """
    value: float = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < _BYTES_PER_UNIT:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= _BYTES_PER_UNIT
    return f"{value:.1f} TB"


def _resolve_git_common_dir(root: Path) -> Path | None:
    """Return the absolute path to the shared git directory, or None if it cannot be resolved.

    Worktrees use a per-worktree git-dir but share the object database under the main
    repo's git-dir; --git-common-dir always points to the shared one.
    """
    result = git("rev-parse", "--git-common-dir")
    if not result.ok:
        return None
    git_dir = Path(result.stdout)
    return git_dir if git_dir.is_absolute() else (root / git_dir).resolve()


def _git_dir_size(git_common_dir: Path | None) -> str:
    """Return the .git directory size as a human-readable string, or em-dash if unknown."""
    if git_common_dir is None or not git_common_dir.is_dir():
        return "\u2014"
    total = sum(f.stat().st_size for f in git_common_dir.rglob("*") if f.is_file())
    return _human_size(total)


def _last_fetch_time(git_common_dir: Path | None) -> str:
    """Return a human-readable time since the last fetch, or "Never" if not known."""
    if git_common_dir is None:
        return "Never"
    fetch_head = git_common_dir / "FETCH_HEAD"
    if not fetch_head.exists():
        return "Never"

    mtime = fetch_head.stat().st_mtime
    now = datetime.now(tz=UTC).timestamp()
    elapsed = int(now - mtime)

    if elapsed < _SECONDS_PER_MINUTE:
        return f"{elapsed}s ago"
    if elapsed < _SECONDS_PER_HOUR:
        return f"{elapsed // _SECONDS_PER_MINUTE}m ago"
    if elapsed < _SECONDS_PER_DAY:
        return f"{elapsed // _SECONDS_PER_HOUR}h ago"
    return f"{elapsed // _SECONDS_PER_DAY}d ago"


def _submodule_count(root: Path) -> int:
    """Count the number of submodules declared in .gitmodules.

    Args:
        root: The repository root path.
    """
    gitmodules = root / ".gitmodules"
    if not gitmodules.exists():
        return 0

    content = gitmodules.read_text()
    return content.count("[submodule ")


def _gh_open_count(resource: str) -> int | None:
    """Fetch the count of open items (PRs or issues) via the gh CLI.

    Args:
        resource: The gh resource type - "pr" or "issue".
    """
    result = run_command(
        ["gh", resource, "list", "--state", "open", "--json", "number", "--jq", "length"],
        timeout=GH_TIMEOUT,
        check=False,
    )
    if not result.ok:
        return None
    try:
        return int(result.stdout)
    except (ValueError, TypeError):
        return None


class RepoPanel:
    """Repository metadata panel (path, remote, HEAD, tags, commits, age, size).

    Args:
        root: Repository root path.
        remote: The primary configured remote, or None for repos without one.
    """

    def __init__(self, root: Path, remote: Remote | None) -> None:
        self.root = root
        self.remote = remote

    def render(self) -> Panel:
        """Build a Rich Panel showing repository metadata as a key-value grid."""
        url_text: str | Text = "\u2014"
        if self.remote:
            web_url = self.remote.web_url
            url_text = Text(web_url, style=f"link {web_url}") if web_url else self.remote.url

        head_result = git("rev-parse", "--short", "HEAD")
        head_val: str | Text = (
            Text(head_result.stdout, style="yellow")
            if head_result.ok and head_result.stdout
            else "\u2014"
        )

        tag_result = git("describe", "--tags", "--abbrev=0")
        tag_val: str | Text = (
            Text(tag_result.stdout, style="bold yellow")
            if tag_result.ok and tag_result.stdout
            else "\u2014"
        )

        commit_result = git("rev-list", "--count", "HEAD")
        commit_val = commit_result.stdout if commit_result.ok and commit_result.stdout else "\u2014"

        contrib_result = git("shortlog", "-sn", "--no-merges", "HEAD")
        contrib_val = (
            str(len(contrib_result.stdout.splitlines()))
            if contrib_result.ok and contrib_result.stdout
            else "\u2014"
        )

        age_result = git("log", "--reverse", "--format=%ar", "--max-count=1")
        age_val = age_result.stdout if age_result.ok and age_result.stdout else "\u2014"

        sub_count = _submodule_count(self.root)
        git_common_dir = _resolve_git_common_dir(self.root)

        rows: list[tuple[str | Text, str | Text]] = [
            ("Path", str(self.root)),
            ("Remote", self.remote.name if self.remote else "None"),
            ("URL", url_text),
            ("HEAD", head_val),
            ("Latest tag", tag_val),
            ("Commits", commit_val),
            ("Contributors", contrib_val),
            ("Repo age", age_val),
            ("Disk size", _git_dir_size(git_common_dir)),
            ("Last fetch", _last_fetch_time(git_common_dir)),
        ]
        if sub_count:
            rows.append(("Submodules", str(sub_count)))

        return Panel(kv_grid(rows), title="Repository", border_style="dim")


class GitHubPanel:
    """GitHub repository metadata panel (description, visibility, stars, PRs, issues).

    Args:
        remote: The primary configured remote, or None.
    """

    def __init__(self, remote: Remote | None) -> None:
        self.remote = remote

    def render(self) -> Panel | None:
        """Build a Rich Panel showing GitHub repository metadata.

        Returns None when gh is unavailable, the remote is not a GitHub URL,
        or the gh command fails.
        """
        if self.remote is None or not gh_available() or not is_github_remote(self.remote.url):
            return None

        result = run_command(
            ["gh", "repo", "view", "--json", "description,visibility,stargazerCount,isFork,parent"],
            timeout=GH_TIMEOUT,
            check=False,
        )
        if not result.ok:
            return None

        try:
            data = json.loads(result.stdout)
        except (json.JSONDecodeError, TypeError):
            return None

        description = data.get("description") or "\u2014"
        visibility = str(data.get("visibility", "")).capitalize() or "\u2014"
        stars = str(data.get("stargazerCount", 0))

        is_fork = data.get("isFork", False)
        fork_val: str | Text = "No"
        if is_fork:
            parent = data.get("parent") or {}
            parent_name = parent.get("nameWithOwner", "unknown")
            fork_val = Text(f"Yes \u2014 {parent_name}", style="dim")

        pr_count = _gh_open_count("pr")
        pr_text = Text(str(pr_count), style="green") if pr_count is not None else Text("\u2014")

        issue_count = _gh_open_count("issue")
        issue_text = (
            Text(str(issue_count), style="red") if issue_count is not None else Text("\u2014")
        )

        rows: list[tuple[str | Text, str | Text]] = [
            ("Description", description),
            ("Visibility", visibility),
            ("Stars", stars),
        ]
        if is_fork:
            rows.append(("Fork", fork_val))
        rows.extend(
            [
                ("Open PRs", pr_text),
                ("Open issues", issue_text),
            ]
        )

        return Panel(kv_grid(rows), title="GitHub", border_style="dim")


class StashPanel:
    """Stash counts per branch panel.

    Args:
        stashes: Mapping of branch name to stash count.
    """

    def __init__(self, stashes: dict[str, int]) -> None:
        self.stashes = stashes

    def render(self) -> Panel | None:
        """Build a Rich Panel showing stash counts per branch.

        Returns None when there are no stashes.
        """
        if not self.stashes:
            return None

        total = sum(self.stashes.values())
        rows: list[tuple[str | Text, str | Text]] = [("Total", str(total))]
        rows.extend(
            (Text(branch, style="cyan"), str(self.stashes[branch]))
            for branch in sorted(self.stashes)
        )

        return Panel(kv_grid(rows), title="Stashes", border_style="dim")


class WorktreePanel:
    """Non-main worktree listing panel.

    Args:
        root: Repository root path, used to compute relative paths.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    def render(self) -> Panel | None:
        """Build a Rich Panel listing non-main worktrees with their paths.

        Returns None when only the main worktree exists or no worktrees are found.
        """
        worktrees = [wt for wt in list_worktrees() if not wt.is_main]
        if not worktrees:
            return None

        grid = Table.grid(padding=(0, 2))
        grid.add_column(style="cyan")
        grid.add_column(style="dim")

        for wt in worktrees:
            branch = wt.branch or "(detached)"
            try:
                rel_path = str(wt.path.relative_to(self.root))
            except ValueError:
                rel_path = str(wt.path)
            grid.add_row(branch, rel_path)

        return Panel(grid, title="Worktrees", border_style="dim")
