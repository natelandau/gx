"""Info subcommand for gx — repository metadata dashboard."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

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
from gx.lib.log_panel import LogPanel
from gx.lib.worktree import list_worktrees

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}
WIDE_THRESHOLD = 100
_BYTES_PER_UNIT = 1024
_SECONDS_PER_MINUTE = 60
_SECONDS_PER_HOUR = 3600
_SECONDS_PER_DAY = 86400

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
    # Use git's own mechanism to find the common git dir (handles worktrees)
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

    Reads the mtime of .git/FETCH_HEAD to determine when the last fetch occurred.

    Args:
        root: The repository root path.
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
    """
    gitmodules = root / ".gitmodules"
    if not gitmodules.exists():
        return 0

    content = gitmodules.read_text()
    return content.count("[submodule ")


def _resolve_remote() -> tuple[str, str]:
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


def _repo_panel(root: Path, remote_name: str, remote_url: str) -> Panel:
    """Build a Rich Panel showing repository metadata as a key-value grid.

    Args:
        root: The repository root path.
        remote_name: The primary remote name (e.g., "origin").
        remote_url: The raw remote URL string.
    """
    url_text: str | Text = "\u2014"
    if remote_url:
        url = _remote_to_url(remote_url)
        url_text = Text(url, style=f"link {url}") if url else remote_url

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

    sub_count = _submodule_count(root)

    rows: list[tuple[str | Text, str | Text]] = [
        ("Path", str(root)),
        ("Remote", remote_name or "None"),
        ("URL", url_text),
        ("HEAD", head_val),
        ("Latest tag", tag_val),
        ("Commits", commit_val),
        ("Contributors", contrib_val),
        ("Repo age", age_val),
        ("Disk size", _git_dir_size(root)),
        ("Last fetch", _last_fetch_time(root)),
    ]
    if sub_count:
        rows.append(("Submodules", str(sub_count)))

    return Panel(kv_grid(rows), title="Repository", border_style="dim")


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


def _github_panel(remote_url: str) -> Panel | None:
    """Build a Rich Panel showing GitHub repository metadata.

    Queries the gh CLI for repo description, visibility, star count, fork status,
    open PR count, and open issue count. Returns None when gh is unavailable, the
    remote is not a GitHub URL, or the gh command fails.

    Args:
        remote_url: The git remote URL to check and query against.
    """
    if not gh_available() or not is_github_remote(remote_url):
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


def _stash_panel(stashes: dict[str, int]) -> Panel | None:
    """Build a Rich Panel showing stash counts per branch.

    Args:
        stashes: Mapping of branch name to stash count.
    """
    if not stashes:
        return None

    total = sum(stashes.values())
    rows: list[tuple[str | Text, str | Text]] = [("Total", str(total))]
    rows.extend(
        (Text(branch, style="stash_branch"), str(stashes[branch])) for branch in sorted(stashes)
    )

    return Panel(kv_grid(rows), title="Stashes", border_style="dim")


def _worktree_panel(root: Path) -> Panel | None:
    """Build a Rich Panel listing non-main worktrees with their paths.

    Args:
        root: The repository root path, used to compute relative paths.
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


def _compose_dashboard(
    *,
    repo: Panel | None = None,
    github: Panel | None = None,
    branches: Panel | None = None,
    working_tree: Panel | None = None,
    stashes: Panel | None = None,
    log: Panel | None = None,
    worktrees: Panel | None = None,
) -> None:
    """Arrange panels in a responsive grid and print to the console.

    Use a wide two/three-column grid layout when the terminal is at least
    WIDE_THRESHOLD characters wide, otherwise stack all panels vertically.
    """
    wide = console.width >= WIDE_THRESHOLD

    if wide:
        parts: list[Table | Panel] = []

        if github:
            row1 = Table.grid(padding=(0, 1))
            row1.add_column(ratio=1)
            row1.add_column(ratio=1)
            row1.add_row(repo, github)
            parts.append(row1)
        elif repo:
            parts.append(repo)

        if branches:
            parts.append(branches)

        row3_panels = [p for p in (working_tree, stashes, worktrees) if p is not None]
        if row3_panels:
            row3 = Table.grid(padding=(0, 1))
            for _ in row3_panels:
                row3.add_column(ratio=1)
            row3.add_row(*row3_panels)
            parts.append(row3)

        if log:
            parts.append(log)

        if parts:
            console.print(Group(*parts))
    else:
        all_panels = [repo, github, branches, working_tree, stashes, log, worktrees]
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
    remote_name, remote_url = _resolve_remote()

    repo_p = _repo_panel(root, remote_name, remote_url)
    github_p = _github_panel(remote_url)

    stash_data = stash_counts()
    porcelain_result = git("status", "--porcelain")
    porcelain = porcelain_result.stdout if porcelain_result.success else ""
    staged, modified, unmerged, untracked = count_file_statuses(porcelain)

    branch_rows = collect_branch_data(
        show_all=True,
        current_porcelain=porcelain,
        stashes=stash_data,
    )

    _compose_dashboard(
        repo=repo_p,
        github=github_p,
        branches=render_branch_panel(branch_rows),
        working_tree=render_working_tree_panel(
            staged=staged,
            modified=modified,
            unmerged=unmerged,
            untracked=untracked,
        ),
        stashes=_stash_panel(stash_data),
        log=LogPanel(count=5).render(),
        worktrees=_worktree_panel(root),
    )
