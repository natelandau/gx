"""Integration tests for the gx integrate command."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from gx.cli import app
from tests.conftest import (
    checkout_tmp_branch,
    create_tmp_branch,
    create_tmp_commit,
    create_tmp_divergence,
    detach_tmp_head,
    make_tmp_dirty,
)

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


def _merge_commit_count(repo: Path) -> int:
    """Return the number of merge commits reachable from HEAD."""
    out = subprocess.run(
        ["git", "rev-list", "--merges", "--count", "HEAD"],  # noqa: S607
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return int(out.stdout.strip())


class TestIntegrateIntegration:
    """Tests for integrate against a real repo."""

    def test_integrate_up_to_date_noop(self, tmp_git_repo: Path) -> None:
        """Verify a no-op when the branch matches its upstream."""
        # When integrating with nothing to do
        result = runner.invoke(app, ["integrate"])
        # Then it succeeds and reports up to date
        assert result.exit_code == 0
        assert "up to date" in result.output.lower()

    def test_integrate_refuses_dirty_tree(self, tmp_git_repo: Path) -> None:
        """Verify integrate refuses to run with uncommitted changes."""
        # Given a dirty tree
        make_tmp_dirty(tmp_git_repo)
        # When integrating
        result = runner.invoke(app, ["integrate"])
        # Then it aborts
        assert result.exit_code == 1
        assert "uncommitted" in result.output.lower() or "dirty" in result.output.lower()

    def test_integrate_ref_rebase(self, tmp_git_repo: Path) -> None:
        """Verify integrating a diverged branch with --rebase succeeds linearly."""
        # Given a feature branch diverged from main
        create_tmp_branch(tmp_git_repo, "feature")
        create_tmp_divergence(tmp_git_repo, "feature")
        # When integrating main into feature via rebase
        result = runner.invoke(app, ["integrate", "--rebase", "main"])
        # Then it succeeds and no merge commit exists
        assert result.exit_code == 0
        assert _merge_commit_count(tmp_git_repo) == 0

    def test_integrate_ref_merge(self, tmp_git_repo: Path) -> None:
        """Verify integrating a diverged branch with --merge creates a merge commit."""
        # Given a feature branch diverged from main
        create_tmp_branch(tmp_git_repo, "feature")
        create_tmp_divergence(tmp_git_repo, "feature")
        # When integrating main into feature via merge
        result = runner.invoke(app, ["integrate", "--merge", "main"])
        # Then it succeeds and a merge commit exists
        assert result.exit_code == 0
        assert _merge_commit_count(tmp_git_repo) >= 1

    def test_integrate_ff_only_on_diverged_errors(self, tmp_git_repo: Path) -> None:
        """Verify --ff-only fails cleanly when the branch has diverged."""
        # Given a feature branch diverged from main
        create_tmp_branch(tmp_git_repo, "feature")
        create_tmp_divergence(tmp_git_repo, "feature")
        # When forcing ff-only
        result = runner.invoke(app, ["integrate", "--ff-only", "main"])
        # Then it errors
        assert result.exit_code == 1
        assert "fast-forward" in result.output.lower()

    def test_integrate_conflicting_flags_error(self, tmp_git_repo: Path) -> None:
        """Verify passing two strategy flags is rejected."""
        # When passing both --rebase and --merge
        result = runner.invoke(app, ["integrate", "--rebase", "--merge", "main"])
        # Then it errors
        assert result.exit_code == 1
        assert "at most one" in result.output.lower()

    def test_integrate_dry_run(self, tmp_git_repo: Path) -> None:
        """Verify dry-run makes no changes to a diverged branch."""
        # Given a feature branch diverged from main
        create_tmp_branch(tmp_git_repo, "feature")
        create_tmp_divergence(tmp_git_repo, "feature")
        # When integrating in dry-run
        result = runner.invoke(app, ["integrate", "--rebase", "-n", "main"])
        # Then it succeeds without error
        assert result.exit_code == 0

    def test_integrate_merge_conflict_left_in_progress(self, tmp_git_repo: Path) -> None:
        """Verify a conflicting merge prints resolution steps and stays in progress."""
        # Given a feature branch and main that both modify README.md differently
        create_tmp_branch(tmp_git_repo, "feature")
        (tmp_git_repo / "README.md").write_text("feature change\n")
        subprocess.run(
            ["git", "commit", "-am", "feature edits README"],  # noqa: S607
            cwd=tmp_git_repo,
            capture_output=True,
            text=True,
            check=True,
        )
        subprocess.run(
            ["git", "checkout", "main"],  # noqa: S607
            cwd=tmp_git_repo,
            capture_output=True,
            text=True,
            check=True,
        )
        (tmp_git_repo / "README.md").write_text("main change\n")
        subprocess.run(
            ["git", "commit", "-am", "main edits README"],  # noqa: S607
            cwd=tmp_git_repo,
            capture_output=True,
            text=True,
            check=True,
        )
        subprocess.run(
            ["git", "checkout", "feature"],  # noqa: S607
            cwd=tmp_git_repo,
            capture_output=True,
            text=True,
            check=True,
        )

        # When integrating main into feature via merge
        result = runner.invoke(app, ["integrate", "--merge", "main"])

        # Then it fails, prints conflict resolution steps, and leaves the merge in progress
        assert result.exit_code == 1
        assert "conflict" in result.output.lower()
        assert "git merge --continue" in result.output.lower()
        merge_head = subprocess.run(
            ["git", "rev-parse", "-q", "--verify", "MERGE_HEAD"],  # noqa: S607
            cwd=tmp_git_repo,
            capture_output=True,
            text=True,
            check=False,
        )
        assert merge_head.returncode == 0

    def test_integrate_ref_with_slash_local_branch_skips_remote_fetch(
        self, tmp_git_repo: Path
    ) -> None:
        """Verify a local branch name containing a slash isn't mistaken for a remote ref.

        A branch like feat/sub (this tool's own naming convention) has no
        remote named "feat"; integrate must not attempt to fetch one.
        """
        # Given a local branch named like a remote-qualified ref, with no "feat" remote
        create_tmp_branch(tmp_git_repo, "feat/sub")
        create_tmp_commit(tmp_git_repo, message="feat/sub commit")
        checkout_tmp_branch(tmp_git_repo, "main")
        # When integrating feat/sub into main
        result = runner.invoke(app, ["integrate", "--ff-only", "feat/sub"])
        # Then it fast-forwards without attempting to fetch a nonexistent "feat" remote
        assert result.exit_code == 0
        assert "fetch from feat" not in result.output.lower()

    def test_integrate_fetch_failure_aborts(self, tmp_git_repo: Path) -> None:
        """Verify integrate aborts cleanly instead of silently ignoring a failed fetch."""
        # Given the origin remote points at an unreachable location
        subprocess.run(
            ["git", "remote", "set-url", "origin", "/nonexistent/path.git"],  # noqa: S607
            cwd=tmp_git_repo,
            capture_output=True,
            text=True,
            check=True,
        )
        # When integrating a remote-qualified ref
        result = runner.invoke(app, ["integrate", "origin/main"])
        # Then it aborts rather than proceeding on stale data
        assert result.exit_code == 1

    def test_integrate_detached_head_errors(self, tmp_git_repo: Path) -> None:
        """Verify integrate errors in detached HEAD state."""
        # Given a detached HEAD
        detach_tmp_head(tmp_git_repo)
        # When integrating
        result = runner.invoke(app, ["integrate"])
        # Then it errors and mentions detached HEAD
        assert result.exit_code == 1
        assert "detached" in result.output.lower()

    def test_integrate_diverged_ask_non_tty_errors(self, tmp_git_repo: Path) -> None:
        """Verify integrate errors with guidance when diverged and no strategy is given."""
        # Given a feature branch diverged from main, no strategy flag, and non-tty stdin
        create_tmp_branch(tmp_git_repo, "feature")
        create_tmp_divergence(tmp_git_repo, "feature")
        # When integrating main into feature with no strategy flag
        result = runner.invoke(app, ["integrate", "main"])
        # Then it errors with guidance on how to choose a strategy
        assert result.exit_code == 1
        assert "no strategy was given" in result.output.lower()

    def test_integrate_no_upstream_noop(self, tmp_git_repo: Path) -> None:
        """Verify integrate is a no-op when branch has no upstream."""
        # Given a new local branch with no upstream
        create_tmp_branch(tmp_git_repo, "orphan")
        # When integrating
        result = runner.invoke(app, ["integrate"])
        # Then it succeeds and indicates nothing to integrate
        assert result.exit_code == 0
        assert "nothing to integrate" in result.output.lower()
