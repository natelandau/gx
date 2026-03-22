# Info Command Design

## Overview

A new `gx info` command that displays a rich, panel-based dashboard summarizing the current repository. It becomes the default command when `gx` is run without arguments, replacing the current `gx status` default.

## Dashboard Layout

The dashboard is a vertical stack of Rich Panels arranged in a responsive grid.

### Wide layout (terminal width >= 100 columns)

| Row | Left | Center | Right |
|-----|------|--------|-------|
| 1 | Repository | GitHub | — (two-column row) |
| 2 | Branches (full width) | | |
| 3 | Working Tree | Stashes | Worktrees |
| 4 | Recent Commits (full width) | | |

Row 1 is a two-column grid (Repository + GitHub). Row 3 is a three-column grid. Rows 2 and 4 are single full-width panels.

### Narrow layout (terminal width < 100 columns)

All panels stacked vertically in order: Repository, GitHub, Branches, Working Tree, Stashes, Recent Commits, Worktrees.

### Optional sections

- **GitHub panel** — only shown when `gh` CLI is available AND remote is a GitHub URL
- **Worktrees panel** — only shown when non-main worktrees exist
- **Stashes panel** — only shown when stashes exist

When optional sections are absent, remaining panels in the same row expand to fill the space.

## Panel Specifications

### Repository Panel

Key-value grid with right-aligned dim labels, left-aligned values.

| Field | Source | Style |
|-------|--------|-------|
| Path | `git rev-parse --show-toplevel` | default |
| Remote | `git remote get-url origin` | default |
| URL | Transform remote to HTTPS (clickable link) | Rich link |
| HEAD | `git rev-parse --short HEAD` | log_sha |
| Latest tag | `git describe --tags --abbrev=0` | log_ref_tag |
| Commits | `git rev-list --count HEAD` | default |
| Contributors | `git shortlog -sn --all` (count lines) | default |
| Repo age | Date of first commit (`git log --reverse --format=%ci -1`) | default |
| Disk size | Size of `.git` directory (recursive `Path.rglob('*')` sum, formatted human-readable) | default |
| Last fetch | mtime of `.git/FETCH_HEAD` | default |
| Submodules | Count entries in `.gitmodules` (0 if absent) | default |

#### Remote-to-URL conversion

Convert raw git remote to clickable HTTPS URL:
- `git@github.com:user/repo.git` -> `https://github.com/user/repo`
- `ssh://git@host:port/path` -> `https://host/path` (strip port)
- `git@host:user/repo` -> `https://host/user/repo`
- `https://` / `http://` -> passthrough (strip `.git` suffix)
- Unrecognized formats -> omit URL row

### GitHub Panel

Key-value grid, same styling as Repository. Only shown when:
1. `gh` CLI is on PATH (`shutil.which("gh")`)
2. Remote URL contains `github.com`

| Field | Source | Style |
|-------|--------|-------|
| Description | `gh repo view --json description` | default |
| Visibility | `gh repo view --json visibility` | default |
| Stars | `gh repo view --json stargazerCount` | default |
| Fork | `gh repo view --json isFork,parent` | default ("No" or "Yes — parent/repo") |
| Open PRs | `gh pr list --state open --json number` (count) | ahead (green) |
| Open issues | `gh api repos/{owner}/{repo}/issues --jq length` or `gh repo view --json ...` | unstaged (red) |

### Branches Panel

Full-width panel reusing the branch table from `gx status` — same `BranchRow` data collection and rendering. Shows current branch, ahead/behind target and remote, staged/modified/untracked/unmerged counts, stash counts, worktree markers.

This panel is **shared between `info` and `status`** commands. The rendering code will be extracted from `status.py` into shared lib code.

### Working Tree Panel

Condensed single-line summary of current working tree state.

Format: `+3 staged  ~2 modified  ?1 untracked` with appropriate color styles, or `Clean` with green checkmark when no changes.

Data source: `git status --porcelain` parsed with existing `_count_file_statuses()` (extracted from status.py).

### Stashes Panel

Total count header, then per-branch breakdown.

Format:
```
3 stashes total
  feat/info  2
  main       1
```

Data source: `stash_counts()` from `branch.py`. Reuse the stash data already collected during `collect_branch_data()` rather than calling `git stash list` a second time — pass the stash dict through to avoid duplicate git calls.

Only shown when total stash count > 0.

### Recent Commits Panel

Last 5 log entries in a grid: SHA, message, author, relative date.

Data source: `git log -5 --format=<custom>` with fields separated for column layout.

Uses `GitHighlighter` for automatic coloring of SHAs, commit types, scopes, PR refs.

### Worktrees Panel

Lists non-main worktrees with branch name and relative path.

Data source: `list_worktrees()` from `worktree.py`, filtered to exclude main worktree.

Only shown when non-main worktrees exist.

## Panel Styling

- All panels use `border_style="dim"`
- Panel titles styled with new `panel.title` theme entry (`bold cyan`)
- Content uses existing `GX_THEME` styles throughout
- New theme entries added: `panel.title`, `dim_label`, `stash_branch`, `wt_branch`, `wt_path`

## Command Structure

### New file: `src/gx/commands/info.py`

- Own `typer.Typer()` instance
- `@app.callback(invoke_without_command=True)` pattern
- Accepts `--verbose` / `-v` flag (no `--dry-run` — command is read-only)
- Each panel is a private function returning `Panel | None`
- Main callback composes panels into grid layout

### CLI wiring changes in `cli.py`

- Register info command: `app.add_typer(info.app, name="info")`
- Change default `gx` (no args) behavior from running `status` to running `info`
- Update root callback help text/docstring to reflect the new default

### Shared code extraction from `status.py`

The following will be moved to shared lib modules for reuse by both `info` and `status`:

**Move data collection to `src/gx/lib/branch.py`**:
- `BranchRow` dataclass (with its `Path` TYPE_CHECKING import)
- `_collect_branch_data()` -> `collect_branch_data()`
- `_branch_remote_counts()` -> `branch_remote_counts()`
- `_branch_file_statuses()` -> `branch_file_statuses()`
- `_count_file_statuses()` -> `count_file_statuses()`
- Associated constants: `_STATUS_CODE_MIN_LEN`

**Move rendering to new `src/gx/lib/display.py`**:
- Branch rendering functions (`_render_branch_status`, `_build_metric_segments`, `_ahead_behind_segment`)
- These have Rich dependencies (`Text`, theme styles) and do not belong in the data-query `branch.py`

The new branch panel rendering (grid-based with sigils, as in the mockup) replaces the current two-line-per-branch text display in both commands.

**Stays in `status.py`** (status-specific):
- File tree rendering (`_parse_porcelain`, `_build_file_tree`, `_file_entry_text`, `_status_text`)
- Status-specific options and CLI wiring

### Info uses new branch panel style

The info command's branch panel uses the Rich Panel + grid layout from the mockup (marker + name, tracking ref, ahead/behind arrows, file count sigils, stash indicator). The status command will also adopt this same panel rendering, replacing its current two-line-per-branch text display.

## `gx status` updates

- Branch rendering replaced with the shared panel-based display (same as info)
- File tree and status-specific options (`--files`, `--branches`, `--all`) remain unchanged
- Status remains available as `gx status` explicit command

## Error Handling

- Missing `gh` CLI: silently skip GitHub panel
- `gh` present but auth/command fails: silently skip GitHub panel
- Non-GitHub remote: skip GitHub panel
- No remote configured: show "None" for Remote, omit URL row, skip GitHub panel
- No tags: show "None" for latest tag
- No stashes: skip Stashes panel
- No worktrees: skip Worktrees panel
- Missing `.git/FETCH_HEAD`: show "Never" for last fetch
- Detached HEAD: show SHA instead of branch name
- Empty repository (no commits): show "—" for HEAD, commits, contributors, repo age, latest tag; branches and log panels show empty state
- Git command failures: use `warning()` for non-critical failures, continue rendering remaining panels

### GitHub subprocess wrapper

GitHub CLI calls go through the existing `git()` wrapper pattern — create a lightweight `gh()` helper in `src/gx/lib/git.py` (or a new `src/gx/lib/github.py`) that wraps `subprocess.run` for `gh` commands and returns a similar result object. This maintains the project convention of never calling `subprocess` directly from command modules.

## Testing

### Unit tests (`tests/unit/`)
- `_remote_to_url()` conversion with various remote formats
- Panel builder functions with mocked git data
- Grid layout logic (wide vs narrow)
- GitHub detection (gh available + GitHub remote)
- Conditional panel omission

### Integration tests (`tests/integration/`)
- `gx info` in a test repo produces expected panel structure
- `gx` (no args) runs info instead of status
- `gx status` still works independently
- Narrow terminal renders single-column
