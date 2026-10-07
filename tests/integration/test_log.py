"""Integration tests for gx log command."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from gx.cli import app
from gx.lib import log_graph
from gx.lib.config import GxConfig
from tests.conftest import (
    _run_git,
    checkout_tmp_branch,
    create_tmp_branch,
    create_tmp_commit,
    create_tmp_stash,
    create_tmp_worktree,
    delete_tmp_remote_branch,
    merge_tmp_branch,
    push_tmp_branch,
)

runner = CliRunner()


class TestLogIntegration:
    """Tests for log command against real repo."""

    def test_log_default(self, tmp_git_repo):
        """Verify default log shows commits and exits 0."""
        # Given - repo has initial commit from fixture
        # When
        result = runner.invoke(app, ["log"])
        # Then
        assert result.exit_code == 0
        assert "init" in result.output

    @staticmethod
    def _old_fork(repo: Path) -> None:
        """Fork a branch from the root, then add six commits to main."""
        create_tmp_branch(repo, "old")
        create_tmp_commit(repo, "old work")
        checkout_tmp_branch(repo, "main")
        for i in range(6):
            create_tmp_commit(repo, f"cap-{i}")

    def test_log_graph_explicit_count_caps_commits(self, tmp_git_repo):
        """Verify an explicit -c caps the graph even when a fork point lies further back."""
        # Given
        self._old_fork(tmp_git_repo)
        # When
        result = runner.invoke(app, ["log", "-g", "-c", "5"])
        # Then
        assert result.exit_code == 0
        shown = [line for line in result.output.splitlines() if "cap-" in line]
        assert len(shown) == 5
        assert all(any(f"cap-{i}" in line for i in (1, 2, 3, 4, 5)) for line in shown)
        assert "old work" not in result.output
        assert "more commits" not in result.output

    def test_log_graph_default_count_reaches_fork_point(self, tmp_git_repo):
        """Verify the graph without -c still reaches back to every branch's fork point."""
        # Given
        self._old_fork(tmp_git_repo)
        # When
        result = runner.invoke(app, ["log", "-g", "--full"])
        # Then
        assert result.exit_code == 0
        assert sum("cap-" in line for line in result.output.splitlines()) == 6
        assert "old work" in result.output

    def test_log_count_flag(self, tmp_git_repo):
        """Verify -c flag limits number of commits shown."""
        # Given
        for i in range(5):
            create_tmp_commit(tmp_git_repo, f"commit {i}")
        # When - use count=4 because --all includes origin/main ref
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

    def test_log_graph_reaches_fork_point(self, tmp_git_repo, monkeypatch):
        """Verify --graph shows where a branch forks even past the commit count."""
        # Given a branch forked from "base" with more commits than -c shows
        create_tmp_commit(tmp_git_repo, "base")
        worktree = create_tmp_worktree(tmp_git_repo, "feature")
        for i in range(10):
            create_tmp_commit(worktree, f"feature {i}")
        create_tmp_commit(tmp_git_repo, "main after fork")
        # When
        monkeypatch.setattr("gx.commands.log.DEFAULT_COUNT", 3)
        result = runner.invoke(app, ["log", "--graph"])
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
        monkeypatch.setattr("gx.commands.log.DEFAULT_COUNT", 3)
        result = runner.invoke(app, ["log", "--graph", "--full"])
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
        monkeypatch.setattr("gx.commands.log.DEFAULT_COUNT", 3)
        result = runner.invoke(app, ["log", "--graph", "--full"])
        # Then
        assert result.exit_code == 0
        assert "merge old" in result.output
        assert "old work 0" in result.output
        assert "old work 1" in result.output

    def test_log_graph_shows_recent_unrelated_history(self, tmp_git_repo, monkeypatch):
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
        monkeypatch.setattr("gx.commands.log.DEFAULT_COUNT", 2)
        result = runner.invoke(app, ["log", "--graph", "--full"])
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

    def test_log_graph_legend_lists_branches(self, tmp_git_repo):
        """Verify the graph ends with a blank line and a legend naming each branch."""
        # Given a feature worktree with a commit
        worktree = create_tmp_worktree(tmp_git_repo, "feature")
        (worktree / "f.txt").write_text("f")
        _run_git("add", ".", cwd=worktree)
        _run_git("commit", "-m", "feature work", cwd=worktree)
        # When
        result = runner.invoke(app, ["log", "--graph"])
        # Then
        assert result.exit_code == 0
        lines = result.output.rstrip("\n").splitlines()
        assert lines[-1].startswith(("● main", "* main"))
        assert "feature" in lines[-1]
        assert lines[-2] == ""

    def test_log_graph_legend_without_color(self, tmp_git_repo):
        """Verify the checked-out branch is marked in the legend when color is off."""
        # Given a feature branch checked out
        create_tmp_branch(tmp_git_repo, "feature")
        create_tmp_commit(tmp_git_repo, "feature one")
        # When
        result = runner.invoke(app, ["log", "--graph"])
        # Then
        assert result.exit_code == 0
        assert "feature (current)" in result.output.rstrip("\n").splitlines()[-1]

    def test_log_graph_detached_head_marks_no_current_branch(self, tmp_git_repo):
        """Verify a detached HEAD renders and no branch is marked current."""
        # Given a feature branch and HEAD detached on main
        create_tmp_branch(tmp_git_repo, "feature")
        create_tmp_commit(tmp_git_repo, "feature one")
        checkout_tmp_branch(tmp_git_repo, "main")
        _run_git("checkout", "--detach", cwd=tmp_git_repo)
        # When
        result = runner.invoke(app, ["log", "--graph"])
        # Then
        assert result.exit_code == 0
        assert "feature" in result.output.rstrip("\n").splitlines()[-1]
        assert "(current)" not in result.output
        assert "[HEAD]" in result.output

    def test_log_graph_unborn_orphan_checkout_keeps_default(self, tmp_git_repo, mocker):
        """Verify an unborn orphan checkout still resolves main as the default branch."""
        # Given a feature branch with a commit and an unborn orphan checkout
        create_tmp_branch(tmp_git_repo, "feature")
        create_tmp_commit(tmp_git_repo, "feature one")
        checkout_tmp_branch(tmp_git_repo, "main")
        _run_git("checkout", "--orphan", "scratch", cwd=tmp_git_repo)
        build = mocker.spy(log_graph, "build_log_context")
        # When
        result = runner.invoke(app, ["log", "--graph"])
        # Then main is the colorless default and leads the legend
        assert result.exit_code == 0
        context = build.spy_return
        assert context.default == "main"
        assert context.branches["main"].is_default
        assert context.branches["main"].color == ""
        assert result.output.rstrip("\n").splitlines()[-1].startswith("● main")

    def test_log_graph_legend_with_remote_default(self, tmp_git_repo):
        """Verify the legend names the remote-tracking default when local main is gone."""
        # Given a feature branch checked out and local main deleted
        _run_git("remote", "set-head", "origin", "main", cwd=tmp_git_repo)
        create_tmp_branch(tmp_git_repo, "feature")
        create_tmp_commit(tmp_git_repo, "feature one")
        _run_git("branch", "-D", "main", cwd=tmp_git_repo)
        # When
        result = runner.invoke(app, ["log", "--graph"])
        # Then
        assert result.exit_code == 0
        legend = result.output.rstrip("\n").splitlines()[-1]
        assert legend.startswith("● origin/main")

    def test_log_graph_single_branch_has_no_legend(self, tmp_git_repo):
        """Verify a repo with only the default branch prints no legend."""
        # When
        result = runner.invoke(app, ["log", "--graph"])
        # Then the last line is a graph line
        assert result.exit_code == 0
        assert "init" in result.output.rstrip("\n").splitlines()[-1]

    def test_log_graph_empty_repo(self, empty_git_repo):
        """Verify --graph in a repo with no commits warns instead of crashing."""
        # When
        result = runner.invoke(app, ["log", "--graph"])
        # Then
        assert result.exit_code == 0
        assert "No commits found" in result.output

    @staticmethod
    def _badges_repo(repo: Path) -> None:
        """Build main (tagged, in sync), feat (pushed then one local commit), and solo."""
        _run_git("tag", "v1", cwd=repo)
        create_tmp_branch(repo, "solo")
        create_tmp_commit(repo, "solo work")
        checkout_tmp_branch(repo, "main")
        create_tmp_branch(repo, "feat")
        create_tmp_commit(repo, "one")
        push_tmp_branch(repo, "feat")
        create_tmp_commit(repo, "two")

    @pytest.mark.parametrize(
        ("style", "ahead", "sync", "tag"),
        [("unicode", "↑1", "⇅", "◆ v1"), ("ascii", "^1", "=", "# v1")],
    )
    def test_log_graph_badges_and_sync(self, tmp_git_repo, mocker, style, ahead, sync, tag):
        """Verify badges, sync suffixes, tags, and the local legend mark render end to end."""
        # Given main in sync with origin/main and tagged, feat ahead of its upstream, solo unpushed
        mocker.patch.object(log_graph, "config", GxConfig(graph_style=style))
        self._badges_repo(tmp_git_repo)
        # When
        result = runner.invoke(app, ["log", "--graph"])
        # Then
        assert result.exit_code == 0
        assert f"[feat {ahead}]" in result.output
        assert f"(main {sync})" in result.output
        assert tag in result.output
        assert "(solo)" in result.output
        assert "origin/main" not in result.output
        assert "solo local" in result.output.splitlines()[-1]

    @pytest.mark.parametrize(("style", "marker"), [("unicode", "↑"), ("ascii", "+")])
    def test_log_graph_marks_only_unpushed_commits(self, tmp_git_repo, mocker, style, marker):
        """Verify only commits missing from the upstream carry the unpushed marker."""
        # Given feat pushed at "one" with "two" committed locally
        mocker.patch.object(log_graph, "config", GxConfig(graph_style=style))
        self._badges_repo(tmp_git_repo)
        # When
        result = runner.invoke(app, ["log", "--graph"])
        # Then
        assert result.exit_code == 0
        lines = result.output.splitlines()
        assert len([line for line in lines if f"{marker} " in line and "two" in line]) == 1
        assert not any(f"{marker} " in line and "one" in line for line in lines)

    def test_log_graph_branch_tracking_local_branch_is_not_unpushed(self, tmp_git_repo, mocker):
        """Verify a branch tracking a local branch marks no pushed commit and is legend-local."""
        # Given stacked on a pushed feat, tracking local main
        mocker.patch.object(log_graph, "config", GxConfig(graph_style="unicode"))
        create_tmp_branch(tmp_git_repo, "feat")
        create_tmp_commit(tmp_git_repo, "one")
        push_tmp_branch(tmp_git_repo, "feat")
        create_tmp_branch(tmp_git_repo, "stacked")
        create_tmp_commit(tmp_git_repo, "two")
        _run_git("branch", "-u", "main", "stacked", cwd=tmp_git_repo)
        # When
        result = runner.invoke(app, ["log", "--graph"])
        # Then
        assert result.exit_code == 0
        assert not any("↑ " in line for line in result.output.splitlines())
        assert "stacked (current) local" in result.output.splitlines()[-1]

    def test_log_graph_remote_name_with_slash(self, tmp_git_repo):
        """Verify refs of a remote named with a slash render as remote badges."""
        # Given a remote named team/fork with a fetched branch
        remote = tmp_git_repo.parent / "fork.git"
        _run_git("init", "--bare", str(remote), cwd=tmp_git_repo)
        _run_git("remote", "add", "team/fork", str(remote), cwd=tmp_git_repo)
        _run_git("push", "team/fork", "main:dev", cwd=tmp_git_repo)
        _run_git("fetch", "team/fork", cwd=tmp_git_repo)
        create_tmp_branch(tmp_git_repo, "feat")
        create_tmp_commit(tmp_git_repo, "one")
        # When
        result = runner.invoke(app, ["log", "--graph"])
        # Then the ref is a remote badge, not a local `(team/fork/dev)` branch
        assert result.exit_code == 0
        assert "team/fork/dev" in result.output
        assert "(team/fork/dev" not in result.output

    def test_log_graph_gone_upstream_renders(self, tmp_git_repo):
        """Verify a branch whose upstream was deleted on the remote still renders."""
        # Given feat pushed, then deleted on the remote
        create_tmp_branch(tmp_git_repo, "feat")
        create_tmp_commit(tmp_git_repo, "one")
        push_tmp_branch(tmp_git_repo, "feat")
        delete_tmp_remote_branch(tmp_git_repo, "feat")
        # When
        result = runner.invoke(app, ["log", "--graph"])
        # Then
        assert result.exit_code == 0
        feat_line = next(line for line in result.output.splitlines() if "[feat" in line)
        assert "[feat]" in feat_line
        assert "↑" not in feat_line
        assert "↓" not in feat_line

    @pytest.mark.parametrize(
        ("style", "ahead", "sync", "tag"),
        [("unicode", "↑1", "⇅", "◆ v1"), ("ascii", "^1", "=", "# v1")],
    )
    def test_log_graph_full_keeps_badges_and_legend(
        self, tmp_git_repo, mocker, style, ahead, sync, tag
    ):
        """Verify --full keeps the badges, the tag, and the legend."""
        # Given the badges repo
        mocker.patch.object(log_graph, "config", GxConfig(graph_style=style))
        self._badges_repo(tmp_git_repo)
        # When
        result = runner.invoke(app, ["log", "--graph", "--full"])
        # Then
        assert result.exit_code == 0
        assert f"[feat {ahead}]" in result.output
        assert f"(main {sync})" in result.output
        assert tag in result.output
        assert "solo local" in result.output.splitlines()[-1]

    @staticmethod
    def _worktrees_stale_repo(repo: Path) -> Path:
        """Build main, a merged pushed old-spike, stacked feat-api/feat-auth, and a dirty fix-log worktree.

        Returns:
            Path: The fix-log worktree.
        """
        create_tmp_branch(repo, "old-spike")
        create_tmp_commit(repo, "spike")
        push_tmp_branch(repo, "old-spike")
        merge_tmp_branch(repo, "old-spike", "main")
        create_tmp_branch(repo, "feat-api")
        create_tmp_commit(repo, "api")
        push_tmp_branch(repo, "feat-api")
        create_tmp_branch(repo, "feat-auth")
        create_tmp_commit(repo, "auth one")
        push_tmp_branch(repo, "feat-auth")
        create_tmp_commit(repo, "auth two")
        checkout_tmp_branch(repo, "main")
        worktree = create_tmp_worktree(repo, "fix-log")
        create_tmp_commit(worktree, "log fix")
        (worktree / "scratch.txt").write_text("x\n")
        checkout_tmp_branch(repo, "feat-auth")
        return worktree

    @pytest.mark.parametrize(
        ("style", "node", "wt", "stale"),
        [
            ("unicode", "◌", "⌂ ", "(old-spike ⇅ merged)"),
            ("ascii", "o", "wt:", "(old-spike = merged)"),
        ],
    )
    def test_log_graph_worktrees_and_stale(self, tmp_git_repo, mocker, style, node, wt, stale):
        """Verify worktree marks, the pseudo-row, the merged suffix, and the clean hint."""
        # Given
        mocker.patch.object(log_graph, "config", GxConfig(graph_style=style, nerd_font=False))
        self._worktrees_stale_repo(tmp_git_repo)
        # When
        result = runner.invoke(app, ["log", "--graph"])
        # Then
        lines = result.output.rstrip("\n").splitlines()
        assert result.exit_code == 0
        pseudo = [i for i, line in enumerate(lines) if "uncommitted: 1 untracked" in line]
        assert len(pseudo) == 1
        assert lines[pseudo[0]].lstrip(" |│").startswith(node)
        assert "fix-log" in lines[pseudo[0] + 1]
        assert f"(fix-log {wt}" in result.output
        assert stale in result.output
        assert lines[-1] == "1 branch can be cleaned up: gx clean"
        assert "feat-auth (current)" in lines[-2]

    def test_log_graph_dirty_current_branch(self, tmp_git_repo, mocker):
        """Verify a dirty current branch gets a pseudo-row above its tip."""
        # Given a staged new file and a modified tracked file
        mocker.patch.object(log_graph, "config", GxConfig(graph_style="unicode", nerd_font=False))
        create_tmp_branch(tmp_git_repo, "feat")
        create_tmp_commit(tmp_git_repo, "one")
        (tmp_git_repo / "staged.txt").write_text("s\n")
        _run_git("add", "staged.txt", cwd=tmp_git_repo)
        (tmp_git_repo / "README.md").write_text("changed\n")
        # When
        result = runner.invoke(app, ["log", "--graph"])
        # Then
        lines = result.output.splitlines()
        assert result.exit_code == 0
        assert "uncommitted: 1 staged, 1 modified" in result.output
        idx = next(i for i, line in enumerate(lines) if "uncommitted:" in line)
        assert lines[idx].lstrip(" |│").startswith("◌")
        assert "[feat" in lines[idx + 1]

    def test_log_graph_from_inside_worktree(self, tmp_git_repo, monkeypatch, mocker):
        """Verify main shows a worktree suffix named after the main repo when run from a worktree."""
        # Given
        mocker.patch.object(log_graph, "config", GxConfig(graph_style="unicode", nerd_font=False))
        worktree = self._worktrees_stale_repo(tmp_git_repo)
        checkout_tmp_branch(tmp_git_repo, "main")
        push_tmp_branch(tmp_git_repo)
        monkeypatch.chdir(worktree)
        # When
        result = runner.invoke(app, ["log", "--graph"])
        # Then
        assert result.exit_code == 0
        assert f"(main ⇅ ⌂ {tmp_git_repo.name})" in result.output

    def test_log_graph_never_pushed_branch_not_flagged(self, tmp_git_repo, mocker):
        """Verify a merged-looking branch without an upstream is not flagged stale."""
        # Given a never-pushed branch with no commits of its own
        mocker.patch.object(log_graph, "config", GxConfig(graph_style="unicode", nerd_font=False))
        create_tmp_branch(tmp_git_repo, "new")
        checkout_tmp_branch(tmp_git_repo, "main")
        # When
        result = runner.invoke(app, ["log", "--graph"])
        # Then
        assert result.exit_code == 0
        assert "(new)" in result.output
        assert "merged" not in result.output
        assert "gx clean" not in result.output

    @pytest.mark.parametrize(("style", "wt"), [("unicode", "⌂ "), ("ascii", "wt:")])
    def test_log_graph_full_keeps_pseudo_row_and_hint(self, tmp_git_repo, mocker, style, wt):
        """Verify --full keeps the pseudo-row, worktree mark, legend, and the clean hint."""
        # Given
        mocker.patch.object(log_graph, "config", GxConfig(graph_style=style, nerd_font=False))
        self._worktrees_stale_repo(tmp_git_repo)
        # When
        result = runner.invoke(app, ["log", "--graph", "--full"])
        # Then
        lines = result.output.rstrip("\n").splitlines()
        assert result.exit_code == 0
        pseudo = [i for i, line in enumerate(lines) if "uncommitted: 1 untracked" in line]
        assert len(pseudo) == 1
        assert "fix-log" in lines[pseudo[0] + 1]
        assert f"(fix-log {wt}" in result.output
        assert lines[-1] == "1 branch can be cleaned up: gx clean"
        assert "feat-auth (current)" in lines[-2]


class TestCleanHintMatchesClean:
    """The graph hint must count exactly what gx clean would offer without --force."""

    def test_hint_count_equals_stale_analyzer_candidates(self, tmp_git_repo):
        """Verify worktree, standalone, and dirty-skipped stale branches are counted like clean does."""
        import re

        from gx.lib.branch import current_branch, default_branch
        from gx.lib.config import config
        from gx.lib.stale_analyzer import StaleAnalyzer

        # Given a clean merged worktree, a dirty gone worktree, and standalone merged and gone branches
        repo = tmp_git_repo
        for name in ("wt-merged", "wt-dirty", "solo-merged", "solo-gone"):
            create_tmp_branch(repo, name)
            create_tmp_commit(repo, f"{name} work")
            push_tmp_branch(repo, name)
            checkout_tmp_branch(repo, "main")
        for name in ("wt-merged", "solo-merged"):
            merge_tmp_branch(repo, name, "main")
        push_tmp_branch(repo, "main")
        for name in ("wt-dirty", "solo-gone"):
            delete_tmp_remote_branch(repo, name)
        for name in ("wt-merged", "wt-dirty"):
            worktree = repo / ".worktrees" / name
            _run_git("worktree", "add", str(worktree), name, cwd=repo)
        (repo / ".worktrees" / "wt-dirty" / "scratch.txt").write_text("x\n")

        # When
        result = runner.invoke(app, ["log", "--graph"])

        # Then
        protected = config.protected_branches | {str(current_branch()), default_branch()}
        wt, br, skipped = StaleAnalyzer(protected=frozenset(protected)).analyze()
        assert [c.branch for c in skipped] == ["wt-dirty"]
        match = re.search(r"(\d+) branch(?:es)? can be cleaned up", result.output)
        assert match is not None
        assert int(match.group(1)) == len(wt) + len(br) == 3

    def test_hint_skips_stale_branch_in_main_worktree(self, tmp_git_repo, monkeypatch):
        """Verify a stale branch checked out in the main worktree is not counted from a linked one."""
        import re

        from gx.lib.branch import current_branch, default_branch
        from gx.lib.config import config
        from gx.lib.stale_analyzer import StaleAnalyzer

        # Given the main worktree on a merged, pushed branch and a linked worktree on another
        repo = tmp_git_repo
        create_tmp_branch(repo, "old")
        create_tmp_commit(repo, "old work")
        push_tmp_branch(repo, "old")
        merge_tmp_branch(repo, "old", "main")
        push_tmp_branch(repo, "main")
        checkout_tmp_branch(repo, "old")
        linked = repo.parent / "linked"
        _run_git("worktree", "add", "-b", "other", str(linked), "main", cwd=repo)
        monkeypatch.chdir(linked)

        # When
        result = runner.invoke(app, ["log", "--graph"])

        # Then the hint matches what gx clean offers (nothing)
        protected = config.protected_branches | {str(current_branch()), default_branch()}
        wt, br, _ = StaleAnalyzer(protected=frozenset(protected)).analyze()
        assert len(wt) + len(br) == 0
        assert re.search(r"can be cleaned up", result.output) is None
