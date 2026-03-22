# gx

A CLI that wraps common git commands with sensible defaults, safety guards, and helpful summaries.

## Features

- Auto-numbered feature branches with optional worktree isolation
- Push with dirty-tree warnings and default-branch confirmation
- Pull with automatic stash/unstash and rebase
- Batch cleanup of merged, gone, and empty branches
- Rich repository dashboard with metadata, branches, GitHub info, and more
- Dry-run mode (`-n`) on every command

## Installation

gx requires Python 3.13 or higher.

```sh
# install via uv
uv tool install git-gx

# or install via pip
pip install git-gx
```

## Quick Start

```sh
gx feat                  # create feat/1 from main
# ... make changes, commit ...
gx push                  # push to origin with tracking
# ... PR merged ...
gx done                  # checkout main, pull, delete feat/1
```

## Commands

Every command supports `-h` for help. All commands except `info` and `status` also support `-v`/`-vv` for verbosity and `-n` for dry-run.

### `gx info`

Display a rich repository dashboard with panels for metadata, branches, working tree state, recent commits, and more. Running `gx` with no arguments inside a repo shows this dashboard automatically.

When the `gh` CLI is installed and the remote is GitHub, an additional panel shows repo description, visibility, stars, and open PR/issue counts. Optional panels (GitHub, stashes, worktrees) appear only when relevant.

```sh
gx info                  # full dashboard
gx                       # same as gx info
```

### `gx status`

Display a two-panel view: a color-coded file tree of uncommitted changes and a table of all active branches with ahead/behind counts, file metrics, and stash counts.

```sh
gx status                # full dashboard
gx status -F             # file tree only
gx status -b             # branch table only
gx status -a             # include inactive branches
```

### `gx feat`

Create a new feature branch from the latest default branch. Without a name, branches are auto-numbered (`feat/1`, `feat/2`, ...), filling gaps in the sequence.

```sh
gx feat                  # create feat/1 (or next available)
gx feat login            # create feat/login
gx feat -w               # create in a git worktree at .worktrees/feat/1
gx feat -w ui            # create worktree at .worktrees/feat/ui
```

Worktree mode (`-w`) lets you work on multiple branches simultaneously without stashing. Requires `.worktrees/` to be in `.gitignore`.

### `gx push`

Push the current branch to its remote tracking branch (or `origin/<branch>` on first push). Automatically sets up tracking.

```sh
gx push                  # push current branch
gx push -f               # force push with --force-with-lease
gx push -t               # push commits and all tags
```

Safety guards:

- Warns about uncommitted or untracked files that won't be included
- Asks for confirmation before pushing to the default branch
- Uses `--force-with-lease` instead of `--force` to prevent overwriting others' work

### `gx pull`

Fetch and rebase the current branch onto its upstream. Handles uncommitted changes automatically.

```sh
gx pull                  # pull and rebase
gx pull -v               # pull with debug output
```

The full sequence:

1. stash uncommitted changes
2. fetch
3. rebase
4. update submodules (if `.gitmodules` exists)
5. restore stash
6. print a summary

If a rebase conflict occurs, gx restores your stash and prints resolution steps.

### `gx clean`

Remove branches and worktrees that are no longer needed. Fetches with `--prune` first, then finds branches that are:

- **merged** into the default branch
- **gone** (upstream deleted on the remote)
- **empty** (zero commits ahead of the default branch)

```sh
gx clean                 # interactive cleanup
gx clean -y              # skip confirmation prompt
gx clean -f              # include dirty worktrees
gx clean -n              # preview what would be removed
```

The current branch, `main`, `master`, and `develop` are always protected. Dirty worktrees are skipped unless you pass `--force`.

### `gx done`

Post-merge cleanup. Checks out the default branch, pulls latest changes, and deletes the feature branch you were on.

```sh
gx done                  # clean up after a merged PR
gx done -n               # preview what would happen
```

If run from a worktree, gx removes the worktree first, then switches to the main working directory.

## Global Options

| Flag               | Description                                 |
| ------------------ | ------------------------------------------- |
| `-v`               | Debug output (shows git commands)           |
| `-vv`              | Trace output (shows git stdout/stderr)      |
| `-n` / `--dry-run` | Preview changes without executing mutations |
| `-h` / `--help`    | Show help for any command                   |

## Configuration

gx works out of the box with no configuration. Optionally, create `~/.config/gx/config.toml` to customize defaults:

```toml
[branches]
prefix = "feat"                            # branch prefix for `gx feat`
protected = ["main", "master", "develop"]  # branches protected from cleanup

[worktree]
directory = ".worktrees"                   # worktree base directory

[remote]
name = "origin"                            # default remote name
```

All keys are optional - only specify the ones you want to change.

### Worktree directory

The worktree directory can be relative or absolute:

- **Relative** (e.g. `.worktrees`) - resolved from the repo root. Must be in `.gitignore`.
- **Absolute** (e.g. `~/tmp/worktrees`) - used as-is. No `.gitignore` requirement.

### Environment variables

Override any setting per-invocation with environment variables:

| Variable                | Example                                          |
| ----------------------- | ------------------------------------------------ |
| `GX_BRANCH_PREFIX`      | `GX_BRANCH_PREFIX=fix gx feat`                   |
| `GX_WORKTREE_DIRECTORY` | `GX_WORKTREE_DIRECTORY=~/wt gx feat -w`          |
| `GX_PROTECTED_BRANCHES` | `GX_PROTECTED_BRANCHES=main,production gx clean` |
| `GX_REMOTE_NAME`        | `GX_REMOTE_NAME=upstream gx push`                |

Environment variables take priority over the config file.

## License

MIT
