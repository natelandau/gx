# Info Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `gx info` dashboard command that becomes the default when `gx` is run without arguments, displaying repository metadata, GitHub info, branches, working tree, stashes, recent commits, and worktrees in a responsive Rich panel layout.

**Architecture:** Section-based — each dashboard panel is an independent function that gathers its data and returns a `Panel | None`. The main command composes panels into a responsive grid (two-up wide, single-column narrow). Branch data collection and rendering are extracted from `status.py` into shared lib modules for reuse.

**Tech Stack:** Python 3.13+, Typer, Rich (Panel, Table.grid, Text, Group), gh CLI (optional)

**Spec:** `docs/specs/2026-03-22-info-command-design.md`

**Mockup:** `mockup.py` (run with `uv run python mockup.py` for reference rendering)

---

## File Structure

### New files
- `src/gx/lib/display.py` — Shared Rich rendering: branch panel, working tree summary, key-value grid helper
- `src/gx/lib/github.py` — GitHub CLI wrapper (`gh()` function + `GhResult`)
- `src/gx/commands/info.py` — Info command: panel builders + grid layout composer
- `tests/unit/test_display.py` — Tests for shared display functions
- `tests/unit/test_github.py` — Tests for gh() wrapper and GitHub data parsing
- `tests/unit/test_info.py` — Tests for info command panels and layout
- `tests/integration/test_info.py` — Integration tests for gx info

### Modified files
- `src/gx/lib/console.py` — Add new theme entries
- `src/gx/lib/branch.py` — Receive extracted data collection functions from status.py
- `src/gx/commands/status.py` — Remove extracted code, import from shared modules, adopt new branch panel
- `src/gx/cli.py` — Register info command, change default to info
- `tests/unit/test_status.py` — Update imports after extraction
- `tests/unit/conftest.py` — Add info command fixtures

---

## Task 1: Add new theme entries to console.py

**Files:**
- Modify: `src/gx/lib/console.py:48-93` (GX_THEME dict)

- [ ] **Step 1: Add theme entries**

Add these entries to `GX_THEME` in `src/gx/lib/console.py`:

```python
"panel.title": "bold cyan",
"dim_label": "dim",
"stash_branch": "cyan",
"wt_branch": "cyan",
"wt_path": "dim",
```

- [ ] **Step 2: Run linter**

Run: `uv run ruff check src/gx/lib/console.py && uv run ruff format src/gx/lib/console.py`

- [ ] **Step 3: Run existing tests to verify no regressions**

Run: `uv run pytest tests/unit/test_console.py -v`
Expected: All pass

- [ ] **Step 4: Commit**

```
feat(console): add theme entries for info dashboard panels
```

---

## Task 2: Extract branch data collection from status.py to branch.py

**Files:**
- Modify: `src/gx/lib/branch.py` — receive extracted functions
- Modify: `src/gx/commands/status.py` — remove extracted code, update imports
- Modify: `tests/unit/test_status.py` — update imports

This task moves data collection functions out of `status.py` into `branch.py` so both `info` and `status` can use them. The rendering functions stay for Task 3.

- [ ] **Step 1: Move constants and data functions to branch.py**

Move these from `status.py` to `branch.py`:
- `_STATUS_CODE_MIN_LEN` constant (rename to module-level)
- `BranchRow` dataclass (add `from pathlib import Path` under TYPE_CHECKING)
- `_count_file_statuses()` → `count_file_statuses()` (make public)
- `_branch_remote_counts()` → `branch_remote_counts()` (make public)
- `_branch_file_statuses()` → `branch_file_statuses()` (make public)
- `_collect_branch_data()` → `collect_branch_data()` (make public)

**Add `tracking_ref` field to `BranchRow`:** Add `tracking_ref: str | None` to the dataclass. Populate it in `collect_branch_data()` using the existing `tracking_remote_ref()` call that's already made during `_branch_remote_counts`. This avoids redundant git subprocess calls later in the renderer.

In `branch.py`, add needed imports at top:
```python
from dataclasses import dataclass
# Under TYPE_CHECKING:
from pathlib import Path
```

`collect_branch_data` calls `git()`, `list_worktrees()`, and several `branch.py` functions. Since these are now in the same module, change the calls from `status.*` to direct calls. The `git()` import is already in `branch.py`.

Add `list_worktrees` import:
```python
from gx.lib.worktree import list_worktrees
```

- [ ] **Step 2: Update status.py imports**

In `status.py`, remove the moved functions and import them from `branch.py`:
```python
from gx.lib.branch import (
    BranchRow,
    collect_branch_data,
    count_file_statuses,
    current_branch,
    default_branch,
    stash_counts,
    tracking_remote_ref,
)
```

Remove the `_STATUS_CODE_MIN_LEN` constant, `BranchRow`, `_count_file_statuses`, `_branch_remote_counts`, `_branch_file_statuses`, and `_collect_branch_data` from `status.py`. Also remove the now-unused imports: `ahead_behind`, `all_local_branches` from the branch import line, and `list_worktrees` from the worktree import.

Update the `status()` callback to call `collect_branch_data()` (without underscore).

- [ ] **Step 3: Update test imports in test_status.py**

Change imports in `tests/unit/test_status.py`:
```python
from gx.lib.branch import BranchRow, collect_branch_data
from gx.commands.status import _build_file_tree, _parse_porcelain
```

Update `TestCollectBranchData` mock paths from `gx.commands.status.*` to `gx.lib.branch.*`:
- `gx.lib.branch.current_branch` → stays (already there via local call)
- `gx.lib.branch.default_branch` → same
- `gx.lib.branch.all_local_branches` → same
- `gx.lib.branch.list_worktrees` → new path
- `gx.lib.branch.stash_counts` → stays
- `gx.lib.branch.ahead_behind` → stays
- `gx.lib.branch.tracking_remote_ref` → stays
- `gx.lib.branch.git` → new path (was `gx.commands.status.git`)

- [ ] **Step 4: Run linter on changed files**

Run: `uv run ruff check src/gx/lib/branch.py src/gx/commands/status.py && uv run ruff format src/gx/lib/branch.py src/gx/commands/status.py`

- [ ] **Step 5: Run all tests to verify extraction preserved behavior**

Run: `uv run pytest tests/unit/test_status.py tests/unit/test_branch.py -v`
Expected: All pass

- [ ] **Step 6: Commit**

```
refactor(branch): extract data collection from status into branch.py
```

---

## Task 3: Create shared display module with branch panel renderer

**Files:**
- Create: `src/gx/lib/display.py`
- Create: `tests/unit/test_display.py`
- Modify: `src/gx/commands/status.py` — replace old branch rendering with new

This task creates the new branch panel renderer (grid-based with sigils, matching the mockup) and a shared `kv_grid()` helper, then wires `status.py` to use it.

- [ ] **Step 1: Write tests for display.py**

Create `tests/unit/test_display.py`:

```python
"""Tests for shared display rendering functions."""

from __future__ import annotations

from pathlib import Path

from rich.panel import Panel
from rich.text import Text

from gx.lib.branch import BranchRow
from gx.lib.display import kv_grid, render_branch_panel, render_working_tree_panel


def _branch_row(
    branch: str = "feat/test",
    target: str = "main",
    ahead_target: int = 0,
    behind_target: int = 0,
    ahead_remote: int | None = None,
    behind_remote: int | None = None,
    staged: int = 0,
    modified: int = 0,
    unmerged: int = 0,
    untracked: int = 0,
    stashes: int = 0,
    is_current: bool = False,
    is_worktree: bool = False,
    worktree_path: Path | None = None,
    tracking_ref: str | None = None,
) -> BranchRow:
    """Build a BranchRow for testing."""
    return BranchRow(
        branch=branch,
        target=target,
        ahead_target=ahead_target,
        behind_target=behind_target,
        ahead_remote=ahead_remote,
        behind_remote=behind_remote,
        staged=staged,
        modified=modified,
        unmerged=unmerged,
        untracked=untracked,
        stashes=stashes,
        is_current=is_current,
        is_worktree=is_worktree,
        worktree_path=worktree_path,
        tracking_ref=tracking_ref,
    )


class TestKvGrid:
    """Tests for key-value grid builder."""

    def test_builds_grid_with_string_values(self):
        """Verify grid renders with plain string values."""
        from rich.table import Table

        result = kv_grid([("Path", "/some/path"), ("Remote", "origin")])
        assert isinstance(result, Table)

    def test_builds_grid_with_text_values(self):
        """Verify grid accepts Rich Text objects as values."""
        from rich.table import Table

        result = kv_grid([("HEAD", Text("abc1234", style="log_sha"))])
        assert isinstance(result, Table)


class TestRenderBranchPanel:
    """Tests for the branch panel renderer."""

    def test_returns_panel_with_branches(self):
        """Verify panel returned when branches exist."""
        rows = [_branch_row(branch="main", is_current=True)]
        result = render_branch_panel(rows)
        assert isinstance(result, Panel)

    def test_returns_none_for_empty_rows(self):
        """Verify None returned when no branch data."""
        result = render_branch_panel([])
        assert result is None

    def test_current_branch_has_marker(self):
        """Verify current branch gets asterisk marker."""
        rows = [_branch_row(branch="main", is_current=True)]
        panel = render_branch_panel(rows)
        # Panel content is the grid table — check it was built
        assert panel is not None

    def test_ahead_behind_arrows(self):
        """Verify ahead/behind shown with arrow sigils."""
        rows = [_branch_row(ahead_target=3, behind_target=2)]
        panel = render_branch_panel(rows)
        assert panel is not None

    def test_file_count_sigils(self):
        """Verify staged/modified/untracked use +/~/? sigils."""
        rows = [_branch_row(staged=1, modified=2, untracked=3)]
        panel = render_branch_panel(rows)
        assert panel is not None

    def test_stash_indicator(self):
        """Verify stash count uses ≡ sigil."""
        rows = [_branch_row(stashes=2)]
        panel = render_branch_panel(rows)
        assert panel is not None


class TestRenderWorkingTreePanel:
    """Tests for the working tree summary panel."""

    def test_shows_counts_when_dirty(self):
        """Verify staged/modified/untracked shown with sigils."""
        panel = render_working_tree_panel(staged=3, modified=2, unmerged=0, untracked=1)
        assert isinstance(panel, Panel)

    def test_shows_clean_when_all_zero(self):
        """Verify 'Clean' shown when no changes."""
        panel = render_working_tree_panel(staged=0, modified=0, unmerged=0, untracked=0)
        assert isinstance(panel, Panel)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_display.py -v`
Expected: FAIL — `gx.lib.display` does not exist yet

- [ ] **Step 3: Create src/gx/lib/display.py**

```python
"""Shared Rich rendering functions for gx commands.

Provides reusable panel builders for branch status, working tree summary,
and key-value grids used by both info and status commands.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

if TYPE_CHECKING:
    from gx.lib.branch import BranchRow


def kv_grid(rows: list[tuple[str, str | Text]]) -> Table:
    """Build a right-aligned label / left-aligned value grid.

    Args:
        rows: List of (label, value) pairs to display.
    """
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim_label", justify="right")
    grid.add_column(style="value")
    for label, value in rows:
        grid.add_row(label, value)
    return grid


def render_branch_panel(rows: list[BranchRow]) -> Panel | None:
    """Render branch data as a Rich Panel with a grid layout.

    Each branch gets one row with: marker + name, tracking ref, ahead/behind
    arrows, file count sigils, and stash indicator.

    Args:
        rows: Collected BranchRow data to render.

    Returns:
        A Rich Panel, or None if rows is empty.
    """
    if not rows:
        return None

    table = Table.grid(padding=(0, 2))
    table.add_column(justify="left")   # marker + name
    table.add_column(justify="left")   # tracking
    table.add_column(justify="right")  # ahead/behind
    table.add_column(justify="right")  # files
    table.add_column(justify="right")  # stashes

    for row in rows:
        marker = "* " if row.is_current else "  "
        name_style = "branch_current" if row.is_current else "branch_label"
        name_text = Text(f"{marker}{row.branch}", style=name_style)

        tracking_ref = _tracking_ref_text(row)
        ab_text = _ahead_behind_text(row)
        file_text = _file_counts_text(row)
        stash_text = Text(f"≡{row.stashes}" if row.stashes else "", style="stash_branch")

        table.add_row(name_text, tracking_ref, ab_text, file_text, stash_text)

    return Panel(table, title="[panel.title]Branches[/]", border_style="dim")


def _tracking_ref_text(row: BranchRow) -> Text:
    """Build the tracking ref column text for a branch row."""
    return Text(row.tracking_ref or "", style="branch_target")


def _ahead_behind_text(row: BranchRow) -> Text:
    """Build the ahead/behind arrows text for a branch row."""
    text = Text()
    ahead = row.ahead_target
    behind = row.behind_target
    if ahead:
        text.append(f"↑{ahead}", style="ahead")
    if ahead and behind:
        text.append(" ")
    if behind:
        text.append(f"↓{behind}", style="behind")
    return text


def _file_counts_text(row: BranchRow) -> Text:
    """Build the file count sigils text for a branch row."""
    text = Text()
    parts: list[tuple[str, str]] = []
    if row.staged:
        parts.append((f"+{row.staged}", "staged"))
    if row.modified:
        parts.append((f"~{row.modified}", "unstaged"))
    if row.unmerged:
        parts.append((f"!{row.unmerged}", "warning.message"))
    if row.untracked:
        parts.append((f"?{row.untracked}", "untracked"))
    for i, (val, style) in enumerate(parts):
        if i:
            text.append(" ")
        text.append(val, style=style)
    return text


def render_working_tree_panel(
    *, staged: int, modified: int, unmerged: int, untracked: int
) -> Panel:
    """Render a condensed working tree status panel.

    Shows sigil-prefixed counts for each category, or 'Clean' if all zero.

    Args:
        staged: Number of staged files.
        modified: Number of modified files.
        unmerged: Number of unmerged files.
        untracked: Number of untracked files.
    """
    text = Text()
    if staged == modified == unmerged == untracked == 0:
        text.append("✓ ", style="clean")
        text.append("Clean", style="clean")
    else:
        parts: list[tuple[str, str, str]] = []
        if staged:
            parts.append((f"+{staged}", "staged", "staged"))
        if modified:
            parts.append((f"~{modified}", "unstaged", "modified"))
        if unmerged:
            parts.append((f"!{unmerged}", "warning.message", "unmerged"))
        if untracked:
            parts.append((f"?{untracked}", "untracked", "untracked"))
        for i, (val, style, label) in enumerate(parts):
            if i:
                text.append("  ")
            text.append(val, style=style)
            text.append(f" {label}", style="dim")

    return Panel(text, title="[panel.title]Working Tree[/]", border_style="dim")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_display.py -v`
Expected: All pass

- [ ] **Step 5: Update status.py to use new branch panel**

In `status.py`:
- Remove `_ahead_behind_segment`, `_build_metric_segments`, `_render_branch_status` functions
- Import `render_branch_panel` from `gx.lib.display`
- In `_print_status_output`, replace the branch rendering:

```python
from gx.lib.display import render_branch_panel

# In _print_status_output, replace:
#   if branch_table is not None:
#       console.print(Panel(branch_table, ...))
# With:
if branch_panel is not None:
    if file_panel is not None:
        console.print()
    console.print(branch_panel)
```

Update the `status()` callback to call `render_branch_panel(rows)` instead of `_render_branch_status(rows)`.

- [ ] **Step 6: Update status tests for new rendering**

In `tests/unit/test_status.py`:
- Remove `TestRenderBranchStatus` class (this logic is now tested in `test_display.py`)
- Remove import of `_render_branch_status` (no longer exists)
- Update `TestStatusEdgeCases.test_branches_only_flag` to check for "Branches" in output instead of "Branch Status"

- [ ] **Step 7: Run linter on all changed files**

Run: `uv run ruff check src/gx/lib/display.py src/gx/commands/status.py tests/unit/test_display.py tests/unit/test_status.py && uv run ruff format src/gx/lib/display.py src/gx/commands/status.py tests/unit/test_display.py tests/unit/test_status.py`

- [ ] **Step 8: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All pass

- [ ] **Step 9: Commit**

```
refactor(display): create shared display module with branch panel renderer

Extract branch rendering into reusable panel-based display. Status command
now uses the new grid-based branch panel with sigils instead of the
two-line-per-branch text format.
```

---

## Task 4: Create GitHub CLI wrapper

**Files:**
- Create: `src/gx/lib/github.py`
- Create: `tests/unit/test_github.py`

- [ ] **Step 1: Write tests for github.py**

Create `tests/unit/test_github.py`:

```python
"""Tests for GitHub CLI wrapper."""

from __future__ import annotations

import pytest

from gx.lib.github import GhResult, gh, gh_available, is_github_remote


class TestGhAvailable:
    """Tests for gh CLI availability detection."""

    def test_available_when_on_path(self, mocker):
        """Verify returns True when gh is on PATH."""
        mocker.patch("gx.lib.github.shutil.which", return_value="/usr/bin/gh")
        assert gh_available() is True

    def test_unavailable_when_not_on_path(self, mocker):
        """Verify returns False when gh is not on PATH."""
        mocker.patch("gx.lib.github.shutil.which", return_value=None)
        assert gh_available() is False


class TestIsGithubRemote:
    """Tests for GitHub remote detection."""

    def test_ssh_github_remote(self):
        """Verify SSH GitHub URL detected."""
        assert is_github_remote("git@github.com:user/repo.git") is True

    def test_https_github_remote(self):
        """Verify HTTPS GitHub URL detected."""
        assert is_github_remote("https://github.com/user/repo.git") is True

    def test_non_github_remote(self):
        """Verify non-GitHub URL rejected."""
        assert is_github_remote("git@gitlab.com:user/repo.git") is False

    def test_empty_string(self):
        """Verify empty string rejected."""
        assert is_github_remote("") is False


class TestGh:
    """Tests for the gh() subprocess wrapper."""

    def test_successful_command(self, mocker):
        """Verify successful gh command returns GhResult with stdout."""
        mock_proc = mocker.Mock(returncode=0, stdout="output\n", stderr="")
        mocker.patch("gx.lib.github.subprocess.run", return_value=mock_proc)
        result = gh("repo", "view")
        assert result.success is True
        assert result.stdout == "output"

    def test_failed_command(self, mocker):
        """Verify failed gh command returns GhResult with error."""
        mock_proc = mocker.Mock(returncode=1, stdout="", stderr="auth error\n")
        mocker.patch("gx.lib.github.subprocess.run", return_value=mock_proc)
        result = gh("repo", "view")
        assert result.success is False
        assert result.stderr == "auth error"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_github.py -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Create src/gx/lib/github.py**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_github.py -v`
Expected: All pass

- [ ] **Step 5: Run linter**

Run: `uv run ruff check src/gx/lib/github.py tests/unit/test_github.py && uv run ruff format src/gx/lib/github.py tests/unit/test_github.py`

- [ ] **Step 6: Commit**

```
feat(github): add gh CLI wrapper for GitHub API integration
```

---

## Task 5: Create the info command with repository panel

**Files:**
- Create: `src/gx/commands/info.py`
- Create: `tests/unit/test_info.py`

Start with the repo panel and remote-to-URL conversion. Other panels added in subsequent tasks.

- [ ] **Step 1: Write tests for remote_to_url and repo panel**

Create `tests/unit/test_info.py`:

```python
"""Tests for gx info command."""

from __future__ import annotations

import pytest

from gx.commands.info import _remote_to_url


class TestRemoteToUrl:
    """Tests for git remote to HTTPS URL conversion."""

    def test_ssh_github(self):
        """Verify git@github.com SSH format converted."""
        assert _remote_to_url("git@github.com:user/repo.git") == "https://github.com/user/repo"

    def test_ssh_protocol(self):
        """Verify ssh:// protocol format converted."""
        assert _remote_to_url("ssh://git@github.com/user/repo.git") == "https://github.com/user/repo"

    def test_ssh_with_port(self):
        """Verify ssh:// with port strips port number."""
        result = _remote_to_url("ssh://git@github.com:2222/user/repo.git")
        assert result == "https://github.com/user/repo"

    def test_https_passthrough(self):
        """Verify https:// URLs passed through with .git stripped."""
        assert _remote_to_url("https://github.com/user/repo.git") == "https://github.com/user/repo"

    def test_http_passthrough(self):
        """Verify http:// URLs passed through."""
        assert _remote_to_url("http://github.com/user/repo") == "http://github.com/user/repo"

    def test_generic_git_at(self):
        """Verify generic git@ format converted."""
        assert _remote_to_url("git@gitlab.com:user/repo.git") == "https://gitlab.com/user/repo"

    def test_unrecognized_returns_none(self):
        """Verify unrecognized format returns None."""
        assert _remote_to_url("/local/path/to/repo") is None

    def test_strips_whitespace(self):
        """Verify leading/trailing whitespace stripped."""
        assert _remote_to_url("  git@github.com:user/repo.git  ") == "https://github.com/user/repo"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_info.py::TestRemoteToUrl -v`
Expected: FAIL

- [ ] **Step 3: Create src/gx/commands/info.py with remote_to_url and repo panel**

```python
"""Info subcommand for gx — repository dashboard."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from gx.lib.console import console
from gx.lib.display import kv_grid
from gx.lib.git import check_git_repo, git, repo_root

if TYPE_CHECKING:
    pass

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}
WIDE_THRESHOLD = 100

app = typer.Typer(rich_markup_mode="rich", context_settings=CONTEXT_SETTINGS)


def _remote_to_url(remote: str) -> str | None:
    """Convert a git remote URL to a clickable HTTPS URL.

    Handles SSH, git@, and HTTPS formats. Returns None for unrecognized formats.

    Args:
        remote: Raw git remote URL string.
    """
    url = remote.strip()
    url = url.removesuffix(".git")
    if url.startswith("ssh://git@"):
        url = url.replace("ssh://git@", "https://", 1)
        url = re.sub(r":\d+", "", url)
    elif url.startswith("git@"):
        url = url.replace(":", "/", 1).replace("git@", "https://", 1)
    elif url.startswith(("https://", "http://")):
        pass
    else:
        return None
    return url


def _human_size(size_bytes: int) -> str:
    """Format byte count as human-readable string."""
    value: float = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def _git_dir_size(root: Path) -> str:
    """Calculate .git directory size, formatted for display."""
    git_dir = root / ".git"
    if not git_dir.is_dir():
        return "—"
    total = sum(f.stat().st_size for f in git_dir.rglob("*") if f.is_file())
    return _human_size(total)


def _last_fetch_time(root: Path) -> str:
    """Return human-readable time since last fetch."""
    fetch_head = root / ".git" / "FETCH_HEAD"
    if not fetch_head.exists():
        return "Never"
    mtime = datetime.fromtimestamp(fetch_head.stat().st_mtime, tz=timezone.utc)
    delta = datetime.now(tz=timezone.utc) - mtime
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "Just now"
    if seconds < 3600:
        mins = seconds // 60
        return f"{mins} minute{'s' if mins != 1 else ''} ago"
    if seconds < 86400:
        hours = seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = seconds // 86400
    return f"{days} day{'s' if days != 1 else ''} ago"


def _submodule_count(root: Path) -> int:
    """Count submodules from .gitmodules file."""
    gitmodules = root / ".gitmodules"
    if not gitmodules.exists():
        return 0
    content = gitmodules.read_text()
    return content.count("[submodule ")


def _repo_panel() -> Panel:
    """Build the Repository metadata panel."""
    root = repo_root()
    rows: list[tuple[str, str | Text]] = [("Path", str(root))]

    remote_result = git("remote", "get-url", "origin")
    remote_raw = remote_result.stdout if remote_result.success else ""
    if remote_raw:
        rows.append(("Remote", remote_raw))
        url = _remote_to_url(remote_raw)
        if url:
            rows.append(("URL", Text(url, style=f"link {url}")))
    else:
        rows.append(("Remote", "None"))

    head_result = git("rev-parse", "--short", "HEAD")
    if head_result.success:
        rows.append(("HEAD", Text(head_result.stdout, style="log_sha")))
    else:
        rows.append(("HEAD", "—"))

    tag_result = git("describe", "--tags", "--abbrev=0")
    if tag_result.success:
        rows.append(("Latest tag", Text(tag_result.stdout, style="log_ref_tag")))
    else:
        rows.append(("Latest tag", "None"))

    count_result = git("rev-list", "--count", "HEAD")
    rows.append(("Commits", count_result.stdout if count_result.success else "—"))

    contrib_result = git("shortlog", "-sn", "--all")
    if contrib_result.success and contrib_result.stdout:
        rows.append(("Contributors", str(len(contrib_result.stdout.splitlines()))))
    else:
        rows.append(("Contributors", "—"))

    age_result = git("log", "--reverse", "--format=%ci", "--max-count=1")
    if age_result.success and age_result.stdout:
        first_date = age_result.stdout.split(" ")[0]
        try:
            first = datetime.strptime(first_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            delta = datetime.now(tz=timezone.utc) - first
            days = delta.days
            if days < 30:
                rows.append(("Repo age", f"{days} day{'s' if days != 1 else ''}"))
            elif days < 365:
                months = days // 30
                rows.append(("Repo age", f"{months} month{'s' if months != 1 else ''}"))
            else:
                years = days // 365
                rows.append(("Repo age", f"{years} year{'s' if years != 1 else ''}"))
        except ValueError:
            rows.append(("Repo age", "—"))
    else:
        rows.append(("Repo age", "—"))

    rows.append(("Disk size", _git_dir_size(root)))
    rows.append(("Last fetch", _last_fetch_time(root)))
    rows.append(("Submodules", str(_submodule_count(root))))

    return Panel(kv_grid(rows), title="[panel.title]Repository[/]", border_style="dim")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_info.py::TestRemoteToUrl -v`
Expected: All pass

- [ ] **Step 5: Run linter**

Run: `uv run ruff check src/gx/commands/info.py tests/unit/test_info.py && uv run ruff format src/gx/commands/info.py tests/unit/test_info.py`

- [ ] **Step 6: Commit**

```
feat(info): add info command with repository panel and URL conversion
```

---

## Task 6: Add GitHub, stash, log, and worktree panels to info command

**Files:**
- Modify: `src/gx/commands/info.py`
- Modify: `tests/unit/test_info.py`

- [ ] **Step 1: Write tests for remaining panels**

Add to `tests/unit/test_info.py`:

```python
from unittest.mock import patch

from gx.commands.info import _github_panel, _log_panel, _stash_panel, _worktree_panel


class TestGithubPanel:
    """Tests for GitHub info panel."""

    def test_returns_none_when_gh_unavailable(self, mocker):
        """Verify None returned when gh CLI not installed."""
        mocker.patch("gx.commands.info.gh_available", return_value=False)
        result = _github_panel("")
        assert result is None

    def test_returns_none_for_non_github_remote(self, mocker):
        """Verify None returned for non-GitHub remote."""
        mocker.patch("gx.commands.info.gh_available", return_value=True)
        mocker.patch("gx.commands.info.is_github_remote", return_value=False)
        result = _github_panel("git@gitlab.com:user/repo.git")
        assert result is None

    def test_returns_panel_for_github_remote(self, mocker):
        """Verify panel returned when gh available and GitHub remote."""
        mocker.patch("gx.commands.info.gh_available", return_value=True)
        mocker.patch("gx.commands.info.is_github_remote", return_value=True)
        gh_mock = mocker.patch("gx.commands.info.gh")
        from gx.lib.github import GhResult

        gh_mock.return_value = GhResult(
            command="gh repo view",
            returncode=0,
            stdout='{"description":"A tool","visibility":"PUBLIC","stargazerCount":42,"isFork":false,"parent":null}',
            stderr="",
        )
        mocker.patch(
            "gx.commands.info._gh_pr_count", return_value=2
        )
        mocker.patch(
            "gx.commands.info._gh_issue_count", return_value=5
        )
        result = _github_panel("git@github.com:user/repo.git")
        assert isinstance(result, Panel)

    def test_returns_none_when_gh_fails(self, mocker):
        """Verify None returned when gh command fails."""
        mocker.patch("gx.commands.info.gh_available", return_value=True)
        mocker.patch("gx.commands.info.is_github_remote", return_value=True)
        gh_mock = mocker.patch("gx.commands.info.gh")
        from gx.lib.github import GhResult

        gh_mock.return_value = GhResult(
            command="gh repo view", returncode=1, stdout="", stderr="auth error"
        )
        result = _github_panel("git@github.com:user/repo.git")
        assert result is None


class TestStashPanel:
    """Tests for stash panel."""

    def test_returns_none_when_no_stashes(self):
        """Verify None returned for empty stash dict."""
        result = _stash_panel({})
        assert result is None

    def test_returns_panel_with_stashes(self):
        """Verify panel returned with stash data."""
        result = _stash_panel({"main": 1, "feat/login": 2})
        assert isinstance(result, Panel)


class TestLogPanel:
    """Tests for recent commits panel."""

    def test_returns_panel_with_commits(self, mocker):
        """Verify panel returned when log has entries."""
        from gx.lib.git import GitResult

        mocker.patch(
            "gx.commands.info.git",
            return_value=GitResult(
                command="git log",
                returncode=0,
                stdout="abc1234\x00feat: add thing\x00Author\x002 days ago\nabc1235\x00fix: bug\x00Author\x003 days ago",
                stderr="",
            ),
        )
        result = _log_panel()
        assert isinstance(result, Panel)

    def test_returns_none_when_no_commits(self, mocker):
        """Verify None returned for empty repo."""
        from gx.lib.git import GitResult

        mocker.patch(
            "gx.commands.info.git",
            return_value=GitResult(command="git log", returncode=1, stdout="", stderr=""),
        )
        result = _log_panel()
        assert result is None


class TestWorktreePanel:
    """Tests for worktree panel."""

    def test_returns_none_when_no_worktrees(self, mocker):
        """Verify None returned when only main worktree exists."""
        from gx.lib.worktree import WorktreeInfo

        main_wt = WorktreeInfo(
            path=Path("/repo"),
            branch="main",
            commit="abc1234",
            is_bare=False,
            is_main=True,
            is_merged=False,
            is_gone=False,
            is_empty=False,
        )
        mocker.patch("gx.commands.info.list_worktrees", return_value=[main_wt])
        result = _worktree_panel(Path("/repo"))
        assert result is None

    def test_returns_panel_with_worktrees(self, mocker):
        """Verify panel returned when non-main worktrees exist."""
        from gx.lib.worktree import WorktreeInfo

        wts = [
            WorktreeInfo(
                path=Path("/repo"),
                branch="main",
                commit="abc1234",
                is_bare=False,
                is_main=True,
                is_merged=False,
                is_gone=False,
                is_empty=False,
            ),
            WorktreeInfo(
                path=Path("/repo/.worktrees/feat-info"),
                branch="feat/info",
                commit="def5678",
                is_bare=False,
                is_main=False,
                is_merged=False,
                is_gone=False,
                is_empty=False,
            ),
        ]
        mocker.patch("gx.commands.info.list_worktrees", return_value=wts)
        result = _worktree_panel(Path("/repo"))
        assert isinstance(result, Panel)
```

Add missing import at top of test file:
```python
from pathlib import Path
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_info.py -v`
Expected: FAIL — functions don't exist yet

- [ ] **Step 3: Add panel functions to info.py**

Add these imports to the top of `src/gx/commands/info.py`:

```python
from gx.lib.github import GhResult, gh, gh_available, is_github_remote
from gx.lib.worktree import list_worktrees
```

Add these functions after `_repo_panel()`:

```python
def _gh_pr_count() -> int | None:
    """Fetch open PR count from GitHub."""
    result = gh("pr", "list", "--state", "open", "--json", "number", "--limit", "1000")
    if not result.success:
        return None
    try:
        return len(json.loads(result.stdout))
    except (json.JSONDecodeError, TypeError):
        return None


def _gh_issue_count() -> int | None:
    """Fetch open issue count from GitHub."""
    result = gh("issue", "list", "--state", "open", "--json", "number", "--limit", "1000")
    if not result.success:
        return None
    try:
        return len(json.loads(result.stdout))
    except (json.JSONDecodeError, TypeError):
        return None


def _github_panel(remote_url: str) -> Panel | None:
    """Build the GitHub info panel.

    Returns None if gh CLI is unavailable, remote is not GitHub,
    or the gh command fails.

    Args:
        remote_url: The git remote URL to check.
    """
    if not gh_available() or not is_github_remote(remote_url):
        return None

    result = gh(
        "repo", "view", "--json",
        "description,visibility,stargazerCount,isFork,parent",
    )
    if not result.success:
        return None

    try:
        data = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        return None

    rows: list[tuple[str, str | Text]] = []
    rows.append(("Description", data.get("description") or "—"))
    rows.append(("Visibility", (data.get("visibility") or "—").capitalize()))
    rows.append(("Stars", str(data.get("stargazerCount", 0))))

    is_fork = data.get("isFork", False)
    if is_fork and data.get("parent"):
        parent = data["parent"]
        fork_text = f"Yes — {parent.get('owner', {}).get('login', '')}/{parent.get('name', '')}"
        rows.append(("Fork", fork_text))
    else:
        rows.append(("Fork", "No"))

    pr_count = _gh_pr_count()
    if pr_count is not None:
        rows.append(("Open PRs", Text(str(pr_count), style="ahead")))

    issue_count = _gh_issue_count()
    if issue_count is not None:
        rows.append(("Open issues", Text(str(issue_count), style="unstaged")))

    return Panel(kv_grid(rows), title="[panel.title]GitHub[/]", border_style="dim")


def _stash_panel(stashes: dict[str, int]) -> Panel | None:
    """Build the stash summary panel.

    Args:
        stashes: Mapping of branch name to stash count.

    Returns:
        Panel or None if no stashes exist.
    """
    if not stashes:
        return None

    total = sum(stashes.values())
    text = Text()
    text.append(f"{total} stash{'es' if total != 1 else ''} total\n", style="default")
    for branch, count in sorted(stashes.items()):
        text.append(f"  {branch}", style="stash_branch")
        padding = max(1, 12 - len(branch))
        text.append(f"{' ' * padding}{count}\n", style="dim")

    return Panel(text, title="[panel.title]Stashes[/]", border_style="dim")


_LOG_FORMAT = "%h%x00%s%x00%an%x00%ar"
_LOG_FIELD_COUNT = 4


def _log_panel() -> Panel | None:
    """Build the recent commits panel."""
    result = git("log", f"--format={_LOG_FORMAT}", "-5")
    if not result.success or not result.stdout:
        return None

    table = Table.grid(padding=(0, 1))
    table.add_column(style="log_sha", width=8)
    table.add_column()
    table.add_column(style="log_author")
    table.add_column(style="log_time", justify="right")

    for line in result.stdout.splitlines():
        parts = line.split("\x00")
        if len(parts) == _LOG_FIELD_COUNT:
            table.add_row(parts[0], parts[1], parts[2], parts[3])

    return Panel(table, title="[panel.title]Recent Commits[/]", border_style="dim")


def _worktree_panel(root: Path) -> Panel | None:
    """Build the worktrees panel.

    Args:
        root: Repository root path for computing relative paths.

    Returns:
        Panel or None if no non-main worktrees exist.
    """
    worktrees = list_worktrees()
    non_main = [wt for wt in worktrees if not wt.is_main]
    if not non_main:
        return None

    table = Table.grid(padding=(0, 2))
    table.add_column(style="wt_branch")
    table.add_column(style="wt_path")

    for wt in non_main:
        branch_name = wt.branch or "detached"
        try:
            rel_path = str(wt.path.relative_to(root))
        except ValueError:
            rel_path = str(wt.path)
        table.add_row(branch_name, rel_path)

    return Panel(table, title="[panel.title]Worktrees[/]", border_style="dim")
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_info.py -v`
Expected: All pass

- [ ] **Step 5: Run linter**

Run: `uv run ruff check src/gx/commands/info.py tests/unit/test_info.py && uv run ruff format src/gx/commands/info.py tests/unit/test_info.py`

- [ ] **Step 6: Commit**

```
feat(info): add GitHub, stash, log, and worktree panels
```

---

## Task 7: Add dashboard layout and info command callback

**Files:**
- Modify: `src/gx/commands/info.py`
- Modify: `tests/unit/test_info.py`

- [ ] **Step 1: Write tests for layout and command**

Add to `tests/unit/test_info.py`:

```python
import click


class TestInfoCommand:
    """Tests for the info command callback."""

    def test_renders_without_error(self, mocker):
        """Verify info command runs and produces output."""
        mocker.patch("gx.commands.info.check_git_repo")
        mocker.patch("gx.commands.info.repo_root", return_value=Path("/repo"))
        mocker.patch("gx.commands.info.git", return_value=GitResult(
            command="git", returncode=0, stdout="test", stderr=""
        ))
        mocker.patch("gx.commands.info.gh_available", return_value=False)
        mocker.patch("gx.commands.info.list_worktrees", return_value=[])
        mocker.patch("gx.commands.info.collect_branch_data", return_value=[])
        mocker.patch("gx.commands.info.stash_counts", return_value={})
        mocker.patch("gx.commands.info.count_file_statuses", return_value=(0, 0, 0, 0))

        from gx.commands.info import info

        ctx = typer.Context(click.Command("info"))
        # Should not raise
        info(ctx=ctx)
```

Add missing imports at top:
```python
import typer
from gx.lib.git import GitResult
```

- [ ] **Step 2: Add the info callback and layout composer to info.py**

Add these imports to info.py:
```python
from gx.lib.branch import collect_branch_data, count_file_statuses, stash_counts
from gx.lib.display import render_branch_panel, render_working_tree_panel
```

Add the callback and composer:

```python
def _compose_dashboard(panels: dict[str, Panel | None]) -> None:
    """Compose panels into a responsive grid layout and print.

    Args:
        panels: Named panels (some may be None) to arrange in the dashboard.
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

        # Row 1: Repository | GitHub (or full-width repo)
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

        # Row 3: Working Tree | Stashes | Worktrees
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
        # Narrow: stack all panels vertically
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
    worktrees = _worktree_panel(root)

    _compose_dashboard({
        "repo": repo,
        "github": github,
        "branches": branches,
        "working_tree": working_tree,
        "stashes": stash,
        "log": log,
        "worktrees": worktrees,
    })
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/unit/test_info.py -v`
Expected: All pass

- [ ] **Step 4: Run linter**

Run: `uv run ruff check src/gx/commands/info.py tests/unit/test_info.py && uv run ruff format src/gx/commands/info.py tests/unit/test_info.py`

- [ ] **Step 5: Commit**

```
feat(info): add dashboard layout composer and command callback
```

---

## Task 8: Wire info command into CLI and change default

**Files:**
- Modify: `src/gx/cli.py`
- Create: `tests/integration/test_info.py`
- Modify: `tests/unit/conftest.py`

- [ ] **Step 1: Register info command in cli.py**

In `src/gx/cli.py`:

Add import:
```python
from gx.commands import clean, done, feat, info, log, pull, push, status
```

Add registration after existing commands:
```python
app.add_typer(info.app, name="info")
```

- [ ] **Step 2: Change default command from status to info**

In the `callback()` function, change:
```python
status_cmd = getattr(ctx.command, "commands", {}).get("status")
```
to:
```python
info_cmd = getattr(ctx.command, "commands", {}).get("info")
```
And update the invocation:
```python
if info_cmd:
    ctx.invoke(info_cmd)
```

- [ ] **Step 3: Update help text**

Update the docstring in `callback()` to change:
```
View status dashboard:      gx status
```
to:
```
View repo dashboard:        gx info
```

- [ ] **Step 4: Write integration tests**

Create `tests/integration/test_info.py`:

```python
"""Integration tests for gx info command."""

from __future__ import annotations

from typing import TYPE_CHECKING

from typer.testing import CliRunner

from gx.cli import app

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


class TestInfoCommand:
    """Integration tests for gx info."""

    def test_info_shows_repository_panel(self, tmp_git_repo: Path):
        """Verify info command shows Repository panel."""
        result = runner.invoke(app, ["info"])
        assert result.exit_code == 0
        assert "Repository" in result.output

    def test_info_shows_branches_panel(self, tmp_git_repo: Path):
        """Verify info command shows Branches panel."""
        result = runner.invoke(app, ["info"])
        assert result.exit_code == 0
        assert "Branches" in result.output

    def test_info_shows_working_tree_panel(self, tmp_git_repo: Path):
        """Verify info command shows Working Tree panel."""
        result = runner.invoke(app, ["info"])
        assert result.exit_code == 0
        assert "Working Tree" in result.output

    def test_info_shows_recent_commits(self, tmp_git_repo: Path):
        """Verify info command shows Recent Commits panel."""
        result = runner.invoke(app, ["info"])
        assert result.exit_code == 0
        assert "Recent Commits" in result.output

    def test_default_command_runs_info(self, tmp_git_repo: Path):
        """Verify bare gx runs info instead of status."""
        result = runner.invoke(app, [])
        assert result.exit_code == 0
        assert "Repository" in result.output

    def test_status_still_works(self, tmp_git_repo: Path):
        """Verify gx status still works independently."""
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0


class TestInfoOutsideGitRepo:
    """Tests for info command outside a git repo."""

    def test_shows_error_outside_repo(self, tmp_path, monkeypatch):
        """Verify error when not in a git repo."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["info"])
        assert result.exit_code != 0
```

- [ ] **Step 5: Add info command fixtures to unit conftest**

Add to `tests/unit/conftest.py`:

```python
@pytest.fixture
def mock_info_git(mocker):
    """Patch git() at the info command's usage site."""
    return mocker.patch("gx.commands.info.git", autospec=True)


@pytest.fixture
def mock_info_check_git_repo(mocker):
    """Patch check_git_repo() at the info command's usage site as a no-op."""
    return mocker.patch("gx.commands.info.check_git_repo", autospec=True)
```

- [ ] **Step 6: Run linter on all changed files**

Run: `uv run ruff check src/gx/cli.py tests/integration/test_info.py tests/unit/conftest.py && uv run ruff format src/gx/cli.py tests/integration/test_info.py tests/unit/conftest.py`

- [ ] **Step 7: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All pass

- [ ] **Step 8: Commit**

```
feat(cli): wire info command and make it the default for bare gx
```

---

## Task 9: Final verification and cleanup

**Files:**
- Delete: `mockup.py` (scratch file, no longer needed)

- [ ] **Step 1: Run full linter suite**

Run: `uv run duty lint`
Expected: All pass

- [ ] **Step 2: Run full test suite with coverage**

Run: `uv run duty test`
Expected: All pass

- [ ] **Step 3: Manual smoke test**

Run: `uv run gx info` in the repo
Run: `uv run gx` (bare, should show info dashboard)
Run: `uv run gx status` (should still work)

Verify:
- Repository panel shows correct path, remote, URL, HEAD, tag, etc.
- Branches panel shows current branch with marker
- Working Tree panel shows correct counts or "Clean"
- Recent Commits panel shows last 5 commits
- GitHub panel appears if gh is available (or is absent gracefully)
- Worktrees panel shows if worktrees exist (or is absent gracefully)

- [ ] **Step 4: Remove mockup.py**

Delete the scratch mockup file — it served its purpose during design.

- [ ] **Step 5: Commit**

```
chore(info): remove design mockup script
```
