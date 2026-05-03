"""Shared fixtures for gx command unit tests."""

from __future__ import annotations

import pytest

from gx.lib.git import GitResult


def _ok(stdout: str = "", command: str = "git test") -> GitResult:
    """Build a successful GitResult."""
    return GitResult(command=command, returncode=0, stdout=stdout, stderr="")


def _fail(stderr: str = "error", command: str = "git test") -> GitResult:
    """Build a failed GitResult."""
    return GitResult(command=command, returncode=1, stdout="", stderr=stderr)


@pytest.fixture
def mock_git(mocker):
    """Patch git() everywhere the pull flow calls it and return the shared mock.

    The pull flow's git() calls happen across three modules (commands.pull, lib.workspace,
    lib.sync) since the helpers were extracted; tests rely on a single ordered side_effect
    list, so all three patch sites must share the same Mock instance.
    """
    from gx.lib.git import git as real_git

    mock = mocker.create_autospec(real_git)
    mocker.patch("gx.commands.pull.git", new=mock)
    mocker.patch("gx.lib.workspace.git", new=mock)
    mocker.patch("gx.lib.sync.git", new=mock)
    return mock


@pytest.fixture
def mock_current_branch(mocker):
    """Patch current_branch() where validate_branch() looks it up, returning 'main' by default."""
    return mocker.patch("gx.lib.sync.current_branch", autospec=True, return_value="main")


@pytest.fixture
def mock_tracking_branch(mocker):
    """Patch tracking_branch() where validate_branch() looks it up, returning ('origin', 'main')."""
    return mocker.patch(
        "gx.lib.sync.tracking_branch",
        autospec=True,
        return_value=("origin", "main"),
    )


@pytest.fixture
def mock_check_git_repo(mocker):
    """Patch check_git_repo() at the pull command's usage site as a no-op."""
    return mocker.patch("gx.commands.pull.check_git_repo", autospec=True)


@pytest.fixture
def mock_push_git(mocker):
    """Patch git() at the push command's usage site and return the mock."""
    return mocker.patch("gx.commands.push.git", autospec=True)


@pytest.fixture
def mock_push_current_branch(mocker):
    """Patch current_branch() at the push command's usage site, returning 'feature' by default."""
    return mocker.patch("gx.commands.push.current_branch", autospec=True, return_value="feature")


@pytest.fixture
def mock_push_default_branch(mocker):
    """Patch default_branch() at the push command's usage site, returning 'main' by default."""
    return mocker.patch("gx.commands.push.default_branch", autospec=True, return_value="main")


@pytest.fixture
def mock_push_tracking_branch(mocker):
    """Patch tracking_branch() at the push command's usage site, returning ('origin', 'feature')."""
    return mocker.patch(
        "gx.commands.push.tracking_branch",
        autospec=True,
        return_value=("origin", "feature"),
    )


@pytest.fixture
def mock_push_check_git_repo(mocker):
    """Patch check_git_repo() at the push command's usage site as a no-op."""
    return mocker.patch("gx.commands.push.check_git_repo", autospec=True)


@pytest.fixture
def mock_clean_git(mocker):
    """Patch git() at the clean command's usage site."""
    return mocker.patch("gx.commands.clean.git", autospec=True)


@pytest.fixture
def mock_clean_check_git_repo(mocker):
    """Patch check_git_repo() at the clean command's usage site as a no-op."""
    return mocker.patch("gx.commands.clean.check_git_repo", autospec=True)


@pytest.fixture
def mock_clean_current_branch(mocker):
    """Patch current_branch() at the clean command's usage site, returning 'main' by default."""
    return mocker.patch("gx.commands.clean.current_branch", autospec=True, return_value="main")


@pytest.fixture
def mock_status_git(mocker):
    """Patch git() at the status command's usage site."""
    return mocker.patch("gx.commands.status.git", autospec=True)


@pytest.fixture
def mock_status_check_git_repo(mocker):
    """Patch check_git_repo() at the status command's usage site as a no-op."""
    return mocker.patch("gx.commands.status.check_git_repo", autospec=True)


@pytest.fixture
def mock_status_repo_root(mocker):
    """Patch repo_root() at the status command's usage site."""
    from pathlib import Path

    return mocker.patch("gx.commands.status.repo_root", autospec=True, return_value=Path("/repo"))


@pytest.fixture
def mock_log_git(mocker):
    """Patch git() at the log command's usage site."""
    return mocker.patch("gx.commands.log.git", autospec=True)


@pytest.fixture
def mock_log_check_git_repo(mocker):
    """Patch check_git_repo() at the log command's usage site as a no-op."""
    return mocker.patch("gx.commands.log.check_git_repo", autospec=True)


@pytest.fixture
def mock_info_git(mocker):
    """Patch git() at the info command's usage site."""
    return mocker.patch("gx.commands.info.git", autospec=True)


@pytest.fixture
def mock_info_check_git_repo(mocker):
    """Patch check_git_repo() at the info command's usage site as a no-op."""
    return mocker.patch("gx.commands.info.check_git_repo", autospec=True)
