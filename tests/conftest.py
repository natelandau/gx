"""Fixtures and configuration for the tests."""

from __future__ import annotations

import subprocess
import uuid
from typing import TYPE_CHECKING

import pytest

from gx.lib.console import set_verbosity
from gx.lib.git import set_dry_run

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    """Reset verbosity and dry-run after each test."""
    yield
    set_verbosity(0)
    set_dry_run(enabled=False)


@pytest.fixture
def tmp_git_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create an isolated git repo with a local bare remote.

    Sets up:
    - A bare remote at tmp_path/remote.git
    - A cloned working repo at tmp_path/repo
    - An initial commit with README.md and .gitignore (ignoring .worktrees/)
    - Git user config for commits
    - Process cwd set to the repo

    Returns:
        Path to the working repo directory.
    """
    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"

    _run_git("init", "-b", "main", "--bare", str(remote))
    _run_git("clone", str(remote), str(repo))

    _run_git("config", "user.name", "Test", cwd=repo)
    _run_git("config", "user.email", "test@test.com", cwd=repo)

    (repo / "README.md").write_text("init")
    (repo / ".gitignore").write_text(".worktrees/\n")
    _run_git("add", ".", cwd=repo)
    _run_git("commit", "-m", "init", cwd=repo)
    _run_git("push", "-u", "origin", "main", cwd=repo)

    monkeypatch.chdir(repo)
    return repo


def _run_git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run a git command for test setup. Raises on failure."""
    return subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )


def create_tmp_branch(repo: Path, name: str) -> None:
    """Create and check out a new branch."""
    _run_git("checkout", "-b", name, cwd=repo)


def checkout_tmp_branch(repo: Path, name: str) -> None:
    """Check out an existing branch."""
    _run_git("checkout", name, cwd=repo)


def create_tmp_commit(
    repo: Path, message: str = "test commit", filename: str | None = None
) -> None:
    """Create a file, stage, and commit. Auto-generates filename if not given."""
    if filename is None:
        filename = f"file-{uuid.uuid4().hex[:8]}.txt"
    (repo / filename).write_text(f"content for {filename}\n")
    _run_git("add", filename, cwd=repo)
    _run_git("commit", "-m", message, cwd=repo)


def push_tmp_branch(repo: Path, name: str | None = None) -> None:
    """Push current or named branch to origin with --set-upstream."""
    if name is None:
        _run_git("push", "-u", "origin", "HEAD", cwd=repo)
    else:
        _run_git("push", "-u", "origin", name, cwd=repo)


def merge_tmp_branch(repo: Path, source: str, into: str) -> None:
    """Merge source into target. Checks out `into`, merges, stays on `into`.

    Callers must checkout_tmp_branch() back to desired branch after calling this.
    """
    _run_git("checkout", into, cwd=repo)
    _run_git("merge", source, "--no-ff", "-m", f"Merge {source} into {into}", cwd=repo)


def delete_tmp_remote_branch(repo: Path, name: str) -> None:
    """Delete a branch on the remote and prune tracking refs.

    After this, the local branch will show as [gone] in `git branch -vv`.
    """
    _run_git("push", "origin", "--delete", name, cwd=repo)
    _run_git("fetch", "--prune", cwd=repo)


def create_tmp_worktree(repo: Path, branch: str, worktree_path: Path | None = None) -> Path:
    """Create a git worktree. Returns the worktree path."""
    if worktree_path is None:
        worktree_path = repo / ".worktrees" / branch.replace("/", "-")
    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    _run_git("worktree", "add", str(worktree_path), "-b", branch, cwd=repo)
    return worktree_path


def make_tmp_dirty(repo: Path, filename: str = "dirty.txt") -> None:
    """Create an uncommitted file in the working tree."""
    (repo / filename).write_text("dirty\n")


def create_tmp_stash(repo: Path, branch: str | None = None) -> None:
    """Create a dirty file and stash it.

    If branch is given, checks out that branch first, stashes, then stays on it.
    """
    if branch is not None:
        _run_git("checkout", branch, cwd=repo)
    filename = f"stash-{uuid.uuid4().hex[:8]}.txt"
    (repo / filename).write_text("stash content\n")
    _run_git("add", filename, cwd=repo)
    _run_git("stash", "--include-untracked", cwd=repo)


def detach_tmp_head(repo: Path) -> None:
    """Detach HEAD at the current commit."""
    _run_git("checkout", "--detach", "HEAD", cwd=repo)


def push_tmp_remote_commit(repo: Path) -> None:
    """Simulate a remote commit by cloning into a second working copy and pushing."""
    remote_dir = repo.parent / "remote.git"
    second_clone = repo.parent / "second-clone"
    _run_git("clone", str(remote_dir), str(second_clone))
    _run_git("config", "user.name", "Other", cwd=second_clone)
    _run_git("config", "user.email", "other@test.com", cwd=second_clone)
    (second_clone / "remote-change.txt").write_text("from remote")
    _run_git("add", ".", cwd=second_clone)
    _run_git("commit", "-m", "remote commit", cwd=second_clone)
    _run_git("push", cwd=second_clone)


def create_tmp_divergence(repo: Path, branch: str, main: str = "main") -> None:
    """Create a branch that has diverged from main (both ahead and behind).

    After this call, repo is on `branch` which is ahead of and behind `main`.
    """
    _run_git("checkout", branch, cwd=repo)
    create_tmp_commit(repo, message=f"diverge on {branch}")
    _run_git("checkout", main, cwd=repo)
    create_tmp_commit(repo, message=f"diverge on {main}")
    _run_git("checkout", branch, cwd=repo)
