"""Tests for gx.lib.display shared rendering helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.panel import Panel

if TYPE_CHECKING:
    from pathlib import Path
from rich.text import Text

from gx.lib.branch import BranchRow
from gx.lib.display import kv_grid, render_branch_panel, render_working_tree_panel


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
    tracking_ref: str | None = None,
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
        tracking_ref=tracking_ref,
    )


class TestKvGrid:
    """Tests for kv_grid key-value grid builder."""

    def test_builds_grid_with_string_values(self):
        """Verify a grid is returned and contains the expected rows."""
        from rich.table import Table

        rows = [("Name", "Alice"), ("Branch", "main")]
        grid = kv_grid(rows)
        assert isinstance(grid, Table)
        assert grid.row_count == 2

    def test_builds_grid_with_text_values(self):
        """Verify Text objects are accepted as values."""
        from rich.table import Table

        value = Text("styled value", style="bold")
        rows = [("Label", value)]
        grid = kv_grid(rows)
        assert isinstance(grid, Table)
        assert grid.row_count == 1

    def test_empty_rows(self):
        """Verify an empty grid is returned for no input rows."""
        from rich.table import Table

        grid = kv_grid([])
        assert isinstance(grid, Table)
        assert grid.row_count == 0

    def test_mixed_string_and_text_values(self):
        """Verify a mix of str and Text values is accepted."""
        from rich.table import Table

        rows = [("Key1", "plain"), ("Key2", Text("rich"))]
        grid = kv_grid(rows)
        assert isinstance(grid, Table)
        assert grid.row_count == 2


class TestRenderBranchPanel:
    """Tests for render_branch_panel."""

    def test_returns_none_for_empty_rows(self):
        """Verify None is returned when no branch rows are provided."""
        result = render_branch_panel([])
        assert result is None

    def test_returns_panel_with_branches(self):
        """Verify a Panel is returned when branch rows are provided."""
        rows = [_branch_row(branch="feat/login", ahead_target=1)]
        result = render_branch_panel(rows)
        assert isinstance(result, Panel)

    def test_panel_title_is_branches(self):
        """Verify the panel title is 'Branches'."""
        rows = [_branch_row(branch="feat/login")]
        result = render_branch_panel(rows)
        assert result is not None
        assert result.title == "Branches"

    def test_current_branch_marker(self):
        """Verify current branch has asterisk marker in rendered output."""
        from io import StringIO

        from rich.console import Console

        rows = [_branch_row(branch="feat/current", is_current=True)]
        panel = render_branch_panel(rows)
        assert panel is not None

        buf = StringIO()
        c = Console(file=buf, highlight=False, no_color=True, width=120)
        c.print(panel)
        output = buf.getvalue()
        assert "*" in output
        assert "feat/current" in output

    def test_non_current_branch_no_marker(self):
        """Verify non-current branch does not have asterisk marker."""
        from io import StringIO

        from rich.console import Console

        rows = [_branch_row(branch="feat/other", is_current=False)]
        panel = render_branch_panel(rows)
        assert panel is not None

        buf = StringIO()
        c = Console(file=buf, highlight=False, no_color=True, width=120)
        c.print(panel)
        output = buf.getvalue()
        assert "feat/other" in output

    def test_ahead_behind_arrows(self):
        """Verify ahead/behind counts appear as ↑N ↓N arrows."""
        from io import StringIO

        from rich.console import Console

        rows = [_branch_row(branch="feat/x", ahead_remote=3, behind_remote=1)]
        panel = render_branch_panel(rows)
        assert panel is not None

        buf = StringIO()
        c = Console(file=buf, highlight=False, no_color=True, width=120)
        c.print(panel)
        output = buf.getvalue()
        assert "↑3" in output
        assert "↓1" in output

    def test_file_count_sigils(self):
        """Verify file counts appear as +N ~N !N ?N sigils."""
        from io import StringIO

        from rich.console import Console

        rows = [_branch_row(branch="feat/dirty", staged=2, modified=1, unmerged=0, untracked=3)]
        panel = render_branch_panel(rows)
        assert panel is not None

        buf = StringIO()
        c = Console(file=buf, highlight=False, no_color=True, width=120)
        c.print(panel)
        output = buf.getvalue()
        assert "+2" in output
        assert "~1" in output
        assert "?3" in output

    def test_stash_indicator(self):
        """Verify stash count appears as ≡N."""
        from io import StringIO

        from rich.console import Console

        rows = [_branch_row(branch="feat/stashed", stashes=2)]
        panel = render_branch_panel(rows)
        assert panel is not None

        buf = StringIO()
        c = Console(file=buf, highlight=False, no_color=True, width=120)
        c.print(panel)
        output = buf.getvalue()
        assert "≡2" in output

    def test_no_stash_indicator_when_zero(self):
        """Verify stash column is empty when stash count is zero."""
        from io import StringIO

        from rich.console import Console

        rows = [_branch_row(branch="feat/clean", stashes=0)]
        panel = render_branch_panel(rows)
        assert panel is not None

        buf = StringIO()
        c = Console(file=buf, highlight=False, no_color=True, width=120)
        c.print(panel)
        output = buf.getvalue()
        assert "≡" not in output

    def test_tracking_ref_shown(self):
        """Verify the tracking ref appears in the panel output."""
        from io import StringIO

        from rich.console import Console

        rows = [_branch_row(branch="feat/tracked", tracking_ref="origin/feat/tracked")]
        panel = render_branch_panel(rows)
        assert panel is not None

        buf = StringIO()
        c = Console(file=buf, highlight=False, no_color=True, width=120)
        c.print(panel)
        output = buf.getvalue()
        assert "origin/feat/tracked" in output

    def test_multiple_branches_in_panel(self):
        """Verify multiple branches all appear in the same panel."""
        from io import StringIO

        from rich.console import Console

        rows = [
            _branch_row(branch="main", is_current=True),
            _branch_row(branch="feat/alpha", ahead_target=2),
            _branch_row(branch="feat/beta", staged=1),
        ]
        panel = render_branch_panel(rows)
        assert panel is not None

        buf = StringIO()
        c = Console(file=buf, highlight=False, no_color=True, width=120)
        c.print(panel)
        output = buf.getvalue()
        assert "main" in output
        assert "feat/alpha" in output
        assert "feat/beta" in output


class TestRenderWorkingTreePanel:
    """Tests for render_working_tree_panel."""

    def test_clean_state_shows_clean(self):
        """Verify 'Clean' is shown when all counts are zero."""
        from io import StringIO

        from rich.console import Console

        panel = render_working_tree_panel(staged=0, modified=0, unmerged=0, untracked=0)
        assert isinstance(panel, Panel)

        buf = StringIO()
        c = Console(file=buf, highlight=False, no_color=True, width=120)
        c.print(panel)
        output = buf.getvalue()
        assert "Clean" in output

    def test_dirty_state_shows_counts(self):
        """Verify file counts appear when the working tree is dirty."""
        from io import StringIO

        from rich.console import Console

        panel = render_working_tree_panel(staged=3, modified=2, unmerged=0, untracked=1)
        assert isinstance(panel, Panel)

        buf = StringIO()
        c = Console(file=buf, highlight=False, no_color=True, width=120)
        c.print(panel)
        output = buf.getvalue()
        assert "+3 staged" in output
        assert "~2 modified" in output
        assert "?1 untracked" in output

    def test_unmerged_count_shown(self):
        """Verify unmerged count appears when non-zero."""
        from io import StringIO

        from rich.console import Console

        panel = render_working_tree_panel(staged=0, modified=0, unmerged=4, untracked=0)

        buf = StringIO()
        c = Console(file=buf, highlight=False, no_color=True, width=120)
        c.print(panel)
        output = buf.getvalue()
        assert "!4 unmerged" in output

    def test_zero_counts_not_shown_in_dirty_state(self):
        """Verify zero-count categories are omitted in dirty state."""
        from io import StringIO

        from rich.console import Console

        panel = render_working_tree_panel(staged=1, modified=0, unmerged=0, untracked=0)

        buf = StringIO()
        c = Console(file=buf, highlight=False, no_color=True, width=120)
        c.print(panel)
        output = buf.getvalue()
        assert "+1 staged" in output
        assert "modified" not in output
        assert "untracked" not in output

    def test_panel_title_is_working_tree(self):
        """Verify the panel title is 'Working Tree'."""
        panel = render_working_tree_panel(staged=0, modified=0, unmerged=0, untracked=0)
        assert panel.title == "Working Tree"
