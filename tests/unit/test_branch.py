"""Tests for gx branch query utilities."""

import pytest
import typer

from gx.lib.branch import (
    ahead_behind,
    current_branch,
    default_branch,
    has_upstream,
    has_upstream_branch,
    is_empty,
    is_gone,
    is_merged,
    stash_counts,
    tracking_branch,
    tracking_remote_ref,
)
from gx.lib.git import GitResult
from tests.conftest import (
    checkout_tmp_branch,
    create_tmp_branch,
    create_tmp_commit,
    create_tmp_divergence,
    create_tmp_stash,
    delete_tmp_remote_branch,
    detach_tmp_head,
    merge_tmp_branch,
    push_tmp_branch,
)

from .conftest import _fail


class TestCurrentBranch:
    """Tests for current_branch()."""

    def test_returns_branch_name(self, tmp_git_repo):
        """Verify current_branch() returns the branch name."""
        create_tmp_branch(tmp_git_repo, "feature-login")
        assert current_branch() == "feature-login"

    def test_returns_none_for_detached_head(self, tmp_git_repo):
        """Verify current_branch() returns None in detached HEAD state."""
        detach_tmp_head(tmp_git_repo)
        assert current_branch() is None

    def test_returns_none_on_failure(self, mocker):
        """Verify current_branch() returns None when git command fails."""
        mocker.patch(
            "gx.lib.branch.git",
            return_value=GitResult(
                command="git rev-parse --abbrev-ref HEAD",
                returncode=128,
                stdout="",
                stderr="fatal: not a git repository",
            ),
        )
        assert current_branch() is None


class TestDefaultBranch:
    """Tests for default_branch()."""

    def test_detects_from_remote(self, tmp_git_repo):
        """Verify default_branch() detects the default branch from remote."""
        assert default_branch() == "main"

    def test_falls_back_to_local_main(self, mocker):
        """Verify default_branch() falls back to local 'main' when remote fails."""
        mock_git = mocker.patch("gx.lib.branch.git")
        mock_git.side_effect = [
            GitResult(
                command="git symbolic-ref refs/remotes/origin/HEAD",
                returncode=1,
                stdout="",
                stderr="fatal: ref not found",
            ),
            GitResult(
                command="git rev-parse --verify refs/heads/main",
                returncode=0,
                stdout="abc1234",
                stderr="",
            ),
        ]
        assert default_branch() == "main"

    def test_falls_back_to_local_master(self, mocker):
        """Verify default_branch() falls back to local 'master' when 'main' doesn't exist."""
        mock_git = mocker.patch("gx.lib.branch.git")
        mock_git.side_effect = [
            GitResult(
                command="git symbolic-ref refs/remotes/origin/HEAD",
                returncode=1,
                stdout="",
                stderr="",
            ),
            GitResult(
                command="git rev-parse --verify refs/heads/main",
                returncode=1,
                stdout="",
                stderr="fatal: not a valid ref",
            ),
            GitResult(
                command="git rev-parse --verify refs/heads/master",
                returncode=0,
                stdout="abc1234",
                stderr="",
            ),
        ]
        assert default_branch() == "master"

    def test_exits_when_no_default_found(self, mocker):
        """Verify default_branch() exits when no default branch can be found."""
        mock_git = mocker.patch("gx.lib.branch.git")
        mock_git.side_effect = [
            GitResult(
                command="git symbolic-ref refs/remotes/origin/HEAD",
                returncode=1,
                stdout="",
                stderr="",
            ),
            GitResult(
                command="git rev-parse --verify refs/heads/main", returncode=1, stdout="", stderr=""
            ),
            GitResult(
                command="git rev-parse --verify refs/heads/master",
                returncode=1,
                stdout="",
                stderr="",
            ),
        ]
        with pytest.raises(typer.Exit):
            default_branch()


class TestHasUpstream:
    """Tests for has_upstream()."""

    def test_returns_true_when_upstream_set(self, tmp_git_repo):
        """Verify has_upstream() returns True when tracking branch exists."""
        assert has_upstream() is True

    def test_returns_false_when_no_upstream(self, tmp_git_repo):
        """Verify has_upstream() returns False when no tracking branch."""
        create_tmp_branch(tmp_git_repo, "local-only")
        assert has_upstream() is False


class TestTrackingBranch:
    """Tests for tracking_branch()."""

    def test_returns_remote_and_branch(self, tmp_git_repo):
        """Verify tracking_branch() returns (remote, branch) tuple."""
        create_tmp_branch(tmp_git_repo, "feature")
        create_tmp_commit(tmp_git_repo, "add feature work")
        push_tmp_branch(tmp_git_repo, "feature")
        result = tracking_branch()
        assert result == ("origin", "feature")

    def test_returns_none_when_no_upstream(self, tmp_git_repo):
        """Verify tracking_branch() returns None when no upstream is set."""
        create_tmp_branch(tmp_git_repo, "local-only")
        assert tracking_branch() is None

    def test_returns_none_for_detached_head(self, tmp_git_repo):
        """Verify tracking_branch() returns None in detached HEAD state."""
        detach_tmp_head(tmp_git_repo)
        assert tracking_branch() is None


class TestIsMerged:
    """Tests for is_merged()."""

    def test_returns_true_when_merged(self, tmp_git_repo):
        """Verify is_merged() returns True when branch is in merged list."""
        create_tmp_branch(tmp_git_repo, "feature-done")
        create_tmp_commit(tmp_git_repo, "feature work")
        merge_tmp_branch(tmp_git_repo, "feature-done", "main")
        assert is_merged("feature-done", target="main") is True

    def test_returns_false_when_not_merged(self, tmp_git_repo):
        """Verify is_merged() returns False when branch is not in merged list."""
        create_tmp_branch(tmp_git_repo, "feature-wip")
        create_tmp_commit(tmp_git_repo, "wip work")
        checkout_tmp_branch(tmp_git_repo, "main")
        assert is_merged("feature-wip", target="main") is False

    def test_uses_default_branch_when_no_target(self, tmp_git_repo):
        """Verify is_merged() uses default_branch() when target is None."""
        create_tmp_branch(tmp_git_repo, "feature-done")
        create_tmp_commit(tmp_git_repo, "feature work")
        merge_tmp_branch(tmp_git_repo, "feature-done", "main")
        assert is_merged("feature-done") is True


class TestIsGone:
    """Tests for is_gone()."""

    def test_returns_true_when_upstream_gone(self, tmp_git_repo):
        """Verify is_gone() returns True when upstream is marked [gone]."""
        create_tmp_branch(tmp_git_repo, "feature-old")
        create_tmp_commit(tmp_git_repo, "old work")
        push_tmp_branch(tmp_git_repo, "feature-old")
        checkout_tmp_branch(tmp_git_repo, "main")
        delete_tmp_remote_branch(tmp_git_repo, "feature-old")
        assert is_gone("feature-old") is True

    def test_returns_false_when_upstream_active(self, tmp_git_repo):
        """Verify is_gone() returns False when upstream is still active."""
        create_tmp_branch(tmp_git_repo, "feature")
        create_tmp_commit(tmp_git_repo, "feature work")
        push_tmp_branch(tmp_git_repo, "feature")
        checkout_tmp_branch(tmp_git_repo, "main")
        assert is_gone("feature") is False

    def test_returns_false_when_no_upstream(self, tmp_git_repo):
        """Verify is_gone() returns False when branch has no upstream."""
        create_tmp_branch(tmp_git_repo, "local-only")
        checkout_tmp_branch(tmp_git_repo, "main")
        assert is_gone("local-only") is False


class TestHasUpstreamBranch:
    """Tests for has_upstream_branch()."""

    def test_returns_true_when_remote_configured(self, tmp_git_repo):
        """Verify returns True when branch has a remote configured."""
        create_tmp_branch(tmp_git_repo, "feat/1")
        create_tmp_commit(tmp_git_repo, "feat work")
        push_tmp_branch(tmp_git_repo, "feat/1")
        assert has_upstream_branch("feat/1") is True

    def test_returns_false_when_no_remote(self, tmp_git_repo):
        """Verify returns False when branch has no remote configured."""
        create_tmp_branch(tmp_git_repo, "local-only")
        assert has_upstream_branch("local-only") is False


class TestIsEmpty:
    """Tests for is_empty()."""

    def test_returns_true_when_no_commits_ahead(self, tmp_git_repo):
        """Verify is_empty() returns True when branch has zero commits ahead."""
        create_tmp_branch(tmp_git_repo, "empty-branch")
        assert is_empty("empty-branch") is True

    def test_returns_false_when_commits_ahead(self, tmp_git_repo):
        """Verify is_empty() returns False when branch has commits ahead."""
        create_tmp_branch(tmp_git_repo, "feature")
        create_tmp_commit(tmp_git_repo, "new work")
        assert is_empty("feature") is False

    def test_uses_explicit_target(self, tmp_git_repo):
        """Verify is_empty() uses provided target instead of default branch."""
        create_tmp_branch(tmp_git_repo, "feature")
        assert is_empty("feature", target="main") is True


class TestStashCounts:
    """Tests for the stash_counts helper."""

    def test_groups_stashes_by_branch(self, tmp_git_repo):
        """Verify stashes are grouped by branch name."""
        create_tmp_branch(tmp_git_repo, "feat/login")
        create_tmp_stash(tmp_git_repo, "feat/login")
        create_tmp_stash(tmp_git_repo, "feat/login")
        create_tmp_stash(tmp_git_repo, "main")
        result = stash_counts()
        assert result == {"feat/login": 2, "main": 1}

    def test_empty_stash_list(self, tmp_git_repo):
        """Verify empty dict when no stashes exist."""
        result = stash_counts()
        assert result == {}


class TestAheadBehind:
    """Tests for the ahead_behind helper."""

    def test_ahead_and_behind(self, tmp_git_repo):
        """Verify correct parsing of ahead/behind counts."""
        create_tmp_branch(tmp_git_repo, "feat/login")
        create_tmp_commit(tmp_git_repo, "branch work")
        create_tmp_divergence(tmp_git_repo, "feat/login", "main")
        ahead, behind = ahead_behind("feat/login", "main")
        assert ahead >= 1
        assert behind >= 1

    def test_no_difference(self, tmp_git_repo):
        """Verify zero counts when branches are identical."""
        ahead, behind = ahead_behind("main", "main")
        assert ahead == 0
        assert behind == 0

    def test_invalid_branch_returns_none(self, mocker):
        """Verify None returned when git command fails."""
        mocker.patch("gx.lib.branch.git", autospec=True, return_value=_fail())
        result = ahead_behind("nonexistent", "main")
        assert result is None


class TestTrackingRemoteRef:
    """Tests for the tracking_remote_ref helper."""

    def test_returns_remote_ref(self, tmp_git_repo):
        """Verify returns full remote ref for a branch with upstream."""
        create_tmp_branch(tmp_git_repo, "feat/login")
        create_tmp_commit(tmp_git_repo, "feat work")
        push_tmp_branch(tmp_git_repo, "feat/login")
        result = tracking_remote_ref("feat/login")
        assert result == "origin/feat/login"

    def test_returns_none_when_no_upstream(self, tmp_git_repo):
        """Verify None when branch has no upstream configured."""
        create_tmp_branch(tmp_git_repo, "local-only")
        result = tracking_remote_ref("local-only")
        assert result is None
