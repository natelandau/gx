# CLI Output Redesign

## Problem

The current output is plain green text lines with no visual hierarchy or progress indication. It feels like raw script output rather than a polished CLI tool. Users can't tell if the tool is actively working through steps or just dumping text.

## Goals

1. **Progress feel** — show spinners while operations run, checkmarks/X on completion (like `gh` CLI)
2. **Polished look** — use bold text, semantic color highlighting, and structured sub-items instead of flat green lines
3. **All verbosity levels polished** — debug (`-v`) and trace (`-vv`) output should also look good
4. **Active tense** — messages use imperative voice ("Fetch from origin" not "Fetching from origin")

## Design

### Step Context Manager

The core primitive. Wraps any operation with a Rich `Status` spinner that animates while the block executes, then prints a completion marker.

```python
with step("Fetch from origin"):
    git("fetch", remote).raise_on_error()
```

**While running:** spinner animates with the message
**On success:** `✓ Fetch from origin` (green ✓, bold default text)
**On exception:** `✗ Fetch from origin` (red ✗, bold default text), then re-raises

The `Step` object supports queuing sub-items that print after the completion marker:

```python
with step("Pull with rebase from origin/main") as s:
    git("pull", "--rebase", remote, remote_branch).raise_on_error()
    s.sub("3 new commits:")
    s.sub("  0fa0a83 feat(log): add pretty log command (#3)")
```

Output:
```
✓ Pull with rebase from origin/main
  │ 3 new commits:
  │   0fa0a83 feat(log): add pretty log command (#3)
```

Sub-items are displayed with a gray (`bright_black`) vertical pipe (`│`) at 2-space indent, providing visual grouping under the parent step.

#### Exception Handling

`step()` catches `BaseException` (which includes `typer.Exit`, `SystemExit`, `KeyboardInterrupt`, and standard exceptions). On any exception:

1. The spinner is cleared
2. `✗ {message}` is printed
3. Any queued sub-items are printed
4. The exception is re-raised

This means `typer.Exit(1)` (raised by `raise_on_error()` and `rollback()`) will trigger the `✗` marker before propagating up. Commands that call `error()` before raising should do so *before* the `step()` block, or the error details should be printed by the caller after catching the exit. The recommended pattern:

```python
with step(f"Fetch from {remote}"):
    result = git("fetch", remote)
    if not result.success:
        raise typer.Exit(1)
```

Error details are printed by the caller or by restructuring error handling outside the step block. The `step()` block itself only needs to contain the operation and the exit raise.

#### Dry-Run Mode

In dry-run mode, `step()` behaves identically — the spinner animates and `✓` prints on success. Since the `git()` wrapper already returns synthetic success for mutating commands in dry-run mode, no special handling is needed in `step()`. The `dryrun()` helper remains available for explicit "[DRY RUN]" notices printed by the git wrapper itself.

### Print Helpers

Replace the current flat helpers with styled variants:

| Helper | Marker | Indentation | Style | Visibility |
|--------|--------|-------------|-------|------------|
| `step()` | `✓` green / `✗` red | none | bold default text | always |
| `sub()` | `│` bright_black | 2 spaces before pipe | default text | always (via step) |
| `warning()` | `!` yellow | none | bold yellow (first), yellow (detail) | always, stderr |
| `error()` | `✗` red | none | bold red (first), red (detail) | always, stderr |
| `debug()` | `›` cyan | 2 spaces before marker | cyan | `-v` |
| `trace()` | `git>` bright_black | 4 spaces before marker | bright_black | `-vv` |
| `dryrun()` | `[DRY RUN]` | none | bold cyan | always |

**Error/warning detail lines:** The first call uses bold text. Subsequent detail lines use `detail=True` to get normal weight and are indented without a marker:

```python
error("Rebase conflict detected")
error("  1. Fix the conflicts in the affected files", detail=True)
error("  2. Stage the resolved files with 'git add'", detail=True)
```

Output:
```
✗ Rebase conflict detected
    1. Fix the conflicts in the affected files
    2. Stage the resolved files with 'git add'
```

The `info()` function is removed. All "this is happening" messages become `step()` calls. Sub-results (commit lists, branch names) use `s.sub()`. Warnings, errors, debug, trace, and dryrun keep their own helpers.

### Semantic Highlighting

A `GitHighlighter` (Rich `RegexHighlighter`) automatically colors git-related tokens anywhere in output:

| Token | Pattern | Color |
|-------|---------|-------|
| SHA | `\b[0-9a-f]{7,12}\b` | yellow |
| Commit type | `feat`, `fix`, `refactor`, etc. before `:` | cyan |
| Scope | `(log)`, `(cli)` after commit type | blue |
| PR/issue ref | `(#3)`, `(#42)` | magenta |

The highlighter is applied globally to the console, so all output (steps, sub-items, debug, trace) benefits automatically.

### Theme

```python
THEME = Theme({
    "step.success": "green",
    "step.fail": "red",
    "step.message": "bold default",
    "step.spinner": "cyan",
    "sub.pipe": "bright_black",
    "git.sha": "yellow",
    "git.type": "cyan",
    "git.scope": "blue",
    "git.colon": "default",
    "git.pr": "magenta",
    "debug.marker": "cyan",
    "debug.message": "cyan",
    "trace.marker": "bright_black",
    "trace.message": "bright_black",
    "warning.marker": "yellow",
    "warning.message": "bold yellow",
    "warning.detail": "yellow",
    "error.marker": "bold red",
    "error.message": "bold red",
    "error.detail": "red",
    "dryrun.marker": "bold cyan",
    "dryrun.message": "bold cyan",
})
```

### Command Refactoring

Each command's output calls change from bare `info()` calls to `step()` context managers wrapping the actual git operations.

**Before (pull.py):**
```python
info(f"Fetching from {remote}...")
result = git("fetch", remote)
if not result.success:
    error(f"Failed to fetch from {remote}.")
    rollback(stashed=stashed)
```

**After (pull.py):**
```python
with step(f"Fetch from {remote}"):
    result = git("fetch", remote)
    if not result.success:
        raise typer.Exit(1)
```

Error detail messages (like rebase conflict instructions) move outside the `step()` block to the caller, printed after catching the exit.

### Files Changed

- `src/gx/lib/console.py` — add `GitHighlighter`, `Step` dataclass, `step()` context manager; update theme; remove `info()`; update `warning()`/`error()` signatures for `detail` parameter
- `src/gx/commands/pull.py` — wrap git operations in `step()`, update messages to active tense
- `src/gx/commands/push.py` — wrap git operations in `step()`, update messages to active tense
- `src/gx/commands/done.py` — wrap git operations in `step()`, update messages to active tense
- `src/gx/commands/feat.py` — wrap git operations in `step()`, update messages to active tense
- `src/gx/commands/clean.py` — wrap git operations in `step()`, update messages to active tense
- `src/gx/lib/git.py` — update `raise_on_error()` to remove its own `error()` call (the `step()` ✗ marker replaces it)
- `tests/` — update test assertions for new output format

### Example Outputs

**gx pull:**
```
✓ Fetch from origin
✓ Pull with rebase from origin/main
  │ 3 new commits:
  │   0fa0a83 feat(log): add pretty log command (#3)
  │   9c96da2 bump(release): v0.1.0 → v0.2.0
  │   cdd86d0 feat(cli): add --version/-V flag (#2)
```

**gx pull (dirty working tree):**
```
✓ Stash local changes
✓ Fetch from origin
✓ Pull with rebase from origin/main
  │ Already up to date
✓ Restore stashed changes
```

**gx pull (with submodules):**
```
✓ Fetch from origin
✓ Pull with rebase from origin/main
  │ 1 new commit:
  │   abc1234 fix(core): update dependency
✓ Update submodules
```

**gx pull (error):**
```
✓ Fetch from origin
✗ Pull with rebase from origin/main
✗ Rebase conflict detected
    1. Fix the conflicts in the affected files
    2. Stage the resolved files with 'git add'
    3. Continue with 'git rebase --continue'
```

**gx pull -v (debug):**
```
  › Resolved remote: origin
  › Tracking branch: origin/main
✓ Fetch from origin
✓ Pull with rebase from origin/main
  │ Already up to date
```

**gx pull -vv (trace):**
```
  › Resolved remote: origin
  › Tracking branch: origin/main
✓ Fetch from origin
    git> git fetch origin
    git> From github.com:user/repo
✓ Pull with rebase from origin/main
  │ Already up to date
    git> git pull --rebase origin main
    git> Already up to date.
```

**gx done (feature branch):**
```
✓ Switch to main
✓ Fetch from origin
✓ Pull with rebase from origin/main
  │ Already up to date
✓ Delete branch feat/log-command
```

**gx done (from worktree):**
```
✓ Remove worktree .worktrees/feat/log-command
✓ Switch to main
✓ Fetch from origin
✓ Pull with rebase from origin/main
  │ Already up to date
✓ Delete branch feat/log-command
! Your previous working directory was removed. Run: cd /path/to/repo
```

**gx push:**
```
! 2 modified files won't be included in this push
✓ Push to origin/feat/login
  │ 2 commits pushed:
  │   a1b2c3d fix(auth): handle expired tokens
  │   e4f5g6h feat(login): add remember-me checkbox
```

**gx feat login:**
```
✓ Fetch latest main from origin
✓ Create branch feat/login from main
```

**gx feat -w login (worktree mode):**
```
✓ Fetch latest main from origin
✓ Create worktree at .worktrees/feat/login
  │ Branch feat/login from main
```

**gx clean:**
```
✓ Fetch with prune
✓ Find 3 stale items
  │ feat/old-feature  (merged)
  │ feat/abandoned    (gone)
  │ feat/empty-one    (empty)
Delete these items? [y/N]: y
✓ Remove 3 branches
```

**gx clean (with worktrees and skipped):**
```
✓ Fetch with prune
✓ Find 2 stale items
  │ Worktrees:
  │   .worktrees/feat/old  (branch: feat/old, merged)
  │ Branches:
  │   feat/abandoned  (gone)
! Skipped (dirty worktree, use --force):
    .worktrees/feat/wip  (branch: feat/wip, empty)
Delete these items? [y/N]: y
✓ Remove 1 worktree and 1 branch
```
