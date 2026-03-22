"""Tests for gx console output system."""

import pytest
import typer
from rich.text import Text

from gx.constants import Verbosity
from gx.lib.console import (
    GitHighlighter,
    console,
    debug,
    dryrun,
    err_console,
    error,
    get_verbosity,
    set_verbosity,
    step,
    trace,
    warning,
)


@pytest.fixture(autouse=True)
def _reset_verbosity() -> None:
    """Reset verbosity to INFO after each test."""
    yield
    set_verbosity(0)


class TestVerbosityState:
    """Tests for verbosity getter/setter."""

    def test_default_verbosity_is_info(self):
        """Verify default verbosity is INFO."""
        assert get_verbosity() == Verbosity.INFO

    def test_set_verbosity_debug(self):
        """Verify setting verbosity to DEBUG."""
        set_verbosity(1)
        assert get_verbosity() == Verbosity.DEBUG

    def test_set_verbosity_trace(self):
        """Verify setting verbosity to TRACE."""
        set_verbosity(2)
        assert get_verbosity() == Verbosity.TRACE

    def test_set_verbosity_clamps_high(self):
        """Verify values above TRACE are clamped to TRACE."""
        set_verbosity(99)
        assert get_verbosity() == Verbosity.TRACE

    def test_set_verbosity_clamps_low(self):
        """Verify negative values are clamped to INFO."""
        set_verbosity(-1)
        assert get_verbosity() == Verbosity.INFO


class TestConsoleInstances:
    """Tests for global console instances."""

    def test_console_writes_to_stdout(self):
        """Verify console is configured for stdout."""
        assert console.stderr is False

    def test_err_console_writes_to_stderr(self):
        """Verify err_console is configured for stderr."""
        assert console.stderr is False
        assert err_console.stderr is True


class TestStepContextManager:
    """Tests for step() context manager."""

    def test_step_prints_success_marker(self, capsys):
        """Verify step prints green checkmark on success."""
        with step("Do something"):
            pass
        captured = capsys.readouterr()
        assert "✓" in captured.out
        assert "Do something" in captured.out

    def test_step_prints_failure_marker_on_exception(self, capsys):
        """Verify step prints red X on exception and re-raises."""
        with pytest.raises(RuntimeError), step("Do something"):  # noqa: PT012
            msg = "boom"
            raise RuntimeError(msg)
        captured = capsys.readouterr()
        assert "✗" in captured.out
        assert "Do something" in captured.out

    def test_step_prints_failure_marker_on_typer_exit(self, capsys):
        """Verify step prints red X on typer.Exit and re-raises."""
        with pytest.raises(typer.Exit), step("Do something"):
            raise typer.Exit(1)
        captured = capsys.readouterr()
        assert "✗" in captured.out

    def test_step_sub_items_printed_after_marker(self, capsys):
        """Verify sub-items are printed after the success marker."""
        with step("Pull from origin") as s:
            s.sub("commit abc1234")
            s.sub("commit def5678")
        captured = capsys.readouterr()
        assert "│" in captured.out
        assert "abc1234" in captured.out
        assert "def5678" in captured.out

    def test_step_sub_items_printed_on_failure(self, capsys):
        """Verify sub-items are still printed when step fails."""
        with pytest.raises(RuntimeError), step("Do something") as s:  # noqa: PT012
            s.sub("partial result")
            msg = "boom"
            raise RuntimeError(msg)
        captured = capsys.readouterr()
        assert "partial result" in captured.out


class TestDebugHelper:
    """Tests for debug() output."""

    def test_debug_hidden_at_info_level(self, capsys):
        """Verify debug() produces no output at INFO verbosity."""
        debug("hidden")
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_debug_shown_at_debug_level(self, capsys):
        """Verify debug() prints to stdout at DEBUG verbosity."""
        set_verbosity(1)
        debug("visible")
        captured = capsys.readouterr()
        assert "›" in captured.out  # noqa: RUF001
        assert "visible" in captured.out

    def test_debug_shown_at_trace_level(self, capsys):
        """Verify debug() prints to stdout at TRACE verbosity."""
        set_verbosity(2)
        debug("visible")
        captured = capsys.readouterr()
        assert "›" in captured.out  # noqa: RUF001
        assert "visible" in captured.out


class TestTraceHelper:
    """Tests for trace() output."""

    def test_trace_hidden_at_info_level(self, capsys):
        """Verify trace() produces no output at INFO verbosity."""
        trace("hidden")
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_trace_hidden_at_debug_level(self, capsys):
        """Verify trace() produces no output at DEBUG verbosity."""
        set_verbosity(1)
        trace("hidden")
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_trace_shown_at_trace_level(self, capsys):
        """Verify trace() prints to stdout with git prefix at TRACE verbosity."""
        set_verbosity(2)
        trace("push origin main")
        captured = capsys.readouterr()
        assert "git>" in captured.out
        assert "push origin main" in captured.out


class TestWarningHelper:
    """Tests for warning() output."""

    def test_warning_prints_to_stderr(self, capsys):
        """Verify warning() prints to stderr."""
        warning("careful")
        captured = capsys.readouterr()
        assert "!" in captured.err
        assert "careful" in captured.err
        assert captured.out == ""


class TestWarningDetail:
    """Tests for warning() detail parameter."""

    def test_warning_detail_no_marker(self, capsys):
        """Verify detail=True omits the ! marker and indents."""
        warning("first line")
        warning("second line", detail=True)
        captured = capsys.readouterr()
        lines = captured.err.strip().split("\n")
        assert "!" in lines[0]
        assert "!" not in lines[1]


class TestErrorHelper:
    """Tests for error() output."""

    def test_error_prints_to_stderr(self, capsys):
        """Verify error() prints to stderr."""
        error("broken")
        captured = capsys.readouterr()
        assert "✗" in captured.err
        assert "broken" in captured.err
        assert captured.out == ""


class TestErrorDetail:
    """Tests for error() detail parameter."""

    def test_error_detail_no_marker(self, capsys):
        """Verify detail=True omits the X marker and indents."""
        error("first line")
        error("second line", detail=True)
        captured = capsys.readouterr()
        lines = captured.err.strip().split("\n")
        assert "✗" in lines[0]
        assert "✗" not in lines[1]


class TestDryrunHelper:
    """Tests for dryrun() output."""

    def test_dryrun_theme_is_bold_cyan(self):
        """Verify GX_THEME defines dryrun.message as bold cyan."""
        from gx.lib.console import GX_THEME

        assert GX_THEME.styles["dryrun.message"].bold is True
        assert GX_THEME.styles["dryrun.message"].color.name == "cyan"

    def test_dryrun_prints_at_info_level(self, capsys):
        """Verify dryrun() prints to stdout at default verbosity."""
        dryrun("git push origin main")
        captured = capsys.readouterr()
        assert "[DRY RUN]" in captured.out
        assert "git push origin main" in captured.out

    def test_dryrun_prints_at_debug_level(self, capsys):
        """Verify dryrun() prints to stdout at DEBUG verbosity."""
        set_verbosity(1)
        dryrun("git push origin main")
        captured = capsys.readouterr()
        assert "[DRY RUN]" in captured.out
        assert "git push origin main" in captured.out

    def test_dryrun_does_not_write_to_stderr(self, capsys):
        """Verify dryrun() writes to stdout, not stderr."""
        dryrun("git push origin main")
        captured = capsys.readouterr()
        assert captured.err == ""


class TestGitHighlighter:
    """Tests for GitHighlighter regex patterns."""

    @pytest.fixture
    def highlighter(self) -> GitHighlighter:
        """Return a GitHighlighter instance."""
        return GitHighlighter()

    def test_highlights_short_sha(self, highlighter: GitHighlighter) -> None:
        """Verify 7-char hex strings are highlighted as SHAs."""
        text = Text("0fa0a83 some message")
        highlighter.highlight(text)
        styles = [s.style for s in text._spans]
        assert "git.sha" in styles

    def test_highlights_commit_type(self, highlighter: GitHighlighter) -> None:
        """Verify angular commit types are highlighted."""
        text = Text("feat: add feature")
        highlighter.highlight(text)
        styles = [s.style for s in text._spans]
        assert "git.type" in styles

    def test_highlights_commit_scope(self, highlighter: GitHighlighter) -> None:
        """Verify commit scopes in parens are highlighted."""
        text = Text("feat(log): add feature")
        highlighter.highlight(text)
        styles = [s.style for s in text._spans]
        assert "git.scope" in styles

    def test_highlights_pr_reference(self, highlighter: GitHighlighter) -> None:
        """Verify PR references like (#3) are highlighted."""
        text = Text("add feature (#3)")
        highlighter.highlight(text)
        styles = [s.style for s in text._spans]
        assert "git.pr" in styles

    def test_no_false_positive_on_normal_text(self, highlighter: GitHighlighter) -> None:
        """Verify normal text gets no highlighting."""
        text = Text("hello world")
        highlighter.highlight(text)
        assert len(text._spans) == 0

    def test_highlights_colon_after_type(self, highlighter: GitHighlighter) -> None:
        """Verify colon after commit type is highlighted."""
        text = Text("feat: add feature")
        highlighter.highlight(text)
        styles = [s.style for s in text._spans]
        assert "git.colon" in styles
