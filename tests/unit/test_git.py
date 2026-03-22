"""Tests for gx git subprocess library."""

import subprocess

import pytest
import typer

from gx.lib.console import set_verbosity
from gx.lib.git import (
    GitResult,
    _is_read_only,
    check_git_installed,
    check_git_repo,
    get_dry_run,
    git,
    set_dry_run,
)


class TestGitResult:
    """Tests for GitResult dataclass."""

    def test_success_when_zero_returncode(self):
        """Verify success is True when returncode is 0."""
        result = GitResult(command="git status", returncode=0, stdout="clean", stderr="")
        assert result.success is True

    def test_failure_when_nonzero_returncode(self):
        """Verify success is False when returncode is non-zero."""
        result = GitResult(command="git push", returncode=1, stdout="", stderr="rejected")
        assert result.success is False

    def test_raise_on_error_returns_self_on_success(self):
        """Verify raise_on_error returns self when command succeeded."""
        result = GitResult(command="git status", returncode=0, stdout="ok", stderr="")
        assert result.raise_on_error() is result

    def test_raise_on_error_exits_on_failure(self):
        """Verify raise_on_error raises typer.Exit on failure."""
        result = GitResult(command="git push", returncode=1, stdout="", stderr="rejected")
        with pytest.raises(typer.Exit):
            result.raise_on_error()

    def test_raise_on_error_prints_stderr(self, capsys):
        """Verify raise_on_error prints stderr via error()."""
        result = GitResult(command="git push", returncode=1, stdout="", stderr="access denied")
        with pytest.raises(typer.Exit):
            result.raise_on_error()
        captured = capsys.readouterr()
        assert "access denied" in captured.err

    def test_raise_on_error_prints_command_when_no_stderr(self, capsys):
        """Verify raise_on_error prints command when stderr is empty."""
        result = GitResult(command="git push", returncode=128, stdout="", stderr="")
        with pytest.raises(typer.Exit):
            result.raise_on_error()
        captured = capsys.readouterr()
        assert "git push" in captured.err

    def test_frozen_dataclass(self):
        """Verify GitResult is immutable."""
        result = GitResult(command="git status", returncode=0, stdout="", stderr="")
        with pytest.raises(AttributeError):
            result.returncode = 1  # type: ignore[misc]


class TestDryRunState:
    """Tests for dry-run getter/setter."""

    def test_default_dry_run_is_false(self):
        """Verify dry-run is False by default."""
        assert get_dry_run() is False

    def test_set_dry_run_true(self):
        """Verify setting dry-run to True."""
        set_dry_run(enabled=True)
        assert get_dry_run() is True

    def test_set_dry_run_false(self):
        """Verify setting dry-run back to False."""
        set_dry_run(enabled=True)
        set_dry_run(enabled=False)
        assert get_dry_run() is False


class TestReadOnlyClassification:
    """Tests for read-only command detection."""

    @pytest.mark.parametrize(
        "args",
        [
            ("status",),
            ("log", "--oneline", "-5"),
            ("diff", "--quiet"),
            ("show", "HEAD"),
            ("rev-parse", "--is-inside-work-tree"),
            ("remote", "-v"),
            ("config", "user.name"),
            ("ls-files",),
            ("describe", "--tags"),
        ],
    )
    def test_read_only_commands(self, args: tuple[str, ...]):
        """Verify known read-only commands are classified correctly."""
        assert _is_read_only(args) is True

    @pytest.mark.parametrize(
        "args",
        [
            ("push", "origin", "main"),
            ("pull",),
            ("merge", "feature"),
            ("commit", "-m", "msg"),
            ("checkout", "-b", "new"),
            ("branch", "-d", "old"),
            ("tag", "v1.0"),
            ("stash", "pop"),
            ("reset", "--hard"),
            ("rebase", "main"),
        ],
    )
    def test_mutating_commands(self, args: tuple[str, ...]):
        """Verify mutating commands are classified correctly."""
        assert _is_read_only(args) is False

    def test_empty_args(self):
        """Verify empty args are classified as mutating (safe default)."""
        assert _is_read_only(()) is False

    @pytest.mark.parametrize(
        "args",
        [
            ("branch", "--merged"),
            ("branch", "--merged", "main"),
            ("branch", "-vv"),
            ("branch", "--list"),
            ("branch", "-l"),
            ("branch", "-a"),
            ("branch", "-r"),
            ("worktree", "list"),
            ("worktree", "list", "--porcelain"),
            ("symbolic-ref", "refs/remotes/origin/HEAD"),
            ("merge-base", "main", "feature"),
            ("for-each-ref", "refs/heads"),
            ("rev-list", "--count", "main..feature"),
        ],
    )
    def test_compound_read_only_commands(self, args: tuple[str, ...]):
        """Verify compound and new simple read-only commands are classified correctly."""
        assert _is_read_only(args) is True

    @pytest.mark.parametrize(
        "args",
        [
            ("branch", "-d", "old"),
            ("branch", "-D", "old"),
            ("branch", "new-branch"),
            ("worktree", "add", ".worktrees/feat", "-b", "feat"),
            ("worktree", "remove", ".worktrees/feat"),
            ("worktree", "prune"),
        ],
    )
    def test_compound_mutating_commands(self, args: tuple[str, ...]):
        """Verify compound mutating commands are classified correctly."""
        assert _is_read_only(args) is False


class TestGitFunction:
    """Tests for the git() function."""

    def test_successful_command(self, mocker):
        """Verify git() returns GitResult with captured output."""
        # Given a mocked subprocess that succeeds
        mocker.patch(
            "gx.lib.git.subprocess.run",
            autospec=True,
            return_value=subprocess.CompletedProcess(
                args=["git", "status"],
                returncode=0,
                stdout="on branch main\n",
                stderr="",
            ),
        )

        # When running a git command
        result = git("status")

        # Then the result captures the output
        assert result.success is True
        assert result.stdout == "on branch main"
        assert result.command == "git status"

    def test_failed_command(self, mocker):
        """Verify git() captures non-zero exit codes."""
        # Given a mocked subprocess that fails
        mocker.patch(
            "gx.lib.git.subprocess.run",
            autospec=True,
            return_value=subprocess.CompletedProcess(
                args=["git", "push"],
                returncode=1,
                stdout="",
                stderr="rejected\n",
            ),
        )

        # When running a git command
        result = git("push", "origin", "main")

        # Then the result captures the failure
        assert result.success is False
        assert result.stderr == "rejected"

    def test_passes_timeout(self, mocker):
        """Verify git() passes timeout to subprocess.run."""
        # Given a mocked subprocess
        mock_run = mocker.patch(
            "gx.lib.git.subprocess.run",
            autospec=True,
            return_value=subprocess.CompletedProcess(
                args=["git", "status"], returncode=0, stdout="", stderr=""
            ),
        )

        # When running with a custom timeout
        git("status", timeout=60)

        # Then subprocess.run receives the timeout
        mock_run.assert_called_once_with(
            ["git", "status"], capture_output=True, text=True, timeout=60, cwd=None
        )

    def test_default_timeout(self, mocker):
        """Verify git() uses 30 second default timeout."""
        # Given a mocked subprocess
        mock_run = mocker.patch(
            "gx.lib.git.subprocess.run",
            autospec=True,
            return_value=subprocess.CompletedProcess(
                args=["git", "status"], returncode=0, stdout="", stderr=""
            ),
        )

        # When running without explicit timeout
        git("status")

        # Then subprocess.run receives 30s timeout
        mock_run.assert_called_once_with(
            ["git", "status"], capture_output=True, text=True, timeout=30, cwd=None
        )

    def test_dry_run_skips_mutating_command(self):
        """Verify dry-run returns synthetic result for mutating commands."""
        # Given dry-run is active
        set_dry_run(enabled=True)

        # When running a mutating command
        result = git("push", "origin", "main")

        # Then a synthetic success result is returned without calling subprocess
        assert result.success is True
        assert result.stdout == ""
        assert result.stderr == ""
        assert "git push origin main" in result.command

    def test_dry_run_executes_read_only_command(self, mocker):
        """Verify dry-run still executes read-only commands."""
        # Given dry-run is active
        set_dry_run(enabled=True)

        # Given a mocked subprocess
        mocker.patch(
            "gx.lib.git.subprocess.run",
            autospec=True,
            return_value=subprocess.CompletedProcess(
                args=["git", "status"],
                returncode=0,
                stdout="on branch main\n",
                stderr="",
            ),
        )

        # When running a read-only command
        result = git("status")

        # Then the command is actually executed
        assert result.stdout == "on branch main"

    def test_dry_run_calls_dryrun_helper(self, mocker):
        """Verify dry-run uses dryrun() helper for skipped commands."""
        # Given dry-run is active
        set_dry_run(enabled=True)

        # Given dryrun() is mocked
        mock_dryrun = mocker.patch("gx.lib.git.dryrun", autospec=True)

        # When running a mutating command
        git("push", "origin", "main")

        # Then dryrun() is called with the command string
        mock_dryrun.assert_called_once_with("git push origin main")

    def test_dry_run_no_doubling_at_debug_verbosity(self, capsys):
        """Verify skipped command is printed exactly once with -v."""
        # Given dry-run is active and verbosity is DEBUG
        set_dry_run(enabled=True)
        set_verbosity(1)

        # When running a mutating command
        git("push", "origin", "main")

        # Then the command string appears exactly once in stdout
        captured = capsys.readouterr()
        assert captured.out.count("git push origin main") == 1

    def test_debug_logs_command(self, mocker, capsys):
        """Verify git() logs command via debug() at verbosity DEBUG."""
        # Given verbosity is DEBUG
        set_verbosity(1)

        # Given a mocked subprocess
        mocker.patch(
            "gx.lib.git.subprocess.run",
            autospec=True,
            return_value=subprocess.CompletedProcess(
                args=["git", "status"], returncode=0, stdout="", stderr=""
            ),
        )

        # When running a command
        git("status")

        # Then the command is logged via debug()
        captured = capsys.readouterr()
        assert "git status" in captured.out

    def test_trace_pipes_stdout(self, mocker, capsys):
        """Verify git() pipes stdout lines through trace() at verbosity TRACE."""
        # Given verbosity is TRACE
        set_verbosity(2)

        # Given a mocked subprocess with stdout
        mocker.patch(
            "gx.lib.git.subprocess.run",
            autospec=True,
            return_value=subprocess.CompletedProcess(
                args=["git", "log"],
                returncode=0,
                stdout="abc1234 first commit\ndef5678 second commit\n",
                stderr="",
            ),
        )

        # When running a command
        git("log", "--oneline")

        # Then stdout lines are piped through trace()
        captured = capsys.readouterr()
        assert "git>" in captured.out
        assert "first commit" in captured.out
        assert "second commit" in captured.out

    def test_trace_pipes_stderr(self, mocker, capsys):
        """Verify git() pipes stderr lines through trace() at verbosity TRACE."""
        # Given verbosity is TRACE
        set_verbosity(2)

        # Given a mocked subprocess with stderr
        mocker.patch(
            "gx.lib.git.subprocess.run",
            autospec=True,
            return_value=subprocess.CompletedProcess(
                args=["git", "push"],
                returncode=0,
                stdout="",
                stderr="Enumerating objects: 5, done.\n",
            ),
        )

        # When running a command
        git("push")

        # Then stderr lines are piped through trace()
        captured = capsys.readouterr()
        assert "Enumerating objects" in captured.out


class TestGitCwd:
    """Tests for the cwd parameter on git()."""

    def test_git_passes_cwd_to_subprocess(self, mocker, tmp_path):
        """Verify git() passes cwd to subprocess.run when provided."""
        # Given
        mock_run = mocker.patch("gx.lib.git.subprocess.run", autospec=True)
        mock_run.return_value = mocker.Mock(returncode=0, stdout="", stderr="")

        # When
        git("status", cwd=tmp_path)

        # Then
        _, kwargs = mock_run.call_args
        assert kwargs["cwd"] == tmp_path

    def test_git_cwd_defaults_to_none(self, mocker):
        """Verify git() does not pass cwd when not provided."""
        # Given
        mock_run = mocker.patch("gx.lib.git.subprocess.run", autospec=True)
        mock_run.return_value = mocker.Mock(returncode=0, stdout="", stderr="")

        # When
        git("status")

        # Then
        _, kwargs = mock_run.call_args
        assert kwargs.get("cwd") is None


class TestCheckGitRepo:
    """Tests for check_git_repo()."""

    def test_succeeds_in_git_repo(self, mocker):
        """Verify check_git_repo() passes when inside a git repo."""
        # Given git rev-parse succeeds
        mocker.patch(
            "gx.lib.git.subprocess.run",
            autospec=True,
            return_value=subprocess.CompletedProcess(
                args=["git", "rev-parse", "--is-inside-work-tree"],
                returncode=0,
                stdout="true\n",
                stderr="",
            ),
        )

        # When checking for a git repo
        # Then no exception is raised
        check_git_repo()

    def test_exits_outside_git_repo(self, mocker):
        """Verify check_git_repo() raises typer.Exit outside a git repo."""
        # Given git rev-parse fails
        mocker.patch(
            "gx.lib.git.subprocess.run",
            autospec=True,
            return_value=subprocess.CompletedProcess(
                args=["git", "rev-parse", "--is-inside-work-tree"],
                returncode=128,
                stdout="",
                stderr="fatal: not a git repository\n",
            ),
        )

        # When checking for a git repo
        # Then typer.Exit is raised
        with pytest.raises(typer.Exit):
            check_git_repo()

    def test_prints_error_outside_git_repo(self, mocker, capsys):
        """Verify check_git_repo() prints error message outside a git repo."""
        # Given git rev-parse fails
        mocker.patch(
            "gx.lib.git.subprocess.run",
            autospec=True,
            return_value=subprocess.CompletedProcess(
                args=["git", "rev-parse", "--is-inside-work-tree"],
                returncode=128,
                stdout="",
                stderr="fatal: not a git repository\n",
            ),
        )

        # When checking for a git repo
        with pytest.raises(typer.Exit):
            check_git_repo()

        # Then an error message is printed
        captured = capsys.readouterr()
        assert "Not a git repository" in captured.err


class TestCheckGitInstalled:
    """Tests for check_git_installed()."""

    def test_passes_when_git_found(self, mocker):
        """Verify check_git_installed() passes when git is on PATH."""
        # Given git is found on PATH
        mocker.patch("gx.lib.git.shutil.which", autospec=True, return_value="/usr/bin/git")

        # When checking for git
        # Then no exception is raised
        check_git_installed()

    def test_exits_when_git_not_found(self, mocker):
        """Verify check_git_installed() raises typer.Exit when git is missing."""
        # Given git is not found on PATH
        mocker.patch("gx.lib.git.shutil.which", autospec=True, return_value=None)

        # When checking for git
        # Then typer.Exit is raised
        with pytest.raises(typer.Exit):
            check_git_installed()

    def test_prints_error_when_git_not_found(self, mocker, capsys):
        """Verify check_git_installed() prints error message when git is missing."""
        # Given git is not found on PATH
        mocker.patch("gx.lib.git.shutil.which", autospec=True, return_value=None)

        # When checking for git
        with pytest.raises(typer.Exit):
            check_git_installed()

        # Then an error message is printed
        captured = capsys.readouterr()
        assert "git is not installed" in captured.err
