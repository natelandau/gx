"""Info subcommand for gx — repository metadata dashboard."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import typer
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from gx.lib.branch import collect_branch_data, count_file_statuses, stash_counts
from gx.lib.console import console
from gx.lib.display import kv_grid, render_branch_panel, render_working_tree_panel
from gx.lib.git import check_git_repo, git, repo_root
from gx.lib.github import gh, gh_available, is_github_remote
from gx.lib.worktree import list_worktrees

if TYPE_CHECKING:
    from pathlib import Path

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}
WIDE_THRESHOLD = 100
_BYTES_PER_UNIT = 1024
_SECONDS_PER_MINUTE = 60
_SECONDS_PER_HOUR = 3600
_SECONDS_PER_DAY = 86400
_LOG_FORMAT = "%h%x00%s%x00%an%x00%ar"
_LOG_FIELD_COUNT = 4

app = typer.Typer(rich_markup_mode="rich", context_settings=CONTEXT_SETTINGS)


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

    # Strip .git suffix early so all branches can assume clean path
    remote = remote.removesuffix(".git")

    # Passthrough for https:// and http://
    if remote.startswith(("https://", "http://")):
        return remote

    # ssh:// protocol — strip user@, strip optional :port
    if remote.startswith("ssh://"):
        # ssh://[user@]host[:port]/path
        without_scheme = remote[len("ssh://") :]
        # Strip user@ prefix
        if "@" in without_scheme:
            without_scheme = without_scheme.split("@", 1)[1]
        # Strip :port if present before the path
        without_scheme = re.sub(r"^([^/:]+):\d+(/.*)", r"\1\2", without_scheme)
        return f"https://{without_scheme}"

    # git@host:path (SCP-style)
    m = re.match(r"^git@([^:]+):(.+)$", remote)
    if m:
        host = m.group(1)
        path = m.group(2)
        return f"https://{host}/{path}"

    return None


def _human_size(size_bytes: int) -> str:
    """Format a byte count as a human-readable string with appropriate unit.

    Args:
        size_bytes: Number of bytes to format.

    Returns:
        A formatted string such as "1.5 MB" or "512 B".
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

    Returns:
        A human-readable size string, or "—" if .git is not found.
    """
    git_dir = root / ".git"
    if not git_dir.exists():
        return "\u2014"

    total = sum(f.stat().st_size for f in git_dir.rglob("*") if f.is_file())
    return _human_size(total)


def _last_fetch_time(root: Path) -> str:
    """Return a human-readable time since the last fetch.

    Reads the mtime of .git/FETCH_HEAD to determine when the last fetch occurred.

    Args:
        root: The repository root path.

    Returns:
        A string like "2h ago" or "3d ago", or "Never" if FETCH_HEAD does not exist.
    """
    fetch_head = root / ".git" / "FETCH_HEAD"
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

    Returns:
        The number of submodule entries, or 0 if .gitmodules does not exist.
    """
    gitmodules = root / ".gitmodules"
    if not gitmodules.exists():
        return 0

    content = gitmodules.read_text()
    return content.count("[submodule ")


def _repo_panel() -> Panel:
    """Build a Rich Panel showing repository metadata as a key-value grid.

    Collects repo path, remote, URL, HEAD, latest tag, commit count, contributor count,
    repo age, disk size, last fetch time, and submodule count.

    Returns:
        A Rich Panel ready for console output.
    """
    root = repo_root()

    # Path
    path_val = str(root)

    # Remote name
    remote_result = git("remote")
    remote_name = (
        remote_result.stdout.splitlines()[0]
        if remote_result.success and remote_result.stdout
        else "None"
    )

    # Remote URL
    url_text: str | Text = "\u2014"
    if remote_name and remote_name != "None":
        url_result = git("remote", "get-url", remote_name)
        if url_result.success and url_result.stdout:
            url = _remote_to_url(url_result.stdout.strip())
            url_text = Text(url, style=f"link {url}") if url else url_result.stdout.strip()

    # HEAD commit SHA
    head_result = git("rev-parse", "--short", "HEAD")
    head_val: str | Text
    if head_result.success and head_result.stdout:
        head_val = Text(head_result.stdout, style="log_sha")
    else:
        head_val = "\u2014"

    # Latest tag
    tag_result = git("describe", "--tags", "--abbrev=0")
    tag_val: str | Text
    if tag_result.success and tag_result.stdout:
        tag_val = Text(tag_result.stdout, style="log_ref_tag")
    else:
        tag_val = "\u2014"

    # Total commit count
    commit_result = git("rev-list", "--count", "HEAD")
    commit_val = (
        commit_result.stdout if commit_result.success and commit_result.stdout else "\u2014"
    )

    # Contributor count
    contrib_result = git("shortlog", "-sn", "--no-merges", "HEAD")
    if contrib_result.success and contrib_result.stdout:
        contrib_val = str(len(contrib_result.stdout.splitlines()))
    else:
        contrib_val = "\u2014"

    # Repo age (first commit date)
    age_result = git("log", "--reverse", "--format=%ar", "--max-count=1")
    age_val = age_result.stdout if age_result.success and age_result.stdout else "\u2014"

    # Disk size
    size_val = _git_dir_size(root)

    # Last fetch
    fetch_val = _last_fetch_time(root)

    # Submodule count
    sub_count = _submodule_count(root)
    sub_val = str(sub_count) if sub_count else "None"

    rows: list[tuple[str, str | Text]] = [
        ("Path", path_val),
        ("Remote", remote_name),
        ("URL", url_text),
        ("HEAD", head_val),
        ("Latest tag", tag_val),
        ("Commits", commit_val),
        ("Contributors", contrib_val),
        ("Repo age", age_val),
        ("Disk size", size_val),
        ("Last fetch", fetch_val),
        ("Submodules", sub_val),
    ]

    return Panel(kv_grid(rows), title="Repository", border_style="dim")


def _gh_pr_count() -> int | None:
    """Fetch the count of open pull requests via the gh CLI.

    Returns:
        The number of open PRs, or None if the command fails or gh is unavailable.
    """
    result = gh("pr", "list", "--state", "open", "--json", "number", "--limit", "1000")
    if not result.success:
        return None
    try:
        return len(json.loads(result.stdout))
    except (json.JSONDecodeError, TypeError):
        return None


def _gh_issue_count() -> int | None:
    """Fetch the count of open issues via the gh CLI.

    Returns:
        The number of open issues, or None if the command fails or gh is unavailable.
    """
    result = gh("issue", "list", "--state", "open", "--json", "number", "--limit", "1000")
    if not result.success:
        return None
    try:
        return len(json.loads(result.stdout))
    except (json.JSONDecodeError, TypeError):
        return None


def _github_panel(remote_url: str) -> Panel | None:
    """Build a Rich Panel showing GitHub repository metadata.

    Queries the gh CLI for repo description, visibility, star count, fork status,
    open PR count, and open issue count. Returns None when gh is unavailable, the
    remote is not a GitHub URL, or the gh command fails.

    Args:
        remote_url: The git remote URL to check and query against.

    Returns:
        A Rich Panel ready for console output, or None if GitHub info is unavailable.
    """
    if not gh_available():
        return None
    if not is_github_remote(remote_url):
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
    if is_fork:
        parent = data.get("parent") or {}
        parent_name = parent.get("nameWithOwner", "unknown")
        fork_val: str | Text = Text(f"Yes \u2014 {parent_name}", style="dim")
    else:
        fork_val = "No"

    pr_count = _gh_pr_count()
    pr_text = Text()
    if pr_count is None:
        pr_text.append("\u2014")
    else:
        pr_text.append(str(pr_count), style="ahead")

    issue_count = _gh_issue_count()
    issue_text = Text()
    if issue_count is None:
        issue_text.append("\u2014")
    else:
        issue_text.append(str(issue_count), style="unstaged")

    rows: list[tuple[str, str | Text]] = [
        ("Description", description),
        ("Visibility", visibility),
        ("Stars", stars),
        ("Fork", fork_val),
        ("Open PRs", pr_text),
        ("Open issues", issue_text),
    ]

    return Panel(kv_grid(rows), title="GitHub", border_style="dim")


def _stash_panel(stashes: dict[str, int]) -> Panel | None:
    """Build a Rich Panel showing stash counts per branch.

    Returns None when the stash dict is empty. Shows the total stash count in
    the header row followed by a per-branch breakdown sorted alphabetically.

    Args:
        stashes: Mapping of branch name to stash count.

    Returns:
        A Rich Panel ready for console output, or None if there are no stashes.
    """
    if not stashes:
        return None

    total = sum(stashes.values())
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim_label", justify="right")
    grid.add_column(style="value")

    grid.add_row("Total", str(total))
    for branch in sorted(stashes):
        branch_text = Text(branch, style="stash_branch")
        grid.add_row(branch_text, str(stashes[branch]))

    return Panel(grid, title="Stashes", border_style="dim")


def _log_panel() -> Panel | None:
    """Build a Rich Panel showing the 5 most recent commits.

    Each row shows the short SHA, commit subject, author name, and relative
    time. Returns None when the git log command fails or produces no output.

    Returns:
        A Rich Panel ready for console output, or None if no commits are available.
    """
    result = git("log", f"--format={_LOG_FORMAT}", "-5")
    if not result.success or not result.stdout:
        return None

    grid = Table.grid(padding=(0, 1))
    grid.add_column(style="log_sha", width=8, no_wrap=True)
    grid.add_column()
    grid.add_column(style="log_author")
    grid.add_column(style="log_time", justify="right")

    for line in result.stdout.splitlines():
        fields = line.split("\x00")
        if len(fields) != _LOG_FIELD_COUNT:
            continue
        sha, subject, author, time_ago = fields
        grid.add_row(sha, subject, author, time_ago)

    return Panel(grid, title="Recent Commits", border_style="dim")


def _worktree_panel(root: Path) -> Panel | None:
    """Build a Rich Panel listing non-main worktrees with their paths.

    Shows branch name and path relative to the repo root for each non-main
    worktree. Returns None when no non-main worktrees exist.

    Args:
        root: The repository root path, used to compute relative paths.

    Returns:
        A Rich Panel ready for console output, or None if no extra worktrees exist.
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
            rel_path = str(wt.path.relative_to(root))
        except ValueError:
            rel_path = str(wt.path)
        grid.add_row(branch, rel_path)

    return Panel(grid, title="Worktrees", border_style="dim")


def _compose_dashboard(panels: dict[str, Panel | None]) -> None:
    """Arrange named panels in a responsive grid and print to the console.

    Use a wide two/three-column grid layout when the terminal is at least
    WIDE_THRESHOLD characters wide, otherwise stack all panels vertically.

    Args:
        panels: Mapping of panel names to Rich Panel objects or None. None entries
            are excluded from the output.
    """
    width = console.width
    wide = width >= WIDE_THRESHOLD

    repo = panels.get("repo")
    github = panels.get("github")
    branches = panels.get("branches")
    working_tree = panels.get("working_tree")
    stash = panels.get("stashes")
    log = panels.get("log")
    worktrees = panels.get("worktrees")

    if wide:
        parts: list[Table | Panel] = []

        # Row 1: Repository | GitHub
        if github:
            row1 = Table.grid(padding=(0, 1))
            row1.add_column(ratio=1)
            row1.add_column(ratio=1)
            row1.add_row(repo, github)
            parts.append(row1)
        elif repo:
            parts.append(repo)

        # Row 2: Branches (full width)
        if branches:
            parts.append(branches)

        # Row 3: Working Tree | Stashes | Worktrees (3-up, only non-None panels)
        row3_panels = [p for p in (working_tree, stash, worktrees) if p is not None]
        if row3_panels:
            row3 = Table.grid(padding=(0, 1))
            for _ in row3_panels:
                row3.add_column(ratio=1)
            row3.add_row(*row3_panels)
            parts.append(row3)

        # Row 4: Recent Commits (full width)
        if log:
            parts.append(log)

        if parts:
            console.print(Group(*parts))
    else:
        all_panels = [repo, github, branches, working_tree, stash, log, worktrees]
        visible = [p for p in all_panels if p is not None]
        if visible:
            console.print(Group(*visible))


@app.callback(invoke_without_command=True)
def info(
    ctx: typer.Context,  # noqa: ARG001
) -> None:
    """Show a rich dashboard for the current repository.

    Displays repository metadata, branch status, working tree state,
    recent commits, and optionally GitHub info and worktree listings.

    [bold]Examples:[/bold]

      gx info                Full dashboard
      gx info -v             Dashboard with debug output
      gx                     Same as gx info (default command)
    """
    check_git_repo()

    root = repo_root()

    # Gather all panels
    repo = _repo_panel()

    remote_result = git("remote", "get-url", "origin")
    remote_url = remote_result.stdout if remote_result.success else ""
    github = _github_panel(remote_url)

    stashes = stash_counts()
    porcelain_result = git("status", "--porcelain")
    porcelain = porcelain_result.stdout if porcelain_result.success else ""
    staged, modified, unmerged, untracked = count_file_statuses(porcelain)

    rows = collect_branch_data(show_all=True, current_porcelain=porcelain)
    branches = render_branch_panel(rows)
    working_tree = render_working_tree_panel(
        staged=staged, modified=modified, unmerged=unmerged, untracked=untracked
    )
    stash = _stash_panel(stashes)
    log = _log_panel()
    worktrees_panel = _worktree_panel(root)

    _compose_dashboard(
        {
            "repo": repo,
            "github": github,
            "branches": branches,
            "working_tree": working_tree,
            "stashes": stash,
            "log": log,
            "worktrees": worktrees_panel,
        }
    )
