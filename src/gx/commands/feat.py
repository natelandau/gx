"""Feat subcommand for gx."""

import re

import typer
from nllog import configure, debug, error, step, warning

from gx.lib.branch import ahead_behind, branch_exists, current_branch, default_branch
from gx.lib.config import config, resolve_worktree_directory
from gx.lib.git import check_git_repo, git, repo_root, set_dry_run
from gx.lib.options import DRY_RUN_OPTION, VERBOSE_OPTION
from gx.lib.workspace import is_dirty
from gx.lib.worktree import create_worktree

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

app = typer.Typer(rich_markup_mode="rich", context_settings=CONTEXT_SETTINGS)

NAME_ARGUMENT: str | None = typer.Argument(
    None,
    help="Name for the branch. Creates feat/<name> (e.g. gx feat login creates feat/login). Omit for auto-numbering.",
)

WORKTREE_OPTION: bool = typer.Option(
    False,  # noqa: FBT003
    "--worktree",
    "-w",
    help="Create the branch in a new worktree under .worktrees/feat/ instead of switching branches.",
)

LOCAL_OPTION: bool = typer.Option(
    False,  # noqa: FBT003
    "--local",
    "-L",
    help="Branch from the local default branch instead of fetching origin. Use to include unpushed commits on your local default branch.",
)


def _next_feat_number() -> int:
    """Find the lowest available feat branch number.

    Scan local branches matching feat/<digit> and return the lowest positive
    integer not already taken, filling gaps in the sequence.
    """
    prefix = config.branch_prefix
    result = git("branch", "--list", f"{prefix}/*")
    if not result.success or not result.stdout:
        return 1

    existing: set[int] = set()
    for line in result.stdout.splitlines():
        name = line.strip().removeprefix("* ").removeprefix("+ ")
        suffix = name.removeprefix(f"{prefix}/")
        if re.fullmatch(r"\d+", suffix):
            existing.add(int(suffix))

    num = 1
    while num in existing:
        num += 1
    return num


def _normalize_name(name: str) -> str:
    """Normalize user input into a valid bare branch name for feat/<name>.

    Apply progressive sanitization so that friendly input like "My Feature!!"
    becomes "my-feature" rather than producing an error.
    """
    original = name
    name = name.strip().lower()
    name = re.sub(r"[\s_]+", "-", name)
    name = re.sub(r"[~^:?*\[\]\\]+", "", name)
    name = re.sub(r"[-.]{2,}", "-", name)
    name = name.strip("-.")

    if (
        not name
        or "/" in name
        or not git("check-ref-format", "--branch", f"{config.branch_prefix}/{name}").success
    ):
        error(f"Cannot normalize into a valid branch name: {original}")
        raise typer.Exit(1)

    if name != original:
        debug(f'Normalized "{original}" to "{name}"')

    return name


def _resolve_branch_name(name: str | None) -> str:
    """Determine the full branch name (feat/<name> or feat/<number>)."""
    if name is not None:
        name = _normalize_name(name)
        return f"{config.branch_prefix}/{name}"
    return f"{config.branch_prefix}/{_next_feat_number()}"


def _resolve_start_point(default: str, *, local: bool) -> str:
    """Return the ref to branch from.

    With local=False (the default), prefer the just-fetched remote-tracking
    ref (e.g. origin/main) so new branches start from the latest remote
    state regardless of whether the local default branch has been pulled.
    Fall back to the local default if no remote-tracking ref exists.

    With local=True, branch from the local default ref so unpushed commits
    on the user's local default branch are carried into the new branch.
    """
    if not local:
        remote_ref = f"{config.remote_name}/{default}"
        if git("rev-parse", "--verify", "--quiet", remote_ref).success:
            return remote_ref
    return default


def _local_default_ahead_of_remote(default: str) -> int:
    """Return the count of commits on local <default> not on origin/<default>.

    Used to detect the case where the user has unpushed commits on their
    local default branch that the new feature branch will not include
    because we branch from the freshly fetched remote tip. Returns 0 when
    the comparison fails - ahead_behind() already returns None on missing
    refs or rev-list failure, so no separate existence pre-check is needed.
    """
    counts = ahead_behind(default, f"{config.remote_name}/{default}")
    return counts[0] if counts else 0


def _maybe_warn_local_ahead(*, default: str, local: bool, name: str | None, worktree: bool) -> None:
    """Inform the user when local default has unpushed commits not in the new branch.

    No-op when local=True (the user already opted in to local mode) or when
    local default matches the remote tip. Otherwise prints the count of
    skipped commits and the exact `gx feat --local` command they can run to
    branch from local instead, preserving worktree mode and branch name.
    """
    if local:
        return
    ahead = _local_default_ahead_of_remote(default)
    if ahead == 0:
        return

    commit_word = "commit" if ahead == 1 else "commits"
    cmd = "gx feat -w --local" if worktree else "gx feat --local"
    if name:
        cmd += f" {name}"
    warning(
        f"Local {default} has {ahead} {commit_word} not on {config.remote_name}/{default}; new branch will not include them.",
        details=[f"Run `{cmd}` to branch from local {default} instead."],
    )


def _prepare_feat_branch(name: str | None, *, local: bool) -> tuple[str, str, str]:
    """Run shared guards and return (feat_branch, start_point, default).

    Check for detached HEAD, fetch the default branch (unless local=True),
    warn if currently on a feat/* branch, resolve the branch name, and
    verify it doesn't exist. The returned start_point is origin/<default>
    when present (local=False) so the new branch is rooted at the freshly
    fetched remote tip; with local=True it is the local default ref so
    unpushed commits are carried into the new branch. `default` is exposed
    so callers can compose follow-up messages without re-querying.
    """
    branch = current_branch()
    if branch is None:
        error("Cannot create feature branch in detached HEAD state.")
        raise typer.Exit(1)

    default = default_branch()

    if not local:
        with step(f"Fetch latest {default} from {config.remote_name}"):
            git("fetch", config.remote_name, default).raise_on_error()

    if branch.startswith(f"{config.branch_prefix}/"):
        warning(f"Currently on {branch}")

    feat_branch = _resolve_branch_name(name)

    if branch_exists(feat_branch):
        error(f"Branch {feat_branch} already exists.")
        raise typer.Exit(1)

    start_point = _resolve_start_point(default, local=local)

    return feat_branch, start_point, default


def _create_branch(name: str | None, *, local: bool = False) -> None:
    """Create a feature branch and switch to it."""
    feat_branch, start_point, default = _prepare_feat_branch(name, local=local)
    _maybe_warn_local_ahead(default=default, local=local, name=name, worktree=False)

    with step(f"Create branch {feat_branch} from {start_point}"):
        result = git("checkout", "--no-track", "-b", feat_branch, start_point)
        if not result.success:
            if is_dirty():
                error(
                    "Checkout failed due to uncommitted changes that conflict with the target branch",
                    details=["Commit or stash your changes first, then try again"],
                )
            else:
                error(result.stderr or f"Failed to create branch {feat_branch}")
            raise typer.Exit(1)


def _create_worktree_branch(name: str | None, *, local: bool = False) -> None:
    """Create a feature branch in a new worktree."""
    feat_branch, start_point, default = _prepare_feat_branch(name, local=local)
    _maybe_warn_local_ahead(default=default, local=local, name=name, worktree=True)

    root = repo_root()
    worktree_base = resolve_worktree_directory(root)
    prefix = config.branch_prefix
    worktree_path = worktree_base / prefix / feat_branch.removeprefix(f"{prefix}/")

    # Only check gitignore for in-repo (relative) worktree directories
    if worktree_base.is_relative_to(root):
        check = git("check-ignore", "-q", str(worktree_base))
        if not check.success:
            error(f"{worktree_base.name}/ is not in .gitignore. Add it before creating worktrees.")
            raise typer.Exit(1)

    try:
        display_path = worktree_path.relative_to(root)
    except ValueError:
        display_path = worktree_path

    with step(f"Create worktree at {display_path}") as s:
        create_worktree(
            path=worktree_path, branch=feat_branch, start_point=start_point
        ).raise_on_error()
        s.sub(f"Branch {feat_branch} from {start_point}")


@app.callback(invoke_without_command=True)
def feat(
    ctx: typer.Context,  # noqa: ARG001
    verbose: int = VERBOSE_OPTION,
    dry_run: bool = DRY_RUN_OPTION,  # noqa: FBT001
    name: str | None = NAME_ARGUMENT,
    worktree: bool = WORKTREE_OPTION,  # noqa: FBT001
    local: bool = LOCAL_OPTION,  # noqa: FBT001
) -> None:
    """Create a new feature branch from the default branch.

    Fetches the latest default branch (main/master) from origin, then creates a new feat/* branch from it. Without a name, branches are auto-numbered (feat/1, feat/2, ...), filling gaps in the sequence.

    [bold]Branch mode (default):[/bold]

    Creates the branch and switches to it in the current working directory.

    [bold]Worktree mode (-w):[/bold]

    Creates the branch in a new git worktree at .worktrees/feat/<name>. This lets you work on multiple branches simultaneously without stashing. Requires .worktrees/ to be listed in .gitignore.

    [bold]Local mode (-L):[/bold]

    Skips the fetch and branches from your local default branch instead of origin/<default>. Use this when you have unpushed commits on your local default branch that you want included in the new feature branch.

    [bold]Examples:[/bold]

      gx feat              Create feat/1 (or next available number)
      gx feat login        Create feat/login
      gx feat -w           Create feat/1 in a worktree
      gx feat -w ui        Create feat/ui in a worktree
      gx feat -L           Create feat/1 from local <default> (no fetch)
      gx feat -n           Preview without creating anything
    """
    if verbose:
        configure(verbosity=verbose)
    if dry_run:
        set_dry_run(enabled=True)
    check_git_repo()

    if worktree:
        _create_worktree_branch(name, local=local)
    else:
        _create_branch(name, local=local)
