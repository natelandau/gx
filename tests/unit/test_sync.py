"""Unit tests for the reconcile helpers in gx.lib.sync."""

import subprocess
from pathlib import Path

import pytest

from gx.lib.sync import (
    Strategy,
    SyncState,
    classify_sync_state,
    is_merge_in_progress,
    needs_force_push,
    resolve_strategy,
)
from tests.conftest import create_tmp_branch, create_tmp_commit, push_tmp_branch


@pytest.mark.parametrize(
    ("ahead", "behind", "expected"),
    [
        (0, 0, SyncState.UP_TO_DATE),
        (3, 0, SyncState.UP_TO_DATE),
        (0, 2, SyncState.FAST_FORWARD),
        (2, 2, SyncState.DIVERGED),
    ],
)
def test_classify_sync_state(ahead: int, behind: int, expected: SyncState) -> None:
    """Verify ahead/behind counts map to the correct sync state."""
    # When / Then
    assert classify_sync_state(ahead, behind) == expected


def test_resolve_strategy_flag_wins_over_config() -> None:
    """Verify an explicit flag overrides the config default."""
    # Given a rebase flag and a merge config default
    # When resolving
    result = resolve_strategy(rebase=True, merge=False, ff_only=False, config_strategy="merge")
    # Then the flag wins
    assert result is Strategy.REBASE


def test_resolve_strategy_config_used_when_no_flag() -> None:
    """Verify the config default applies when no flag is given."""
    # When resolving with only a config value
    result = resolve_strategy(rebase=False, merge=False, ff_only=False, config_strategy="merge")
    # Then the config value is used
    assert result is Strategy.MERGE


def test_resolve_strategy_ff_only_config() -> None:
    """Verify the ff-only config value resolves to the FF_ONLY strategy."""
    result = resolve_strategy(rebase=False, merge=False, ff_only=False, config_strategy="ff-only")
    assert result is Strategy.FF_ONLY


def test_resolve_strategy_ask_returns_none() -> None:
    """Verify 'ask' with no flag returns None so the caller prompts."""
    result = resolve_strategy(rebase=False, merge=False, ff_only=False, config_strategy="ask")
    assert result is None


def test_resolve_strategy_ff_only_flag() -> None:
    """Verify the --ff-only flag resolves to FF_ONLY."""
    result = resolve_strategy(rebase=False, merge=False, ff_only=True, config_strategy="ask")
    assert result is Strategy.FF_ONLY


def test_resolve_strategy_merge_flag() -> None:
    """Verify the merge flag resolves to MERGE."""
    # When resolving with only the merge flag
    result = resolve_strategy(rebase=False, merge=True, ff_only=False, config_strategy="ask")
    # Then merge strategy is returned
    assert result is Strategy.MERGE


def test_resolve_strategy_flag_precedence_rebase_over_merge() -> None:
    """Verify rebase flag takes precedence over merge flag."""
    # When both rebase and merge flags are set
    result = resolve_strategy(rebase=True, merge=True, ff_only=False, config_strategy="ask")
    # Then rebase wins
    assert result is Strategy.REBASE


def test_is_merge_in_progress_false_when_clean(tmp_git_repo: Path) -> None:
    """Verify no merge is reported in a clean repo."""
    # Then
    assert is_merge_in_progress() is False


def test_needs_force_push_true_after_diverged_rebase(tmp_git_repo: Path) -> None:
    """Verify force-push is flagged when upstream is not an ancestor of HEAD."""
    # Given a feature branch pushed, then rewritten so its upstream diverges
    create_tmp_branch(tmp_git_repo, "feature")
    create_tmp_commit(tmp_git_repo)
    push_tmp_branch(tmp_git_repo)
    # amend to rewrite the pushed commit so origin/feature is no longer an ancestor
    subprocess.run(
        ["git", "commit", "--amend", "-m", "rewritten"],  # noqa: S607
        cwd=tmp_git_repo,
        check=True,
        capture_output=True,
        text=True,
    )
    # When / Then
    assert needs_force_push("origin/feature") is True
