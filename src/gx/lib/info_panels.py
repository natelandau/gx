"""Reusable info dashboard panels for repository metadata.

Provides RepoPanel, GitHubPanel, StashPanel, and WorktreePanel classes shared
by the info command. Each class follows the same pattern: accept data in
__init__, call render() to produce a Rich Panel (or None).

Usage:
    from gx.lib.info_panels import RepoPanel, GitHubPanel, StashPanel, WorktreePanel

    panel = RepoPanel(root, remote_name, remote_url).render()
    console.print(panel)
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from gx.lib.display import kv_grid
from gx.lib.git import git
from gx.lib.github import gh, gh_available, is_github_remote
from gx.lib.worktree import list_worktrees

_BYTES_PER_UNIT = 1024
_SECONDS_PER_MINUTE = 60
_SECONDS_PER_HOUR = 3600
_SECONDS_PER_DAY = 86400


def _remote_to_url(remote: str) -> str | None:
    """Convert a git remote string to a clickable HTTPS URL.

    Handles the common remote formats: git@host:path, ssh://..., https://, and http://.
    Returns None for local filesystem paths or unrecognized formats.

    Args:
        remote: The raw remote URL string from git config.

    Returns:
        An HTTPS URL string, or None if the format is not recognized.
    """
    remote = remote.strip()
    remote = remote.removesuffix(".git")

    if remote.startswith(("https://", "http://")):
        return remote

    if remote.startswith("ssh://"):
        without_scheme = remote[len("ssh://") :]
        if "@" in without_scheme:
            without_scheme = without_scheme.split("@", 1)[1]
        without_scheme = re.sub(r"^([^/:]+):\d+(/.*)", r"\1\2", without_scheme)
        return f"https://{without_scheme}"

    m = re.match(r"^git@([^:]+):(.+)$", remote)
    if m:
        return f"https://{m.group(1)}/{m.group(2)}"

    return None


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


def _git_dir_size(root: Path) -> str:
    """Calculate the total size of the .git directory.

    Args:
        root: The repository root path.
    """
    result = git("rev-parse", "--git-common-dir")
    if not result.success:
        return "\u2014"

    git_dir = Path(result.stdout)
    if not git_dir.is_absolute():
        git_dir = (root / git_dir).resolve()

    if not git_dir.is_dir():
        return "\u2014"

    total = sum(f.stat().st_size for f in git_dir.rglob("*") if f.is_file())
    return _human_size(total)


def _last_fetch_time(root: Path) -> str:
    """Return a human-readable time since the last fetch.

    Uses git rev-parse to locate the git directory so this works correctly
    in worktrees and repos with non-standard GIT_DIR.

    Args:
        root: The repository root path.
    """
    git_dir_result = git("rev-parse", "--git-common-dir")
    if not git_dir_result.success:
        return "Never"

    git_dir = Path(git_dir_result.stdout)
    if not git_dir.is_absolute():
        git_dir = (root / git_dir).resolve()

    fetch_head = git_dir / "FETCH_HEAD"
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


def resolve_remote() -> tuple[str, str]:
    """Resolve the primary remote name and its URL.

    Returns:
        A (remote_name, remote_url) tuple. Values are empty strings on failure.
    """
    name_result = git("remote")
    if not name_result.success or not name_result.stdout:
        return ("", "")

    name = name_result.stdout.splitlines()[0]
    url_result = git("remote", "get-url", name)
    url = url_result.stdout.strip() if url_result.success and url_result.stdout else ""
    return (name, url)


def _gh_open_count(resource: str) -> int | None:
    """Fetch the count of open items (PRs or issues) via the gh CLI.

    Args:
        resource: The gh resource type — "pr" or "issue".
    """
    result = gh(resource, "list", "--state", "open", "--json", "number", "--jq", "length")
    if not result.success:
        return None
    try:
        return int(result.stdout)
    except (ValueError, TypeError):
        return None


class RepoPanel:
    """Repository metadata panel (path, remote, HEAD, tags, commits, age, size).

    Args:
        root: Repository root path.
        remote_name: Primary remote name.
        remote_url: Raw remote URL string.
    """

    def __init__(self, root: Path, remote_name: str, remote_url: str) -> None:
        self.root = root
        self.remote_name = remote_name
        self.remote_url = remote_url

    def render(self) -> Panel:
        """Build a Rich Panel showing repository metadata as a key-value grid."""
        url_text: str | Text = "\u2014"
        if self.remote_url:
            url = _remote_to_url(self.remote_url)
            url_text = Text(url, style=f"link {url}") if url else self.remote_url

        head_result = git("rev-parse", "--short", "HEAD")
        head_val: str | Text = (
            Text(head_result.stdout, style="log_sha")
            if head_result.success and head_result.stdout
            else "\u2014"
        )

        tag_result = git("describe", "--tags", "--abbrev=0")
        tag_val: str | Text = (
            Text(tag_result.stdout, style="log_ref_tag")
            if tag_result.success and tag_result.stdout
            else "\u2014"
        )

        commit_result = git("rev-list", "--count", "HEAD")
        commit_val = (
            commit_result.stdout if commit_result.success and commit_result.stdout else "\u2014"
        )

        contrib_result = git("shortlog", "-sn", "--no-merges", "HEAD")
        contrib_val = (
            str(len(contrib_result.stdout.splitlines()))
            if contrib_result.success and contrib_result.stdout
            else "\u2014"
        )

        age_result = git("log", "--reverse", "--format=%ar", "--max-count=1")
        age_val = age_result.stdout if age_result.success and age_result.stdout else "\u2014"

        sub_count = _submodule_count(self.root)

        rows: list[tuple[str | Text, str | Text]] = [
            ("Path", str(self.root)),
            ("Remote", self.remote_name or "None"),
            ("URL", url_text),
            ("HEAD", head_val),
            ("Latest tag", tag_val),
            ("Commits", commit_val),
            ("Contributors", contrib_val),
            ("Repo age", age_val),
            ("Disk size", _git_dir_size(self.root)),
            ("Last fetch", _last_fetch_time(self.root)),
        ]
        if sub_count:
            rows.append(("Submodules", str(sub_count)))

        return Panel(kv_grid(rows), title="Repository", border_style="dim")


class GitHubPanel:
    """GitHub repository metadata panel (description, visibility, stars, PRs, issues).

    Args:
        remote_url: Git remote URL to query against.
    """

    def __init__(self, remote_url: str) -> None:
        self.remote_url = remote_url

    def render(self) -> Panel | None:
        """Build a Rich Panel showing GitHub repository metadata.

        Returns None when gh is unavailable, the remote is not a GitHub URL,
        or the gh command fails.
        """
        if not gh_available() or not is_github_remote(self.remote_url):
            return None

        result = gh(
            "repo",
            "view",
            "--json",
            "description,visibility,stargazerCount,isFork,parent",
        )
        if not result.success:
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
        pr_text = Text(str(pr_count), style="ahead") if pr_count is not None else Text("\u2014")

        issue_count = _gh_open_count("issue")
        issue_text = (
            Text(str(issue_count), style="unstaged") if issue_count is not None else Text("\u2014")
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
            (Text(branch, style="stash_branch"), str(self.stashes[branch]))
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
        grid.add_column(style="wt_branch")
        grid.add_column(style="wt_path")

        for wt in worktrees:
            branch = wt.branch or "(detached)"
            try:
                rel_path = str(wt.path.relative_to(self.root))
            except ValueError:
                rel_path = str(wt.path)
            grid.add_row(branch, rel_path)

        return Panel(grid, title="Worktrees", border_style="dim")
