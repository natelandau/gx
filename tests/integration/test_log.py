"""Integration tests for gx log command."""

import pytest
from typer.testing import CliRunner

from gx.cli import app
from gx.lib.config import GxConfig
from tests.conftest import (
    _run_git,
    checkout_tmp_branch,
    create_tmp_branch,
    create_tmp_commit,
    create_tmp_stash,
    create_tmp_worktree,
    merge_tmp_branch,
)

runner = CliRunner()


class TestLogIntegration:
    """Tests for log command against real repo."""

    def test_log_default(self, tmp_git_repo):
        """Verify default log shows commits and exits 0."""
        # Given — repo has initial commit from fixture
        # When
        result = runner.invoke(app, ["log"])
        # Then
        assert result.exit_code == 0
        assert "init" in result.output

    def test_log_count_flag(self, tmp_git_repo):
        """Verify -c flag limits number of commits shown."""
        # Given
        for i in range(5):
            create_tmp_commit(tmp_git_repo, f"commit {i}")
        # When — use count=4 because --all includes origin/main ref
        result = runner.invoke(app, ["log", "-c", "4"])
        # Then
        assert result.exit_code == 0
        assert "commit 4" in result.output
        assert "commit 3" in result.output
        assert "commit 2" in result.output

    def test_log_full(self, tmp_git_repo):
        """Verify --full flag exits 0."""
        # When
        result = runner.invoke(app, ["log", "--full"])
        # Then
        assert result.exit_code == 0

    def test_log_graph(self, tmp_git_repo):
        """Verify --graph flag shows graph characters."""
        # When
        result = runner.invoke(app, ["log", "--graph"])
        # Then
        assert result.exit_code == 0
        assert "◉" in result.output

    def test_log_graph_ascii_style(self, tmp_git_repo, mocker):
        """Verify the ascii style draws only ascii nodes."""
        # Given
        mocker.patch("gx.lib.log_graph.config", GxConfig(graph_style="ascii"))
        # When
        result = runner.invoke(app, ["log", "--graph"])
        # Then
        assert result.exit_code == 0
        assert "@" in result.output
        assert "◉" not in result.output
        assert "●" not in result.output

    def test_log_graph_merge_renders_merge_node(self, tmp_git_repo):
        """Verify a non-fast-forward merge draws the merge node."""
        # Given a feature branch merged into main, with a commit on top
        home = _run_git("branch", "--show-current", cwd=tmp_git_repo).stdout.strip()
        create_tmp_branch(tmp_git_repo, "feature")
        create_tmp_commit(tmp_git_repo, "feature work")
        checkout_tmp_branch(tmp_git_repo, home)
        create_tmp_commit(tmp_git_repo, "main work")
        merge_tmp_branch(tmp_git_repo, "feature", home)
        create_tmp_commit(tmp_git_repo, "after merge")
        # When
        result = runner.invoke(app, ["log", "--graph"])
        # Then
        assert result.exit_code == 0
        assert "◎" in result.output

    def test_log_graph_octopus_merge(self, tmp_git_repo):
        """Verify an octopus merge draws a merge node with a fan-out."""
        # Given three single-commit branches merged at once, with a commit on top
        home = _run_git("branch", "--show-current", cwd=tmp_git_repo).stdout.strip()
        for name in ("b1", "b2", "b3"):
            create_tmp_branch(tmp_git_repo, name)
            create_tmp_commit(tmp_git_repo, f"work {name}")
            checkout_tmp_branch(tmp_git_repo, home)
        _run_git("merge", "--no-ff", "-m", "octopus", "b1", "b2", "b3", cwd=tmp_git_repo)
        create_tmp_commit(tmp_git_repo, "after octopus")
        # When
        result = runner.invoke(app, ["log", "--graph"])
        # Then
        assert result.exit_code == 0
        assert "◎─┬─" in result.output
        for name in ("b1", "b2", "b3"):
            assert f"work {name}" in result.output

    def test_log_graph_shallow_clone(self, tmp_git_repo, tmp_path, monkeypatch):
        """Verify a shallow clone renders without error."""
        # Given a shallow clone of a repo with several commits
        for i in range(5):
            create_tmp_commit(tmp_git_repo, f"history {i}")
        clone = tmp_path / "shallow"
        _run_git("clone", "--depth", "2", f"file://{tmp_git_repo}", str(clone))
        monkeypatch.chdir(clone)
        # When
        result = runner.invoke(app, ["log", "--graph"])
        # Then
        assert result.exit_code == 0
        assert "history 4" in result.output
        assert "history 3" in result.output

    def test_log_graph_includes_other_branches(self, tmp_git_repo):
        """Verify --graph shows commits on branches other than HEAD."""
        # Given
        worktree = create_tmp_worktree(tmp_git_repo, "feature")
        create_tmp_commit(worktree, "feature work")
        # When
        result = runner.invoke(app, ["log", "--graph"])
        # Then
        assert result.exit_code == 0
        assert "feature work" in result.output

    @pytest.mark.parametrize("args", [["log"], ["log", "--graph"]])
    def test_log_excludes_stash_commits(self, tmp_git_repo, args):
        """Verify stash WIP and index commits are not shown as history."""
        # Given
        create_tmp_stash(tmp_git_repo)
        # When
        result = runner.invoke(app, args)
        # Then
        assert result.exit_code == 0
        assert "WIP on" not in result.output
        assert "index on" not in result.output

    def test_log_graph_reaches_fork_point(self, tmp_git_repo):
        """Verify --graph shows where a branch forks even past the commit count."""
        # Given a branch forked from "base" with more commits than -c shows
        create_tmp_commit(tmp_git_repo, "base")
        worktree = create_tmp_worktree(tmp_git_repo, "feature")
        for i in range(10):
            create_tmp_commit(worktree, f"feature {i}")
        create_tmp_commit(tmp_git_repo, "main after fork")
        # When
        result = runner.invoke(app, ["log", "--graph", "-c", "3"])
        # Then
        assert result.exit_code == 0
        assert "─╯" in result.output
        assert "base" in result.output
        assert "main after fork" in result.output
        assert "feature 9" in result.output
        assert "more commits" in result.output

    def test_log_graph_full_shows_every_commit(self, tmp_git_repo):
        """Verify --graph --full disables folding."""
        # Given
        worktree = create_tmp_worktree(tmp_git_repo, "feature")
        for i in range(10):
            create_tmp_commit(worktree, f"feature {i}")
        create_tmp_commit(tmp_git_repo, "main after fork")
        # When
        result = runner.invoke(app, ["log", "--graph", "--full"])
        # Then
        assert result.exit_code == 0
        assert "more commits" not in result.output
        for i in range(10):
            assert f"feature {i}" in result.output

    def test_log_graph_detached_head_without_default_branch(self, tmp_git_repo):
        """Verify --graph works when no default branch can be detected."""
        # Given a detached HEAD in a repo whose only branch has a non-standard name
        _run_git("remote", "remove", "origin", cwd=tmp_git_repo)
        _run_git("branch", "-m", "trunk", cwd=tmp_git_repo)
        create_tmp_commit(tmp_git_repo, "second")
        _run_git("checkout", "--detach", "HEAD~1", cwd=tmp_git_repo)
        # When
        result = runner.invoke(app, ["log", "--graph"])
        # Then
        assert result.exit_code == 0
        assert "second" in result.output

    def test_log_graph_bounds_older_unrelated_history(self, tmp_git_repo, monkeypatch):
        """Verify an older orphan history does not show in full in the fork window."""
        # Given an orphan branch older than a feature branch that forks far back
        home = _run_git("branch", "--show-current", cwd=tmp_git_repo).stdout.strip()
        _run_git("checkout", "--orphan", "pages", cwd=tmp_git_repo)
        _run_git("rm", "-rq", "--cached", ".", cwd=tmp_git_repo)
        for i in range(5):
            monkeypatch.setenv("GIT_COMMITTER_DATE", f"@{1_000_000_000 + i}")
            create_tmp_commit(tmp_git_repo, f"orphan {i}")
        monkeypatch.delenv("GIT_COMMITTER_DATE")
        _run_git("checkout", "-f", home, cwd=tmp_git_repo)
        for i in range(4):
            create_tmp_commit(tmp_git_repo, f"base {i}")
        worktree = create_tmp_worktree(tmp_git_repo, "feature")
        create_tmp_commit(worktree, "feature work")
        for i in range(20):
            create_tmp_commit(tmp_git_repo, f"main {i}")
        # When
        result = runner.invoke(app, ["log", "--graph", "--full", "-c", "3"])
        # Then
        assert result.exit_code == 0
        assert "feature work" in result.output
        assert "orphan" not in result.output

    def test_log_graph_keeps_old_commits_of_a_merged_branch(self, tmp_git_repo, monkeypatch):
        """Verify a deleted branch's old commits still show below the merge that brought them in."""
        # Given a side branch with old commits, merged after newer main work, then deleted
        home = _run_git("branch", "--show-current", cwd=tmp_git_repo).stdout.strip()
        _run_git("checkout", "-b", "old", cwd=tmp_git_repo)
        for i in range(2):
            monkeypatch.setenv("GIT_COMMITTER_DATE", f"@{1_000_000_000 + i}")
            create_tmp_commit(tmp_git_repo, f"old work {i}")
        monkeypatch.delenv("GIT_COMMITTER_DATE")
        _run_git("checkout", home, cwd=tmp_git_repo)
        for i in range(6):
            create_tmp_commit(tmp_git_repo, f"main {i}")
        _run_git("merge", "--no-ff", "old", "-m", "merge old", cwd=tmp_git_repo)
        _run_git("branch", "-D", "old", cwd=tmp_git_repo)
        worktree = create_tmp_worktree(tmp_git_repo, "feature")
        create_tmp_commit(worktree, "feature work")
        # When
        result = runner.invoke(app, ["log", "--graph", "--full", "-c", "3"])
        # Then
        assert result.exit_code == 0
        assert "merge old" in result.output
        assert "old work 0" in result.output
        assert "old work 1" in result.output

    def test_log_graph_shows_recent_unrelated_history(self, tmp_git_repo):
        """Verify an orphan history newer than the fork window still shows."""
        # Given a feature branch and an orphan branch with recent commits
        home = _run_git("branch", "--show-current", cwd=tmp_git_repo).stdout.strip()
        for i in range(3):
            create_tmp_commit(tmp_git_repo, f"base {i}")
        worktree = create_tmp_worktree(tmp_git_repo, "feature")
        create_tmp_commit(worktree, "feature work")
        _run_git("checkout", "--orphan", "pages", cwd=tmp_git_repo)
        _run_git("rm", "-rq", "--cached", ".", cwd=tmp_git_repo)
        create_tmp_commit(tmp_git_repo, "orphan page")
        _run_git("checkout", "-f", home, cwd=tmp_git_repo)
        create_tmp_commit(tmp_git_repo, "main after fork")
        # When
        result = runner.invoke(app, ["log", "--graph", "--full", "-c", "2"])
        # Then
        assert result.exit_code == 0
        assert "orphan page" in result.output
        assert "feature work" in result.output

    def test_log_graph_trunk_lane_without_local_default_branch(self, tmp_git_repo):
        """Verify the trunk lane still renders when the local default branch is gone."""
        # Given a feature branch checked out and local main deleted, leaving origin/main
        _run_git("remote", "set-head", "origin", "main", cwd=tmp_git_repo)
        create_tmp_branch(tmp_git_repo, "feature")
        create_tmp_commit(tmp_git_repo, "feature one")
        create_tmp_commit(tmp_git_repo, "feature two")
        _run_git("branch", "-D", "main", cwd=tmp_git_repo)
        # When
        result = runner.invoke(app, ["log", "--graph"])
        # Then the feature commits sit right of the trunk lane
        assert result.exit_code == 0
        feature_line = next(line for line in result.output.splitlines() if "feature two" in line)
        init_line = next(line for line in result.output.splitlines() if " init" in line)
        assert feature_line.startswith("  ")
        assert not init_line.startswith(" ")

    def test_log_graph_empty_repo(self, empty_git_repo):
        """Verify --graph in a repo with no commits warns instead of crashing."""
        # When
        result = runner.invoke(app, ["log", "--graph"])
        # Then
        assert result.exit_code == 0
        assert "No commits found" in result.output
