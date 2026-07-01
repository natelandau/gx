"""Shared fixtures for gx command unit tests."""

from __future__ import annotations

import pytest
from nclutils.sh import CompletedCommand


def _completed(
    *,
    argv: tuple[str, ...] = ("git",),
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> CompletedCommand:
    """Build a CompletedCommand result for mocking run_command or git()."""
    return CompletedCommand(
        argv=argv,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        duration=0.0,
        cwd=None,
    )


def _ok(stdout: str = "") -> CompletedCommand:
    """Build a successful CompletedCommand."""
    return _completed(returncode=0, stdout=stdout)


def _fail(stderr: str = "error") -> CompletedCommand:
    """Build a failed CompletedCommand."""
    return _completed(returncode=1, stderr=stderr)


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
def mock_ahead_behind(mocker):
    """Patch ahead_behind() at the pull command's usage site, returning (0, 0) by default.

    A (0, 0) result classifies as SyncState.UP_TO_DATE, keeping tests on the
    non-diverged pull path without invoking a real git subprocess.
    """
    return mocker.patch("gx.commands.pull.ahead_behind", autospec=True, return_value=(0, 0))


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
