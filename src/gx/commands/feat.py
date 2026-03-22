"""Feat subcommand for gx."""

import re

import typer

from gx.lib.branch import branch_exists, current_branch, default_branch
from gx.lib.config import config, resolve_worktree_directory
from gx.lib.console import debug, error, set_verbosity, step, warning
from gx.lib.git import check_git_repo, git, repo_root, set_dry_run
from gx.lib.options import DRY_RUN_OPTION, VERBOSE_OPTION
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


def _prepare_feat_branch(name: str | None) -> tuple[str, str]:
    """Run shared guards and return (feat_branch, default_branch_name).

    Check for detached HEAD, fetch the default branch, warn if currently on
    a feat/* branch, resolve the branch name, and verify it doesn't exist.
    """
    branch = current_branch()
    if branch is None:
        error("Cannot create feature branch in detached HEAD state.")
        raise typer.Exit(1)

    default = default_branch()

    with step(f"Fetch latest {default} from {config.remote_name}"):
        git("fetch", config.remote_name, default).raise_on_error()

    if branch.startswith(f"{config.branch_prefix}/"):
        warning(f"Currently on {branch}")

    feat_branch = _resolve_branch_name(name)

    if branch_exists(feat_branch):
        error(f"Branch {feat_branch} already exists.")
        raise typer.Exit(1)

    return feat_branch, default


def _create_branch(name: str | None) -> None:
    """Create a feature branch and switch to it."""
    feat_branch, default = _prepare_feat_branch(name)

    with step(f"Create branch {feat_branch} from {default}"):
        result = git("checkout", "-b", feat_branch, default)
        if not result.success:
            if "would be overwritten" in result.stderr:
                error(
                    "Checkout failed due to uncommitted changes that conflict with the target branch"
                )
                error("Commit or stash your changes first, then try again", detail=True)
            else:
                error(result.stderr or f"Failed to create branch {feat_branch}")
            raise typer.Exit(1)


def _create_worktree_branch(name: str | None) -> None:
    """Create a feature branch in a new worktree."""
    feat_branch, default = _prepare_feat_branch(name)

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
        create_worktree(worktree_path, feat_branch, start_point=default).raise_on_error()
        s.sub(f"Branch {feat_branch} from {default}")


@app.callback(invoke_without_command=True)
def feat(
    ctx: typer.Context,  # noqa: ARG001
    verbose: int = VERBOSE_OPTION,
    dry_run: bool = DRY_RUN_OPTION,  # noqa: FBT001
    name: str | None = NAME_ARGUMENT,
    worktree: bool = WORKTREE_OPTION,  # noqa: FBT001
) -> None:
    """Create a new feature branch from the default branch.

    Fetches the latest default branch (main/master) from origin, then creates a new feat/* branch from it. Without a name, branches are auto-numbered (feat/1, feat/2, ...), filling gaps in the sequence.

    [bold]Branch mode (default):[/bold]

    Creates the branch and switches to it in the current working directory.

    [bold]Worktree mode (-w):[/bold]

    Creates the branch in a new git worktree at .worktrees/feat/<name>. This lets you work on multiple branches simultaneously without stashing. Requires .worktrees/ to be listed in .gitignore.

    [bold]Examples:[/bold]

      gx feat              Create feat/1 (or next available number)
      gx feat login        Create feat/login
      gx feat -w           Create feat/1 in a worktree
      gx feat -w ui        Create feat/ui in a worktree
      gx feat -n           Preview without creating anything
    """
    if verbose:
        set_verbosity(verbose)
    if dry_run:
        set_dry_run(enabled=True)
    check_git_repo()

    if worktree:
        _create_worktree_branch(name)
    else:
        _create_branch(name)
