"""Push subcommand for gx."""

from __future__ import annotations

import typer
from rich.prompt import Confirm

from gx.lib.branch import current_branch, default_branch, tracking_branch
from gx.lib.config import config
from gx.lib.console import console, error, set_verbosity, step, warning
from gx.lib.git import check_git_repo, get_dry_run, git, set_dry_run
from gx.lib.options import DRY_RUN_OPTION, VERBOSE_OPTION

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

app = typer.Typer(rich_markup_mode="rich", context_settings=CONTEXT_SETTINGS)


def _count_dirty_files() -> tuple[int, int]:
    """Count modified/staged and untracked files in the working tree.

    Returns:
        (modified, untracked) counts from `git status --porcelain`.
    """
    result = git("status", "--porcelain")
    if not result.success or not result.stdout:
        return (0, 0)

    modified = 0
    untracked = 0
    for line in result.stdout.splitlines():
        if line.startswith("??"):
            untracked += 1
        else:
            modified += 1

    return (modified, untracked)


def _resolve_push_target(branch: str) -> tuple[str, str]:
    """Determine the remote and branch to push to.

    Use the configured tracking branch if available, otherwise fall back to
    origin and the given branch name. The --set-upstream flag on the push
    command will establish tracking on first push.

    Args:
        branch: The current local branch name (already validated as non-None).
    """
    tracking = tracking_branch()
    if tracking is not None:
        return tracking

    return (config.remote_name, branch)


def _warn_dirty_tree() -> None:
    """Print a warning about uncommitted changes that won't be pushed."""
    modified, untracked = _count_dirty_files()

    if modified == 0 and untracked == 0:
        return

    parts: list[str] = []
    if modified > 0:
        parts.append(f"{modified} modified file{'s' if modified != 1 else ''}")
    if untracked > 0:
        parts.append(f"{untracked} untracked file{'s' if untracked != 1 else ''}")

    warning(f"{' and '.join(parts)} won't be included in this push.")


def _print_summary(
    remote_ref_before: str | None, remote: str, remote_branch: str, default: str
) -> None:
    """Print a summary of commits that were pushed (or would be pushed in dry-run).

    Args:
        remote_ref_before: SHA of remote tracking ref before push, or None for first push.
        remote: The remote name.
        remote_branch: The remote branch name.
        default: The default branch name, used as fallback range for first pushes.
    """
    if remote_ref_before is not None:
        log_range = f"{remote_ref_before}..HEAD"
    else:
        log_range = f"{default}..HEAD"

    log_result = git("log", "--oneline", log_range)
    if not log_result.success or not log_result.stdout:
        return

    commits = log_result.stdout.splitlines()
    verb = "Would push" if get_dry_run() else "Push"
    console.print(
        f"[step.success]✓[/] [step.message]{verb} {len(commits)} commit(s) "
        f"to {remote}/{remote_branch}[/]"
    )
    for commit in commits:
        console.print(f"  [sub.pipe]│[/] {commit}")


FORCE_OPTION: bool = typer.Option(
    False,  # noqa: FBT003
    "--force",
    "-f",
    help="Force push using --force-with-lease (safer than --force). Skips the default-branch confirmation prompt.",
)

TAGS_OPTION: bool = typer.Option(
    False,  # noqa: FBT003
    "--tags",
    "-t",
    help="Include all local tags in the push.",
)


@app.callback(invoke_without_command=True)
def push(
    ctx: typer.Context,  # noqa: ARG001
    verbose: int = VERBOSE_OPTION,
    dry_run: bool = DRY_RUN_OPTION,  # noqa: FBT001
    force: bool = FORCE_OPTION,  # noqa: FBT001
    tags: bool = TAGS_OPTION,  # noqa: FBT001
) -> None:
    """Push commits to the remote tracking branch.

    Pushes the current branch to its configured upstream, or to origin/<branch> if no upstream is set. Automatically sets up tracking on first push.

    [bold]Safety guards:[/bold]

    - Warns about uncommitted or untracked files that won't be included
    - Asks for confirmation before pushing directly to the default branch (main/master)
    - Uses --force-with-lease instead of --force to prevent overwriting others' work

    [bold]Examples:[/bold]

      gx push              Push current branch
      gx push -f           Force push with lease
      gx push -t           Push commits and all tags
      gx push -n           Preview what would be pushed
    """
    if verbose:
        set_verbosity(verbose)
    if dry_run:
        set_dry_run(enabled=True)
    check_git_repo()

    branch = current_branch()
    if branch is None:
        error("Cannot push in detached HEAD state.")
        raise typer.Exit(1)

    _warn_dirty_tree()

    default = default_branch()
    if (
        not force
        and branch == default
        and not Confirm.ask(f"You're about to push directly to {default}. Continue?")
    ):
        raise typer.Exit(0)

    remote, remote_branch = _resolve_push_target(branch)

    remote_ref_result = git("rev-parse", f"{remote}/{remote_branch}")
    remote_ref_before = remote_ref_result.stdout if remote_ref_result.success else None

    push_args = ["push", "--set-upstream", remote, remote_branch]
    if force:
        push_args.append("--force-with-lease")
    if tags:
        push_args.append("--tags")

    with step(f"Push to {remote}/{remote_branch}"):
        git(*push_args, timeout=120).raise_on_error()

    _print_summary(remote_ref_before, remote, remote_branch, default)
