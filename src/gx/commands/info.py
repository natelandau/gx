"""Info subcommand for gx — repository metadata dashboard."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import typer
from rich.panel import Panel
from rich.text import Text

from gx.lib.display import kv_grid
from gx.lib.git import git, repo_root

if TYPE_CHECKING:
    from pathlib import Path

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
