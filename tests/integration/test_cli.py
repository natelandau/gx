"""Integration tests for gx CLI."""

from typer.testing import CliRunner

from gx.cli import app
from gx.lib.console import get_verbosity
from gx.lib.git import GitResult, get_dry_run
from tests.conftest import create_tmp_branch, create_tmp_commit

runner = CliRunner()


class TestVerbosityFlag:
    """Tests for -v/--verbose flag wiring."""

    def test_default_verbosity_is_info(self, tmp_git_repo):
        """Verify no flags results in INFO verbosity."""
        result = runner.invoke(app, ["pull", "-n"])
        assert result.exit_code == 0
        assert get_verbosity().value == 0

    def test_single_v_sets_debug(self, tmp_git_repo):
        """Verify -v sets DEBUG verbosity."""
        result = runner.invoke(app, ["-v", "pull", "-n"])
        assert result.exit_code == 0
        assert get_verbosity().value == 1

    def test_double_v_sets_trace(self, tmp_git_repo):
        """Verify -vv sets TRACE verbosity."""
        result = runner.invoke(app, ["-vv", "pull", "-n"])
        assert result.exit_code == 0
        assert get_verbosity().value == 2

    def test_verbose_long_form(self, tmp_git_repo):
        """Verify --verbose sets DEBUG verbosity."""
        result = runner.invoke(app, ["--verbose", "pull", "-n"])
        assert result.exit_code == 0
        assert get_verbosity().value == 1

    def test_v_after_subcommand(self, tmp_git_repo):
        """Verify -v works after the subcommand name."""
        result = runner.invoke(app, ["pull", "-v", "-n"])
        assert result.exit_code == 0
        assert get_verbosity().value == 1

    def test_vv_after_subcommand(self, tmp_git_repo):
        """Verify -vv works after the subcommand name."""
        runner.invoke(app, ["pull", "-vv", "-n"])
        assert get_verbosity().value == 2


class TestHelpOutput:
    """Tests for help text output."""

    def test_bare_gx_in_repo_runs_status(self, mocker):
        """Verify bare gx invocation inside a repo runs status instead of help."""
        mocker.patch("gx.commands.status.check_git_repo", autospec=True)
        mocker.patch(
            "gx.commands.status.git",
            return_value=GitResult(command="git status", returncode=0, stdout="", stderr=""),
        )
        mocker.patch("gx.commands.status.current_branch", return_value="main")
        mocker.patch("gx.commands.status.default_branch", return_value="main")
        mocker.patch("gx.commands.status.all_local_branches", return_value=frozenset({"main"}))
        mocker.patch("gx.commands.status.list_worktrees", return_value=[])
        mocker.patch("gx.commands.status.stash_counts", return_value={})
        mocker.patch("gx.commands.status.ahead_behind", return_value=(0, 0))
        mocker.patch("gx.commands.status.tracking_remote_ref", return_value=None)

        result = runner.invoke(app, [])
        # Bare gx runs status; the current branch is always shown in the table
        assert result.exit_code == 0
        assert "Branch Status" in result.output

    def test_help_flag(self):
        """Verify --help flag prints help text."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "push" in result.output
        assert "status" in result.output


class TestDryRunFlag:
    """Tests for --dry-run/-n flag wiring."""

    def test_default_dry_run_is_false(self, tmp_git_repo):
        """Verify no flags results in dry-run False."""
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert get_dry_run() is False

    def test_dry_run_long_form(self, tmp_git_repo):
        """Verify --dry-run sets dry-run True."""
        create_tmp_branch(tmp_git_repo, "feat/test")
        create_tmp_commit(tmp_git_repo, "test work")
        result = runner.invoke(app, ["push", "--dry-run"])
        assert result.exit_code == 0
        assert get_dry_run() is True

    def test_dry_run_short_form(self, tmp_git_repo):
        """Verify -n sets dry-run True."""
        create_tmp_branch(tmp_git_repo, "feat/test")
        create_tmp_commit(tmp_git_repo, "test work")
        result = runner.invoke(app, ["push", "-n"])
        assert result.exit_code == 0
        assert get_dry_run() is True

    def test_dry_run_on_pull(self, tmp_git_repo):
        """Verify --dry-run works on pull subcommand."""
        runner.invoke(app, ["pull", "--dry-run"])
        assert get_dry_run() is True

    def test_dry_run_on_feat(self, tmp_git_repo):
        """Verify --dry-run works on feat subcommand."""
        result = runner.invoke(app, ["feat", "--dry-run"])
        assert result.exit_code == 0
        assert get_dry_run() is True

    def test_dry_run_on_clean(self, tmp_git_repo):
        """Verify --dry-run works on clean subcommand."""
        result = runner.invoke(app, ["clean", "--dry-run"])
        assert result.exit_code == 0
        assert get_dry_run() is True


def test_clean_shows_help():
    """Verify clean command is registered and shows help."""
    result = runner.invoke(app, ["clean", "--help"])
    assert result.exit_code == 0
    assert "Remove branches and worktrees" in result.output


def test_done_shows_help():
    """Verify done command is registered and shows help."""
    result = runner.invoke(app, ["done", "--help"])
    assert result.exit_code == 0
    assert "Switch back to the default branch" in result.output


def test_dry_run_on_done(tmp_git_repo):
    """Verify --dry-run works on done subcommand."""
    runner.invoke(app, ["done", "--dry-run"])
    assert get_dry_run() is True


class TestDryRunOutput:
    """Tests for dry-run output content."""

    def test_dry_run_push_shows_dryrun_prefix(self, tmp_git_repo):
        """Verify dry-run push output contains [DRY RUN] prefix."""
        create_tmp_branch(tmp_git_repo, "feat/test")
        create_tmp_commit(tmp_git_repo, "test work")
        result = runner.invoke(app, ["push", "-n"])
        assert "[DRY RUN]" in result.output
        assert "git push" in result.output
