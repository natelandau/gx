# gx

A CLI wrapper around git that adds sensible defaults, safety guards, and summaries to the workflows you run every day.

## Features

- Auto-numbered feature branches with optional worktree isolation
- Push with dirty-tree warnings and a confirmation prompt before touching the default branch
- Pull with automatic stash/unstash and rebase, with guided rebase-or-merge reconciliation on divergence
- Batch cleanup of merged, gone, and empty branches
- Color-coded commit log across all branches with inline branch and tag badges
- Repository dashboard with metadata, branches, GitHub info, and recent commits
- Dry-run mode (`-n`) on every mutating command

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

Every command supports `-h` for help. The mutating commands (`feat`, `push`, `pull`, `integrate`, `clean`, `done`) and `log` also support `-v`/`-vv` for verbosity and `-n` for dry-run.

### `gx info`

Show a dashboard with panels for repository metadata, branches, working tree state, and recent commits. Running `gx` with no arguments inside a repo shows this dashboard.

When the `gh` CLI is installed and the remote is on GitHub, an additional panel shows the repo description, visibility, stars, and open PR/issue counts. Stash and worktree panels appear only when there's something to show.

In a brand-new repo with no commits yet, `gx info` (and `gx status`) show the repository metadata and a "No commits yet" placeholder instead of the branch and commit panels.

```sh
gx info                  # full dashboard
gx                       # same as gx info
```

### `gx status`

Two-panel view: a color-coded file tree of uncommitted changes and a table of active branches with ahead/behind counts, file metrics, and stash counts.

```sh
gx status                # both panels
gx status -F             # file tree only
gx status -b             # branch table only
gx status -a             # include inactive branches
```

### `gx log`

Color-coded commit log inside a panel. Includes commits from all branches, with inline badges marking branch tips and tags. Commits ahead of your current branch render dim so you can see where you are relative to other branches.

```sh
gx log                    # last 15 commits
gx log -c 30              # last 30 commits
gx log --full             # include commit bodies
gx log --graph            # branch/merge ASCII graph
```

### `gx feat`

Create a feature branch from the latest default branch. Without a name, branches are auto-numbered (`feat/1`, `feat/2`, ...), filling gaps in the sequence. The `feat/` prefix is configurable.

```sh
gx feat                  # create feat/1 (or next available)
gx feat login            # create feat/login
gx feat -w               # create in a worktree at .worktrees/feat/1
gx feat -w ui            # create worktree at .worktrees/feat/ui
gx feat -L               # branch from local default (no fetch)
```

By default, `gx feat` fetches the default branch from origin first so the new branch starts at the latest remote tip. Pass `-L` (`--local`) to branch from your local default instead, which keeps any unpushed commits.

`gx feat` requires at least one commit. In a brand-new repo with no commits yet, make an initial commit before creating a feature branch.

Worktree mode (`-w`) lets you work on multiple branches simultaneously without stashing. When the worktree directory is inside the repo, it must be listed in `.gitignore`.

### `gx push`

Push the current branch to its remote tracking branch, or to `origin/<branch>` on first push. Tracking is set up automatically.

```sh
gx push                  # push current branch
gx push -f               # force push with --force-with-lease
gx push -t               # push commits and all tags
```

Safety guards:

- Warns about uncommitted or untracked files that won't be included in the push
- Prompts for confirmation before pushing directly to the default branch
- Force-pushing uses `--force-with-lease` rather than `--force`, which protects against overwriting work on the remote that you haven't seen

### `gx pull`

Fetch and rebase the current branch onto its upstream. Handles uncommitted changes automatically. If the branch has diverged from its upstream, gx guides you through reconciling it instead of failing the rebase.

```sh
gx pull                  # pull and rebase
gx pull --rebase         # reconcile a diverged branch by rebasing
gx pull --merge          # reconcile a diverged branch with a merge commit
gx pull --ff-only        # only fast-forward; fail if the branch has diverged
gx pull -v               # pull with debug output
```

The full sequence:

1. Stash uncommitted changes (including untracked files)
2. Fetch from the remote
3. Rebase onto the upstream branch, or reconcile a divergence
4. Update submodules if `.gitmodules` is present
5. Restore the stash
6. Print a summary of new commits

If the branch has only diverged (both ahead of and behind its upstream), gx shows the commits unique to each side and asks whether to reconcile by rebase or merge, unless `--rebase`, `--merge`, `--ff-only`, or the `integrate.strategy` config setting already decides it. If a rebase or merge conflict occurs, gx leaves the operation in progress and prints resolution steps; any changes it stashed are left in the stash for you to restore with `git stash pop` after you resolve the conflict.

### `gx integrate` (alias: `gx int`)

Reconcile the current branch with another ref, choosing between rebase and merge when they've diverged. Unlike `gx pull`, it doesn't touch your upstream or stash: it refuses to run on a dirty working tree instead.

```sh
gx integrate              # reconcile with the upstream
gx integrate main         # bring main into the current branch
gx integrate main --merge # merge main in without prompting
gx int main -n            # preview integrating main
```

The current branch always receives the changes. With no argument, gx integrates against the upstream tracking branch; given a ref (a local branch like `main` or a remote-qualified ref like `origin/main`), gx fetches it if it names a known remote and brings its commits into the current branch.

Depending on how the branch relates to the target:

- **Already up to date**: nothing to do.
- **Fast-forward** (only behind): gx fast-forwards automatically.
- **Diverged** (both ahead and behind): gx previews the commits unique to each side, then reconciles by rebase or merge. Pass `--rebase`, `--merge`, or `--ff-only` to skip the prompt, or set `integrate.strategy` in your config. `--ff-only` fails cleanly if the branch has actually diverged.

`gx integrate` refuses to run against a dirty working tree. Commit or stash your changes first.

### `gx clean`

Remove branches and worktrees that are no longer needed. Fetches with `--prune` first, then finds branches that are:

- **merged** into the default branch
- **gone** (upstream tracking branch deleted on the remote)
- **empty** (zero commits ahead of the default branch)

```sh
gx clean                 # interactive cleanup
gx clean -y              # skip confirmation prompt
gx clean -f              # include dirty worktrees
gx clean -n              # preview what would be removed
```

The current branch and any branches in the protected list (default: `main`, `master`, `develop`) are never touched. Worktrees with uncommitted changes are skipped unless you pass `--force`.

### `gx done`

Post-merge cleanup. Switches back to the default branch, pulls the latest changes, and deletes the feature branch you were on.

```sh
gx done                  # clean up after a merged PR
gx done -f               # skip the merge-verification check
gx done -n               # preview what would happen
```

Before deleting, gx verifies the branch was actually merged by checking, in order: a `MERGED` PR state from `gh`, an upstream tracking branch that has been deleted on the remote, or a traditional merge commit. If none of those confirm the merge, you're prompted before deletion. Pass `-f` to skip the check.

If you ran `gx done` from a worktree, the worktree is removed first and gx prints a `cd` command for switching back to the main working directory.

## Global Options

| Flag               | Description                                 |
| ------------------ | ------------------------------------------- |
| `-v`               | Debug output (shows git commands)           |
| `-vv`              | Trace output (shows git stdout/stderr)      |
| `-n` / `--dry-run` | Preview changes without executing mutations |
| `-h` / `--help`    | Show help for any command                   |
| `-V` / `--version` | Print the gx version and exit               |

## Configuration

gx works out of the box with no configuration. To customize defaults, create `~/.config/gx/config.toml`:

```toml
[branches]
prefix = "feat"                            # branch prefix for `gx feat`
protected = ["main", "master", "develop"]  # branches protected from cleanup

[worktree]
directory = ".worktrees"                   # worktree base directory

[remote]
name = "origin"                            # default remote name

[display]
nerd_font = true                           # use Nerd Font icons in the log (see Icons below)

[integrate]
strategy = "ask"                           # ask, rebase, merge, or ff-only: default strategy for reconciling a diverged branch
```

Every key is optional. Only specify the ones you want to change.

### Worktree directory

The worktree directory can be relative or absolute:

- Relative paths (e.g. `.worktrees`) are resolved from the repo root and must be listed in `.gitignore`.
- Absolute paths (e.g. `~/tmp/worktrees`) are used as-is and have no `.gitignore` requirement.

### Icons

The `gx log` and `gx info` panels badge remote branches with [Nerd Font](https://www.nerdfonts.com) icons that match the host (GitHub, GitLab, or generic git). gx defaults to `nerd_font = true` because most developer terminals have a Nerd Font installed.

If those badges show empty boxes or garbled characters, your terminal font lacks the icons. Set `nerd_font = false` (or `GX_NERD_FONT=false`) and gx falls back to a plain `@` symbol for every remote.

### Environment variables

Override any setting per-invocation with environment variables. These take priority over the config file.

| Variable                | Example                                          |
| ----------------------- | ------------------------------------------------ |
| `GX_BRANCH_PREFIX`      | `GX_BRANCH_PREFIX=fix gx feat`                   |
| `GX_WORKTREE_DIRECTORY` | `GX_WORKTREE_DIRECTORY=~/wt gx feat -w`          |
| `GX_PROTECTED_BRANCHES` | `GX_PROTECTED_BRANCHES=main,production gx clean` |
| `GX_REMOTE_NAME`        | `GX_REMOTE_NAME=upstream gx push`                |
| `GX_NERD_FONT`          | `GX_NERD_FONT=false gx log`                      |
| `GX_INTEGRATE_STRATEGY` | `GX_INTEGRATE_STRATEGY=rebase gx pull`           |

## License

MIT
