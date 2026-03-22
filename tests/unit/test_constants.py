"""Tests for gx constants."""

from gx.constants import (
    READ_ONLY_GIT_COMMANDS,
    READ_ONLY_GIT_COMPOUND_COMMANDS,
    Verbosity,
)


def test_verbosity_values() -> None:
    """Verify Verbosity enum has correct integer values."""
    assert Verbosity.INFO == 0
    assert Verbosity.DEBUG == 1
    assert Verbosity.TRACE == 2


def test_verbosity_comparison() -> None:
    """Verify Verbosity supports integer comparison."""
    assert Verbosity.TRACE >= Verbosity.DEBUG
    assert Verbosity.DEBUG >= Verbosity.INFO
    assert not Verbosity.INFO >= Verbosity.DEBUG


def test_read_only_git_commands_is_frozenset() -> None:
    """Verify READ_ONLY_GIT_COMMANDS is a frozenset of strings."""
    assert isinstance(READ_ONLY_GIT_COMMANDS, frozenset)
    assert all(isinstance(cmd, str) for cmd in READ_ONLY_GIT_COMMANDS)


def test_read_only_git_commands_contains_expected() -> None:
    """Verify READ_ONLY_GIT_COMMANDS contains core read-only commands."""
    assert "status" in READ_ONLY_GIT_COMMANDS
    assert "log" in READ_ONLY_GIT_COMMANDS
    assert "diff" in READ_ONLY_GIT_COMMANDS
    assert "push" not in READ_ONLY_GIT_COMMANDS
    assert "commit" not in READ_ONLY_GIT_COMMANDS


def test_read_only_git_compound_commands() -> None:
    """Verify READ_ONLY_GIT_COMPOUND_COMMANDS maps commands to read-only subcommands."""
    assert isinstance(READ_ONLY_GIT_COMPOUND_COMMANDS, dict)
    assert "branch" in READ_ONLY_GIT_COMPOUND_COMMANDS
    assert "worktree" in READ_ONLY_GIT_COMPOUND_COMMANDS
    assert isinstance(READ_ONLY_GIT_COMPOUND_COMMANDS["branch"], frozenset)
    assert isinstance(READ_ONLY_GIT_COMPOUND_COMMANDS["worktree"], frozenset)
