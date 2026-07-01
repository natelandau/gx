# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

`gx` is a Python CLI tool that wraps common git commands (push, pull, feature branch management, branch cleanup). Built with Typer and Rich.

## Running

```bash
uv run gx [COMMAND]
uv run gx --help
uv run gx push
uv run gx done               # Clean up after merged PR
```

## Development

```bash
uv sync                  # Install dependencies
uv run duty lint         # Run all linters (ruff, ty, typos, prek)
uv run duty test         # Run tests with coverage
uv run ruff check src/   # Check code quality
uv run ruff format src/  # Format code
```

## Architecture

### Package Structure

```
src/gx/
    __init__.py              # Version string
    cli.py                   # Root Typer app, subcommand registration, main()
    constants.py             # Package constants (read-only command sets, paths)
    commands/
        __init__.py
        clean.py             # Branch/worktree cleanup (UI, confirmation, removal)
        done.py              # Post-merge cleanup: checkout main, pull, delete branch
        feat.py              # Feature branch/worktree management
        info.py              # Repository dashboard
        integrate.py        # Reconcile a diverged branch (rebase vs merge)
        log.py               # Git log subcommand
        pull.py              # Pull subcommand
        push.py              # Push subcommand
        status.py            # Status subcommand
    lib/
        __init__.py
        branch.py            # Branch queries: current, default, merged/gone/empty
        config.py            # User config (GxConfig), TOML loading, env overrides
        display.py           # Shared Rich renderers: branch panel, working tree panel
        git.py               # Git subprocess wrapper, GitResult, dry-run
        github.py            # GitHub CLI wrapper (gh)
        info_panels.py       # RepoPanel, GitHubPanel, StashPanel, WorktreePanel classes
        log_panel.py         # LogPanel class: git log rendering with inline ref badges
        options.py           # Shared Typer options (VERBOSE_OPTION, DRY_RUN_OPTION)
        stale_analyzer.py    # StaleAnalyzer class: identifies stale branches/worktrees
        status_panel.py      # StatusPanel class: porcelain parsing + file tree rendering
        worktree.py          # Worktree management: list (enriched), create, remove
```

### CLI Wiring

- Root `typer.Typer()` in `cli.py` registers subcommands via `app.add_typer()`
- Each subcommand module exports its own `typer.Typer()` instance
- Subcommands use `@app.callback(invoke_without_command=True)` to allow future sub-subcommands
- Entry point: `gx.cli:main` (configured in `pyproject.toml`)

### Console Output

- Output is handled by the external `nclutils` package via its `pp` printer — never call `print()` or instantiate `rich.Console()` directly
- Import the printer: `from nclutils import pp`
    - `pp.step("message")` — context manager: spinner while running, `✓`/`✗` on completion
        - Use `s.sub("text")` inside `with pp.step(...) as s:` to queue sub-items
    - `pp.success(msg, details=[...])` — terminal success line with optional sub-items
    - `pp.info(msg)` — informational line
    - `pp.debug(msg)` — shown with `-v`
    - `pp.trace(msg)` — shown with `-vv`
    - `pp.dryrun(msg)` — always shown, prefixed `[dry-run]`
    - `pp.warning(msg, details=[...])` / `pp.error(msg, details=[...])` — stderr; pass a list for follow-up lines
- For tables/panels/direct Rich usage: `pp.console().print(...)`
- Verbosity set via `-v`/`-vv` flags on root command, wired through `pp.configure(verbosity=...)`

### Git Execution

- Git commands run through `src/gx/lib/git.py` — never call `subprocess` directly
- Import: `from gx.lib.git import git, check_git_installed, check_git_repo, set_dry_run, get_dry_run`
- `git("push", "origin", "main")` returns a `GitResult` dataclass
    - `.success` — True if returncode == 0
    - `.raise_on_error()` — prints stderr via `error()`, raises `typer.Exit(1)` on failure, returns self on success (chainable)
    - `.stdout` / `.stderr` — stripped strings
    - `.command` — full command string
- Command logging: `debug()` logs the command (visible with `-v`), `trace()` pipes stdout/stderr lines (visible with `-vv`)
- Dry-run: `--dry-run`/`-n` flag on each subcommand. Mutating commands return synthetic success; read-only commands defined in `READ_ONLY_GIT_COMMANDS` (constants.py) always execute
- `check_git_installed()` — called once in root CLI callback; verifies git is on PATH
- `check_git_repo()` — call in each subcommand callback; verifies cwd is a git repo

### Branch Queries

- Branch queries run through `src/gx/lib/branch.py`
- Import: `from gx.lib.branch import current_branch, default_branch, has_commits, is_merged, is_gone, is_empty, has_upstream, tracking_branch`
- `current_branch()` — returns branch name or `None` for detached HEAD
- `default_branch()` — detects default branch (remote → local main → local master → current branch)
- `has_commits()` — True if the repo has at least one commit; `False` for an unborn HEAD (brand-new repo). Gate commit-dependent queries (merged/gone/empty, ahead/behind) on it so they don't abort with "malformed object name"
- `has_upstream()` / `tracking_branch()` — check/get remote tracking info
- `is_merged(branch, target)` — True if branch is merged into target
- `is_gone(branch)` — True if upstream was deleted on remote
- `is_empty(branch, target)` — True if zero commits ahead of target

### Worktree Management

- Worktree operations run through `src/gx/lib/worktree.py`
- Import: `from gx.lib.worktree import list_worktrees, create_worktree, remove_worktree, WorktreeInfo`
- `list_worktrees()` — returns `list[WorktreeInfo]` enriched with branch status flags
- `WorktreeInfo` fields: `path`, `branch`, `commit`, `is_bare`, `is_main`, `is_merged`, `is_gone`, `is_empty`
- `create_worktree(path, branch)` — creates worktree with new branch
- `remove_worktree(path)` — removes worktree
- `is_main` worktree is never a cleanup candidate

### Sync and Reconcile

- The reconcile engine lives in `src/gx/lib/sync.py`, shared by `pull` and `integrate`: one engine, two entry points
- Import: `from gx.lib.sync import SyncState, Strategy, classify_sync_state, resolve_strategy, reconcile_divergence`
- `classify_sync_state(ahead, behind)`: returns `SyncState.UP_TO_DATE`, `FAST_FORWARD`, or `DIVERGED` from ahead/behind counts
- `resolve_strategy(...)`: picks a `Strategy` (`REBASE`/`MERGE`/`FF_ONLY`) by precedence: explicit flag, then `integrate.strategy` config, then `None` to signal the caller should prompt
- `reconcile_divergence(...)`: orchestrates a diverged branch, previewing the commits on each side, resolving the strategy, and executing the rebase or merge, reporting conflicts and rolling back a stash on failure
- `integrate.strategy` config (`ask`/`rebase`/`merge`/`ff-only`, default `ask`) drives the default reconcile strategy for both `gx pull` and `gx integrate`

### Adding a New Subcommand

1. Create `src/gx/commands/<name>.py` with its own `typer.Typer()` and `@app.callback()`
2. In `cli.py`, import and register: `app.add_typer(<name>.app, name="<name>")`
3. Add tests in `tests/`

### Testing

- `tests/integration/` used for testing the CLI
- `tests/unit/` used for testing the underlying functionality of the package

## Conventions

- Functions: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Docstrings: Google format
- Type hints on all function signatures
- Ruff for linting and formatting
