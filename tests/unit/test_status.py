"""Tests for gx status command."""

from __future__ import annotations

from pathlib import Path

import click
import pytest
import typer

from gx.commands.status import BranchRow, _build_file_tree, _collect_branch_data, _parse_porcelain

from .conftest import _fail, _ok  # noqa: F401


def _branch_row(
    branch: str = "feat/test",
    target: str = "main",
    ahead_target: int = 0,
    behind_target: int = 0,
    ahead_remote: int | None = None,
    behind_remote: int | None = None,
    staged: int = 0,
    modified: int = 0,
    unmerged: int = 0,
    untracked: int = 0,
    stashes: int = 0,
    is_current: bool = False,  # noqa: FBT002
    is_worktree: bool = False,  # noqa: FBT002
    worktree_path: Path | None = None,
) -> BranchRow:
    """Build a BranchRow for testing."""
    return BranchRow(
        branch=branch,
        target=target,
        ahead_target=ahead_target,
        behind_target=behind_target,
        ahead_remote=ahead_remote,
        behind_remote=behind_remote,
        staged=staged,
        modified=modified,
        unmerged=unmerged,
        untracked=untracked,
        stashes=stashes,
        is_current=is_current,
        is_worktree=is_worktree,
        worktree_path=worktree_path,
    )


class TestParsePorcelain:
    """Tests for parsing git status --porcelain output."""

    def test_parses_modified_staged_untracked(self):
        """Verify correct parsing of mixed status output."""
        # Given
        lines = " M src/gx/cli.py\nA  src/gx/commands/status.py\n?? tests/test_new.py\nMM pyproject.toml"
        # When
        result = _parse_porcelain(lines)
        # Then
        assert len(result) == 4
        assert result[0] == (" M", "src/gx/cli.py")
        assert result[1] == ("A ", "src/gx/commands/status.py")
        assert result[2] == ("??", "tests/test_new.py")
        assert result[3] == ("MM", "pyproject.toml")

    def test_empty_output(self):
        """Verify empty list for clean working tree."""
        result = _parse_porcelain("")
        assert result == []

    def test_renamed_file(self):
        """Verify renamed files are parsed with the new name."""
        lines = "R  old_name.py -> new_name.py"
        result = _parse_porcelain(lines)
        assert result[0] == ("R ", "new_name.py")


class TestBuildFileTree:
    """Tests for building the Rich Tree from parsed status entries."""

    def test_builds_nested_tree(self):
        """Verify files are nested under their directory paths."""
        entries = [
            (" M", "src/gx/cli.py"),
            ("A ", "src/gx/commands/status.py"),
            ("??", "README.md"),
        ]
        tree = _build_file_tree(entries, "myrepo")
        assert "myrepo" in str(tree.label)

    def test_empty_entries_returns_none(self):
        """Verify None returned for empty entry list."""
        result = _build_file_tree([], "myrepo")
        assert result is None


class TestCollectBranchData:
    """Tests for collecting branch dashboard data."""

    def test_basic_branch_data(self, mocker):
        """Verify branch data is collected for active branches."""
        # Given
        mocker.patch("gx.commands.status.current_branch", return_value="feat/login")
        mocker.patch("gx.commands.status.default_branch", return_value="main")
        mocker.patch(
            "gx.commands.status.all_local_branches",
            return_value=frozenset({"main", "feat/login"}),
        )
        mocker.patch("gx.commands.status.list_worktrees", return_value=[])
        mocker.patch("gx.commands.status.stash_counts", return_value={})
        mocker.patch("gx.commands.status.ahead_behind", return_value=(2, 0))
        mocker.patch("gx.commands.status.tracking_remote_ref", return_value=None)
        mocker.patch("gx.commands.status.git", return_value=_ok(stdout=" M file.py\n?? new.txt"))
        # When
        rows = _collect_branch_data(show_all=False)
        # Then
        branch_names = [r.branch for r in rows]
        assert "feat/login" in branch_names

    def test_inactive_branch_excluded_by_default(self, mocker):
        """Verify clean branches without activity are excluded."""
        # Given
        mocker.patch("gx.commands.status.current_branch", return_value="feat/login")
        mocker.patch("gx.commands.status.default_branch", return_value="main")
        mocker.patch(
            "gx.commands.status.all_local_branches",
            return_value=frozenset({"main", "feat/login", "old-branch"}),
        )
        mocker.patch("gx.commands.status.list_worktrees", return_value=[])
        mocker.patch("gx.commands.status.stash_counts", return_value={})
        mocker.patch("gx.commands.status.ahead_behind", return_value=(0, 0))
        mocker.patch("gx.commands.status.tracking_remote_ref", return_value=None)
        mocker.patch("gx.commands.status.git", return_value=_ok(stdout=""))
        # When
        rows = _collect_branch_data(show_all=False)
        # Then
        branch_names = [r.branch for r in rows]
        assert "old-branch" not in branch_names

    def test_show_all_includes_inactive(self, mocker):
        """Verify --all flag includes clean branches."""
        # Given
        mocker.patch("gx.commands.status.current_branch", return_value="feat/login")
        mocker.patch("gx.commands.status.default_branch", return_value="main")
        mocker.patch(
            "gx.commands.status.all_local_branches",
            return_value=frozenset({"main", "feat/login", "old-branch"}),
        )
        mocker.patch("gx.commands.status.list_worktrees", return_value=[])
        mocker.patch("gx.commands.status.stash_counts", return_value={})
        mocker.patch("gx.commands.status.ahead_behind", return_value=(0, 0))
        mocker.patch("gx.commands.status.tracking_remote_ref", return_value=None)
        mocker.patch("gx.commands.status.git", return_value=_ok(stdout=""))
        # When
        rows = _collect_branch_data(show_all=True)
        # Then
        branch_names = [r.branch for r in rows]
        assert "old-branch" in branch_names


class TestStatusCommand:
    """Tests for the status command callback."""

    def test_files_and_branches_mutually_exclusive(self, mocker, capsys):
        """Verify error when both --files and --branches are passed."""
        mocker.patch("gx.commands.status.check_git_repo", autospec=True)
        from gx.commands.status import status

        ctx = typer.Context(click.Command("status"))
        with pytest.raises(typer.Exit):
            status(ctx=ctx, files=True, branches=True, show_all=False)
        captured = capsys.readouterr()
        assert "mutually exclusive" in captured.err.lower() or "cannot" in captured.err.lower()


class TestRenderBranchStatus:
    """Tests for rendering the two-line branch status display."""

    def test_renders_active_branch_with_metrics(self):
        """Verify active branch shows name on line 1 and non-zero metrics on line 2."""
        from gx.commands.status import _render_branch_status

        rows = [
            _branch_row(
                branch="feat/login",
                ahead_target=3,
                ahead_remote=2,
                behind_remote=0,
                staged=1,
                modified=2,
                untracked=1,
                is_current=True,
            ),
        ]
        result = _render_branch_status(rows)
        assert result is not None
        text = str(result)
        assert "feat/login" in text
        assert "main" in text
        assert "target:" in text
        assert "staged:" in text
        assert "modified:" in text
        assert "untracked:" in text

    def test_returns_none_for_empty_rows(self):
        """Verify None returned when no rows to display."""
        from gx.commands.status import _render_branch_status

        result = _render_branch_status([])
        assert result is None

    def test_clean_branch_shows_checkmark(self):
        """Verify branch with all-zero metrics shows clean indicator."""
        from gx.commands.status import _render_branch_status

        rows = [_branch_row(branch="main", ahead_remote=0, behind_remote=0, is_current=True)]
        result = _render_branch_status(rows)
        text = str(result)
        assert "✓" in text
        assert "clean" in text

    def test_worktree_branch_shows_wt_tag(self):
        """Verify worktree branches display [wt] suffix."""
        from gx.commands.status import _render_branch_status

        rows = [
            _branch_row(
                branch="feat/dark-mode",
                ahead_target=1,
                is_worktree=True,
                worktree_path=Path("/worktrees/dark-mode"),
            ),
        ]
        result = _render_branch_status(rows)
        text = str(result)
        assert "[wt]" in text

    def test_omits_target_metric_for_default_branch(self):
        """Verify target metric is omitted when branch is the default branch."""
        from gx.commands.status import _render_branch_status

        rows = [_branch_row(branch="main", staged=2, is_current=True)]
        result = _render_branch_status(rows)
        text = str(result)
        assert "target:" not in text
        assert "staged:" in text

    def test_no_tracking_shows_remote_dash_when_other_metrics(self):
        """Verify remote: — shown when no tracking but other metrics present."""
        from gx.commands.status import _render_branch_status

        rows = [_branch_row(ahead_target=1)]
        result = _render_branch_status(rows)
        text = str(result)
        assert "remote:" in text
        assert "—" in text

    def test_no_tracking_clean_branch_suppresses_remote_dash(self):
        """Verify remote: — is suppressed for clean branches with no tracking."""
        from gx.commands.status import _render_branch_status

        rows = [_branch_row(branch="feat/stale")]
        result = _render_branch_status(rows)
        text = str(result)
        assert "remote:" not in text
        assert "✓" in text

    def test_no_tracking_with_file_metrics_shows_remote_dash(self):
        """Verify remote: — shown when no tracking but file metrics present."""
        from gx.commands.status import _render_branch_status

        rows = [_branch_row(branch="feat/local", staged=2)]
        result = _render_branch_status(rows)
        text = str(result)
        assert "remote:" in text
        assert "—" in text
        assert "staged:" in text

    def test_ahead_and_behind_same_ref(self):
        """Verify both ahead and behind values shown for same reference."""
        from gx.commands.status import _render_branch_status

        rows = [_branch_row(branch="feat/diverged", ahead_target=3, behind_target=2)]
        result = _render_branch_status(rows)
        text = str(result)
        assert "3↑" in text
        assert "2↓" in text


class TestStatusEdgeCases:
    """Tests for status command edge cases."""

    def test_working_tree_clean_message(
        self, mocker, mock_status_check_git_repo, mock_status_git, capsys
    ):
        """Verify 'Working tree clean' shown when --files requested with no changes."""
        # Given
        mock_status_git.return_value = _ok(stdout="")
        mocker.patch("gx.commands.status.current_branch", return_value="main")

        # When
        from gx.commands.status import status

        ctx = typer.Context(click.Command("status"))
        status(ctx=ctx, files=True, branches=False, show_all=False)

        # Then
        captured = capsys.readouterr()
        assert "Working tree clean" in captured.out

    def test_files_only_flag(
        self, mocker, mock_status_check_git_repo, mock_status_git, mock_status_repo_root, capsys
    ):
        """Verify --files shows only the file tree panel."""
        # Given
        mock_status_git.return_value = _ok(stdout=" M file.py")
        mocker.patch("gx.commands.status.current_branch", return_value="feat/test")

        # When
        from gx.commands.status import status

        ctx = typer.Context(click.Command("status"))
        status(ctx=ctx, files=True, branches=False, show_all=False)

        # Then — should show file tree panel, no branch table
        captured = capsys.readouterr()
        assert "feat/test" in captured.out
        assert "Branch Status" not in captured.out

    def test_branches_only_flag(self, mocker, mock_status_check_git_repo, mock_status_git, capsys):
        """Verify --branches shows only the branch table."""
        # Given
        mock_status_git.return_value = _ok(stdout=" M file.py")
        mocker.patch("gx.commands.status.current_branch", return_value="feat/test")
        mocker.patch("gx.commands.status.default_branch", return_value="main")
        mocker.patch(
            "gx.commands.status.all_local_branches",
            return_value=frozenset({"main", "feat/test"}),
        )
        mocker.patch("gx.commands.status.list_worktrees", return_value=[])
        mocker.patch("gx.commands.status.stash_counts", return_value={})
        mocker.patch("gx.commands.status.ahead_behind", return_value=(1, 0))
        mocker.patch("gx.commands.status.tracking_remote_ref", return_value=None)

        # When
        from gx.commands.status import status

        ctx = typer.Context(click.Command("status"))
        status(ctx=ctx, files=False, branches=True, show_all=False)

        # Then — should show branch table, no file tree
        captured = capsys.readouterr()
        assert "Branch Status" in captured.out
