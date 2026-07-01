"""Integration tests for gx pull command."""

from pathlib import Path

from typer.testing import CliRunner

from gx.cli import app
from tests.conftest import create_tmp_commit, make_tmp_dirty, push_tmp_remote_commit

runner = CliRunner()


class TestPullIntegration:
    """Tests for pull command against real repo."""

    def test_pull_new_commits(self, tmp_git_repo: Path) -> None:
        """Verify pull fetches and shows new commits."""
        push_tmp_remote_commit(tmp_git_repo)
        result = runner.invoke(app, ["pull"])
        assert result.exit_code == 0
        assert "1 new commit(s)" in result.output

    def test_pull_already_up_to_date(self, tmp_git_repo: Path) -> None:
        """Verify pull shows up-to-date when nothing new."""
        result = runner.invoke(app, ["pull"])
        assert result.exit_code == 0
        assert "Already up to date" in result.output

    def test_pull_stashes_dirty_tree(self, tmp_git_repo: Path) -> None:
        """Verify pull stashes and restores dirty working tree."""
        push_tmp_remote_commit(tmp_git_repo)
        make_tmp_dirty(tmp_git_repo)
        result = runner.invoke(app, ["pull"])
        assert result.exit_code == 0
        assert (tmp_git_repo / "dirty.txt").exists()


class TestPullDivergence:
    """Pull routes into the reconcile flow when local and remote diverge."""

    def test_pull_diverged_rebase(self, tmp_git_repo: Path) -> None:
        """Verify pull reconciles a diverged main via --rebase."""
        # Given origin/main and local main have both advanced
        push_tmp_remote_commit(tmp_git_repo)
        create_tmp_commit(tmp_git_repo)
        # When pulling with an explicit rebase strategy
        result = runner.invoke(app, ["pull", "--rebase"])
        # Then it succeeds and reports the divergence was handled
        assert result.exit_code == 0
        assert "diverged" in result.output.lower()

    def test_pull_diverged_ask_non_tty_restores_stash(self, tmp_git_repo: Path) -> None:
        """Verify a diverged pull with no strategy restores the stash before exiting."""
        # Given origin/main and local main have diverged, and the tree is dirty
        push_tmp_remote_commit(tmp_git_repo)
        create_tmp_commit(tmp_git_repo)
        make_tmp_dirty(tmp_git_repo)
        # When pulling with no strategy flag (config default is "ask", stdin is non-tty)
        result = runner.invoke(app, ["pull"])
        # Then it errors, but the stashed changes are restored to disk
        assert result.exit_code == 1
        assert (tmp_git_repo / "dirty.txt").exists()

    def test_pull_diverged_pushes_hint(self, tmp_git_repo: Path) -> None:
        """Verify pull hints to push after reconciling a diverged branch."""
        # Given origin/main and local main have diverged
        push_tmp_remote_commit(tmp_git_repo)
        create_tmp_commit(tmp_git_repo)
        # When pulling with an explicit rebase strategy
        result = runner.invoke(app, ["pull", "--rebase"])
        # Then it succeeds and hints that a push is needed
        assert result.exit_code == 0
        assert "gx push" in result.output
