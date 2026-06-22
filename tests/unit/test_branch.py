"""Tests for gx-specific branch helpers."""

import pytest
import typer

from gx.lib.branch import default_branch, has_commits


class TestHasCommits:
    """Tests for has_commits()."""

    def test_true_when_repo_has_commits(self, tmp_git_repo):
        """Verify has_commits() is True for a repo with at least one commit."""
        # Given a repo with an initial commit (tmp_git_repo fixture)
        # When/Then has_commits reports True
        assert has_commits() is True

    def test_false_for_unborn_head(self, empty_git_repo):
        """Verify has_commits() is False for a fresh repo with no commits."""
        # Given a freshly initialized repo with an unborn HEAD (empty_git_repo fixture)
        # When/Then has_commits reports False
        assert has_commits() is False


class TestDefaultBranch:
    """Tests for default_branch()."""

    def test_detects_from_remote(self, tmp_git_repo):
        """Verify default_branch() detects the default branch from remote."""
        assert default_branch() == "main"

    def test_falls_back_to_local_main(self, mocker):
        """Verify default_branch() falls back to local 'main' when remote symref is missing."""
        mocker.patch("gx.lib.branch.nc_default_branch", autospec=True, return_value=None)
        mocker.patch("gx.lib.branch.branch_exists", autospec=True, return_value=True)
        assert default_branch() == "main"

    def test_falls_back_to_local_master(self, mocker):
        """Verify default_branch() falls back to 'master' when 'main' doesn't exist."""
        mocker.patch("gx.lib.branch.nc_default_branch", autospec=True, return_value=None)
        mocker.patch(
            "gx.lib.branch.branch_exists",
            autospec=True,
            side_effect=lambda name: name == "master",
        )
        assert default_branch() == "master"

    def test_falls_back_to_current_branch(self, mocker):
        """Verify default_branch() falls back to HEAD when no remote or main/master exists."""
        # Given a fresh repo with no remote symref and no main/master branch
        mocker.patch("gx.lib.branch.nc_default_branch", autospec=True, return_value=None)
        mocker.patch("gx.lib.branch.branch_exists", autospec=True, return_value=False)
        mocker.patch("gx.lib.branch.current_branch", autospec=True, return_value="trunk")

        # When/Then default_branch falls back to the current branch
        assert default_branch() == "trunk"

    def test_exits_when_no_default_found(self, mocker):
        """Verify default_branch() exits when no default branch can be found."""
        mocker.patch("gx.lib.branch.nc_default_branch", autospec=True, return_value=None)
        mocker.patch("gx.lib.branch.branch_exists", autospec=True, return_value=False)
        mocker.patch("gx.lib.branch.current_branch", autospec=True, return_value=None)
        with pytest.raises(typer.Exit):
            default_branch()
