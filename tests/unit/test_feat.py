"""Tests for gx feat command."""

import pytest
import typer

from gx.lib.git import GitResult
from tests.conftest import checkout_tmp_branch, create_tmp_branch


class TestNextFeatNumber:
    """Tests for _next_feat_number()."""

    def test_returns_1_when_no_feat_branches(self, tmp_git_repo):
        """Verify returns 1 when no feat/* branches exist."""
        from gx.commands.feat import _next_feat_number

        assert _next_feat_number() == 1

    def test_returns_next_number(self, tmp_git_repo):
        """Verify returns next sequential number."""
        create_tmp_branch(tmp_git_repo, "feat/1")
        checkout_tmp_branch(tmp_git_repo, "main")
        create_tmp_branch(tmp_git_repo, "feat/2")
        checkout_tmp_branch(tmp_git_repo, "main")
        from gx.commands.feat import _next_feat_number

        assert _next_feat_number() == 3

    def test_fills_gaps(self, tmp_git_repo):
        """Verify returns lowest available number when gaps exist."""
        create_tmp_branch(tmp_git_repo, "feat/2")
        checkout_tmp_branch(tmp_git_repo, "main")
        create_tmp_branch(tmp_git_repo, "feat/3")
        checkout_tmp_branch(tmp_git_repo, "main")
        from gx.commands.feat import _next_feat_number

        assert _next_feat_number() == 1

    def test_ignores_named_branches(self, tmp_git_repo):
        """Verify ignores non-numeric feat branches."""
        create_tmp_branch(tmp_git_repo, "feat/1")
        checkout_tmp_branch(tmp_git_repo, "main")
        create_tmp_branch(tmp_git_repo, "feat/login")
        checkout_tmp_branch(tmp_git_repo, "main")
        create_tmp_branch(tmp_git_repo, "feat/3")
        checkout_tmp_branch(tmp_git_repo, "main")
        from gx.commands.feat import _next_feat_number

        assert _next_feat_number() == 2


class TestNormalizeName:
    """Tests for _normalize_name()."""

    def _mock_git_success(self, mocker) -> None:
        """Patch git to succeed for check-ref-format calls."""
        mocker.patch(
            "gx.commands.feat.git",
            return_value=GitResult(
                command="git check-ref-format",
                returncode=0,
                stdout="",
                stderr="",
            ),
        )

    def test_returns_valid_name_unchanged(self, mocker):
        """Verify a valid bare name passes through unchanged."""
        self._mock_git_success(mocker)
        from gx.commands.feat import _normalize_name

        assert _normalize_name("login") == "login"

    def test_replaces_spaces_with_hyphens(self, mocker):
        """Verify spaces are converted to hyphens."""
        self._mock_git_success(mocker)
        from gx.commands.feat import _normalize_name

        assert _normalize_name("my feature") == "my-feature"

    def test_replaces_underscores_with_hyphens(self, mocker):
        """Verify underscores are converted to hyphens."""
        self._mock_git_success(mocker)
        from gx.commands.feat import _normalize_name

        assert _normalize_name("my_feature") == "my-feature"

    def test_lowercases_name(self, mocker):
        """Verify uppercase letters are lowercased."""
        self._mock_git_success(mocker)
        from gx.commands.feat import _normalize_name

        assert _normalize_name("MyFeature") == "myfeature"

    def test_strips_whitespace(self, mocker):
        """Verify leading and trailing whitespace is stripped."""
        self._mock_git_success(mocker)
        from gx.commands.feat import _normalize_name

        assert _normalize_name("  login  ") == "login"

    def test_removes_invalid_chars(self, mocker):
        """Verify git-invalid characters are removed."""
        self._mock_git_success(mocker)
        from gx.commands.feat import _normalize_name

        assert _normalize_name("feat~1") == "feat1"

    def test_collapses_consecutive_hyphens(self, mocker):
        """Verify multiple consecutive hyphens collapse to one."""
        self._mock_git_success(mocker)
        from gx.commands.feat import _normalize_name

        assert _normalize_name("a---b") == "a-b"

    def test_normalizes_dotdot(self, mocker):
        """Verify '..' sequences are replaced and collapsed."""
        self._mock_git_success(mocker)
        from gx.commands.feat import _normalize_name

        assert _normalize_name("a..b") == "a-b"

    def test_strips_leading_trailing_hyphens(self, mocker):
        """Verify leading and trailing hyphens are stripped."""
        self._mock_git_success(mocker)
        from gx.commands.feat import _normalize_name

        assert _normalize_name("-login-") == "login"

    def test_rejects_slashes(self):
        """Verify names with slashes are rejected."""
        from gx.commands.feat import _normalize_name

        with pytest.raises(typer.Exit):
            _normalize_name("foo/bar")

    def test_rejects_empty_after_normalize(self):
        """Verify names that become empty after normalization are rejected."""
        from gx.commands.feat import _normalize_name

        with pytest.raises(typer.Exit):
            _normalize_name("~^:?*")


class TestFeatBranchMode:
    """Tests for feat command in branch mode."""

    def _make_git_side_effect(  # type: ignore[return]
        self,
        existing_branches: str = "",
    ) -> None:
        """Create a git side_effect function for branch mode tests."""

        def side_effect(*args: str, **kwargs: str) -> GitResult:
            if args[0] == "fetch":
                return GitResult(command="", returncode=0, stdout="", stderr="")
            if args[0] == "branch" and "--list" in args:
                return GitResult(command="", returncode=0, stdout=existing_branches, stderr="")
            if args[0] == "check-ref-format":
                return GitResult(command="", returncode=0, stdout=args[-1], stderr="")
            if args[0] == "checkout":
                return GitResult(command="", returncode=0, stdout="", stderr="")
            return GitResult(command="", returncode=0, stdout="", stderr="")

        return side_effect

    def test_creates_auto_numbered_branch(self, mocker):
        """Verify feat creates feat/1 when no feat branches exist."""
        # Given no existing feat branches and on main
        mocker.patch("gx.commands.feat.current_branch", return_value="main")
        mocker.patch("gx.commands.feat.default_branch", return_value="main")
        mocker.patch("gx.commands.feat.branch_exists", return_value=False)
        mock_git = mocker.patch(
            "gx.commands.feat.git",
            side_effect=self._make_git_side_effect(),
        )

        from gx.commands.feat import _create_branch

        # When creating a branch with no name
        _create_branch(name=None)

        # Then checkout is called with feat/1
        checkout_calls = [c for c in mock_git.call_args_list if c.args[0] == "checkout"]
        assert len(checkout_calls) == 1
        assert checkout_calls[0].args == ("checkout", "-b", "feat/1", "main")

    def test_creates_named_branch(self, mocker):
        """Verify feat --name creates feat/<name>."""
        # Given no existing feat branches and on main
        mocker.patch("gx.commands.feat.current_branch", return_value="main")
        mocker.patch("gx.commands.feat.default_branch", return_value="main")
        mocker.patch("gx.commands.feat.branch_exists", return_value=False)
        mock_git = mocker.patch(
            "gx.commands.feat.git",
            side_effect=self._make_git_side_effect(),
        )

        from gx.commands.feat import _create_branch

        # When creating a branch with name "login"
        _create_branch(name="login")

        # Then checkout is called with feat/login
        checkout_calls = [c for c in mock_git.call_args_list if c.args[0] == "checkout"]
        assert len(checkout_calls) == 1
        assert checkout_calls[0].args == ("checkout", "-b", "feat/login", "main")

    def test_errors_on_detached_head(self, mocker):
        """Verify feat errors when in detached HEAD state."""
        # Given detached HEAD state
        mocker.patch("gx.commands.feat.current_branch", return_value=None)

        from gx.commands.feat import _create_branch

        # When/Then creating a branch raises Exit
        with pytest.raises(typer.Exit):
            _create_branch(name=None)

    def test_warns_when_on_feat_branch(self, mocker, capsys):
        """Verify feat warns when currently on a feat/* branch."""
        # Given currently on a feat branch
        mocker.patch("gx.commands.feat.current_branch", return_value="feat/1")
        mocker.patch("gx.commands.feat.default_branch", return_value="main")
        mocker.patch("gx.commands.feat.branch_exists", return_value=False)
        mocker.patch(
            "gx.commands.feat.git",
            side_effect=self._make_git_side_effect(),
        )

        from gx.commands.feat import _create_branch

        # When creating a new named branch
        _create_branch(name="login")

        # Then a warning is printed mentioning the current branch
        captured = capsys.readouterr()
        assert "feat/1" in captured.err

    def test_errors_when_branch_exists(self, mocker):
        """Verify feat errors when target branch already exists."""
        # Given the target branch already exists
        mocker.patch("gx.commands.feat.current_branch", return_value="main")
        mocker.patch("gx.commands.feat.default_branch", return_value="main")
        mocker.patch("gx.commands.feat.branch_exists", return_value=True)
        mocker.patch(
            "gx.commands.feat.git",
            side_effect=self._make_git_side_effect(),
        )

        from gx.commands.feat import _create_branch

        # When/Then creating an existing branch raises Exit
        with pytest.raises(typer.Exit):
            _create_branch(name="login")

    def test_checkout_failure_suggests_stash(self, mocker, capsys):
        """Verify checkout failure from dirty tree suggests commit/stash."""
        # Given a dirty working tree that blocks checkout
        mocker.patch("gx.commands.feat.current_branch", return_value="main")
        mocker.patch("gx.commands.feat.default_branch", return_value="main")
        mocker.patch("gx.commands.feat.branch_exists", return_value=False)

        def side_effect(*args: str, **kwargs: str) -> GitResult:
            if args[0] == "fetch":
                return GitResult(command="", returncode=0, stdout="", stderr="")
            if args[0] == "branch" and "--list" in args:
                return GitResult(command="", returncode=0, stdout="", stderr="")
            if args[0] == "check-ref-format":
                return GitResult(command="", returncode=0, stdout="", stderr="")
            if args[0] == "checkout":
                return GitResult(
                    command="git checkout -b feat/1 main",
                    returncode=1,
                    stdout="",
                    stderr="error: Your local changes to the following files would be overwritten by checkout",
                )
            return GitResult(command="", returncode=0, stdout="", stderr="")

        mocker.patch("gx.commands.feat.git", side_effect=side_effect)

        from gx.commands.feat import _create_branch

        # When/Then checkout failure raises Exit and suggests stash/commit
        with pytest.raises(typer.Exit):
            _create_branch(name=None)

        captured = capsys.readouterr()
        assert "stash" in captured.err.lower() or "commit" in captured.err.lower()


class TestFeatWorktreeMode:
    """Tests for feat command in worktree mode."""

    def test_creates_worktree(self, mocker, tmp_path):
        """Verify feat --worktree creates worktree at correct path."""
        # Given we're on main with no conflicting branches
        mocker.patch("gx.commands.feat.current_branch", return_value="main")
        mocker.patch("gx.commands.feat.default_branch", return_value="main")
        mocker.patch("gx.commands.feat.branch_exists", return_value=False)
        mocker.patch("gx.commands.feat._resolve_branch_name", return_value="feat/1")
        mocker.patch("gx.commands.feat.repo_root", return_value=tmp_path)

        def git_side_effect(*args: str, **kwargs: str) -> GitResult:
            if args[0] == "fetch":
                return GitResult(command="", returncode=0, stdout="", stderr="")
            if args[0] == "check-ignore":
                return GitResult(command="", returncode=0, stdout=".worktrees", stderr="")
            return GitResult(command="", returncode=0, stdout="", stderr="")

        mocker.patch("gx.commands.feat.git", side_effect=git_side_effect)

        mock_create = mocker.patch(
            "gx.commands.feat.create_worktree",
            return_value=GitResult(
                command="", returncode=0, stdout="Preparing worktree", stderr=""
            ),
        )

        from gx.commands.feat import _create_worktree_branch

        # When creating a worktree branch
        _create_worktree_branch(name=None)

        # Then create_worktree was called with correct path and start point
        mock_create.assert_called_once_with(
            tmp_path / ".worktrees" / "feat" / "1",
            "feat/1",
            start_point="main",
        )

    def test_errors_on_detached_head(self, mocker):
        """Verify worktree mode errors on detached HEAD."""
        # Given detached HEAD state
        mocker.patch("gx.commands.feat.current_branch", return_value=None)

        from gx.commands.feat import _create_worktree_branch

        # When/Then creating a worktree raises Exit
        with pytest.raises(typer.Exit):
            _create_worktree_branch(name=None)

    def test_errors_when_worktrees_not_ignored(self, mocker, tmp_path):
        """Verify worktree mode errors when .worktrees/ is not gitignored."""
        # Given .worktrees/ is not gitignored
        mocker.patch("gx.commands.feat.current_branch", return_value="main")
        mocker.patch("gx.commands.feat.default_branch", return_value="main")
        mocker.patch("gx.commands.feat.branch_exists", return_value=False)
        mocker.patch("gx.commands.feat._resolve_branch_name", return_value="feat/1")
        mocker.patch("gx.commands.feat.repo_root", return_value=tmp_path)

        def git_side_effect(*args: str, **kwargs: str) -> GitResult:
            if args[0] == "fetch":
                return GitResult(command="", returncode=0, stdout="", stderr="")
            if args[0] == "check-ignore":
                return GitResult(command="", returncode=1, stdout="", stderr="")
            return GitResult(command="", returncode=0, stdout="", stderr="")

        mocker.patch("gx.commands.feat.git", side_effect=git_side_effect)

        from gx.commands.feat import _create_worktree_branch

        # When/Then creating worktree with un-ignored dir raises Exit
        with pytest.raises(typer.Exit):
            _create_worktree_branch(name=None)

    def test_errors_when_branch_exists(self, mocker):
        """Verify worktree mode errors when target branch already exists."""
        # Given target branch already exists
        mocker.patch("gx.commands.feat.current_branch", return_value="main")
        mocker.patch("gx.commands.feat.default_branch", return_value="main")
        mocker.patch("gx.commands.feat.branch_exists", return_value=True)
        mocker.patch("gx.commands.feat._resolve_branch_name", return_value="feat/1")
        mocker.patch(
            "gx.commands.feat.git",
            return_value=GitResult(command="", returncode=0, stdout="", stderr=""),
        )

        from gx.commands.feat import _create_worktree_branch

        # When/Then creating existing branch raises Exit
        with pytest.raises(typer.Exit):
            _create_worktree_branch(name=None)

    def test_skips_gitignore_check_for_absolute_worktree_path(self, mocker, tmp_path):
        """Verify absolute worktree directory skips the gitignore check."""
        from gx.lib.config import GxConfig

        # Given an absolute worktree directory configured (outside repo)
        abs_worktree = tmp_path.parent / "external-worktrees"
        mocker.patch(
            "gx.commands.feat.config",
            GxConfig(worktree_directory=str(abs_worktree)),
        )
        mocker.patch(
            "gx.commands.feat.resolve_worktree_directory",
            return_value=abs_worktree,
        )
        mocker.patch("gx.commands.feat.current_branch", return_value="main")
        mocker.patch("gx.commands.feat.default_branch", return_value="main")
        mocker.patch("gx.commands.feat.branch_exists", return_value=False)
        mocker.patch("gx.commands.feat._resolve_branch_name", return_value="feat/1")
        mocker.patch("gx.commands.feat.repo_root", return_value=tmp_path)

        mock_git = mocker.patch("gx.commands.feat.git")
        mock_git.return_value = GitResult(command="", returncode=0, stdout="", stderr="")

        mock_create = mocker.patch(
            "gx.commands.feat.create_worktree",
            return_value=GitResult(command="", returncode=0, stdout="", stderr=""),
        )

        from gx.commands.feat import _create_worktree_branch

        # When creating a worktree branch with absolute path config
        _create_worktree_branch(name=None)

        # Then check-ignore is never called and the worktree is still created
        check_ignore_calls = [
            c for c in mock_git.call_args_list if c.args and c.args[0] == "check-ignore"
        ]
        assert len(check_ignore_calls) == 0
        mock_create.assert_called_once()
