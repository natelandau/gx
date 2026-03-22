# Output Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace flat green `info()` output with spinner-based `step()` context manager, semantic git highlighting, and styled print helpers across all commands.

**Architecture:** New `step()` context manager in `console.py` wraps operations with Rich `Status` spinner, prints `✓`/`✗` markers on completion. `GitHighlighter` applies regex-based coloring to SHAs, commit types, scopes, and PR refs. Commands refactored to use `step()` instead of `info()`. Error/warning helpers gain `detail` parameter for bold-first / normal-rest pattern.

**Tech Stack:** Python 3.13+, Rich (Console, Status, RegexHighlighter, Theme), Typer, pytest + pytest-mock

**Spec:** `docs/specs/2026-03-21-output-redesign-design.md`

---

### Task 1: Add GitHighlighter and update theme in console.py

**Files:**
- Modify: `src/gx/lib/console.py`
- Test: `tests/unit/test_console.py`

- [ ] **Step 1: Write failing tests for GitHighlighter**

Add to `tests/unit/test_console.py`:

```python
from gx.lib.console import GitHighlighter

class TestGitHighlighter:
    """Tests for GitHighlighter regex patterns."""

    @pytest.fixture
    def highlighter(self) -> GitHighlighter:
        return GitHighlighter()

    def test_highlights_short_sha(self, highlighter):
        """Verify 7-char hex strings are highlighted as SHAs."""
        text = Text("0fa0a83 some message")
        highlighter.highlight(text)
        styles = [s.style for s in text._spans]
        assert "git.sha" in styles

    def test_highlights_commit_type(self, highlighter):
        """Verify angular commit types are highlighted."""
        text = Text("feat: add feature")
        highlighter.highlight(text)
        style = text._spans[0].style
        assert style == "git.type"

    def test_highlights_commit_scope(self, highlighter):
        """Verify commit scopes in parens are highlighted."""
        text = Text("feat(log): add feature")
        highlighter.highlight(text)
        styles = [s.style for s in text._spans]
        assert "git.scope" in styles

    def test_highlights_pr_reference(self, highlighter):
        """Verify PR references like (#3) are highlighted."""
        text = Text("add feature (#3)")
        highlighter.highlight(text)
        styles = [s.style for s in text._spans]
        assert "git.pr" in styles

    def test_no_false_positive_on_normal_text(self, highlighter):
        """Verify normal text gets no highlighting."""
        text = Text("hello world")
        highlighter.highlight(text)
        assert len(text._spans) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/natelandau/repos/gx/.worktrees/feat/output-redesign && uv run pytest tests/unit/test_console.py::TestGitHighlighter -v`
Expected: ImportError — `GitHighlighter` does not exist yet.

- [ ] **Step 3: Implement GitHighlighter and update theme**

In `src/gx/lib/console.py`, add the import and class at the top, then replace `GX_THEME` with the new theme. Keep all existing theme keys that other commands use (like `log_sha`, `branch_current`, etc.) — only add/change the output-related keys.

```python
from rich.highlighter import RegexHighlighter

class GitHighlighter(RegexHighlighter):
    """Highlight git-related tokens in output text."""

    base_style = "git."
    highlights = [
        r"(?P<sha>\b[0-9a-f]{7,12}\b)",
        r"(?P<type>(?:feat|fix|refactor|perf|build|ci|docs|style|test|chore|bump))"
        r"(?P<scope>\([^)]+\))?(?P<colon>:)",
        r"(?P<pr>\(#\d+\))",
    ]
```

Add to `GX_THEME`:
```python
"step.success": "green",
"step.fail": "red",
"step.message": "bold default",
"step.spinner": "cyan",
"sub.pipe": "bright_black",
"git.sha": "yellow",
"git.type": "cyan",
"git.scope": "blue",
"git.colon": "default",
"git.pr": "magenta",
```

Replace the old `"info"` key with the new step keys. Keep `"debug"`, `"dryrun"`, `"trace"`, `"warning"`, `"error"` but update their values:

```python
"debug.marker": "cyan",
"debug.message": "cyan",
"trace.marker": "bright_black",
"trace.message": "bright_black",
"warning.marker": "yellow",
"warning.message": "bold yellow",
"warning.detail": "yellow",
"error.marker": "bold red",
"error.message": "bold red",
"error.detail": "red",
"dryrun.marker": "bold cyan",
"dryrun.message": "bold cyan",
```

Apply the highlighter to the console:
```python
highlighter = GitHighlighter()
console = Console(theme=GX_THEME, highlighter=highlighter)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/natelandau/repos/gx/.worktrees/feat/output-redesign && uv run pytest tests/unit/test_console.py::TestGitHighlighter -v`
Expected: PASS

- [ ] **Step 5: Run linters**

Run: `cd /Users/natelandau/repos/gx/.worktrees/feat/output-redesign && uv run ruff check src/gx/lib/console.py && uv run ruff format src/gx/lib/console.py tests/unit/test_console.py`

- [ ] **Step 6: Commit**

```
feat(console): add GitHighlighter and update theme

Semantic highlighting for SHAs, commit types, scopes, and PR
references. Updated theme with step, sub, and new helper styles.
```

---

### Task 2: Add step() context manager and update print helpers

**Files:**
- Modify: `src/gx/lib/console.py`
- Test: `tests/unit/test_console.py`

- [ ] **Step 1: Write failing tests for step() context manager**

Add to `tests/unit/test_console.py`:

```python
import typer

from gx.lib.console import step

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
        with pytest.raises(RuntimeError):
            with step("Do something"):
                msg = "boom"
                raise RuntimeError(msg)
        captured = capsys.readouterr()
        assert "✗" in captured.out
        assert "Do something" in captured.out

    def test_step_prints_failure_marker_on_typer_exit(self, capsys):
        """Verify step prints red X on typer.Exit and re-raises."""
        with pytest.raises(SystemExit):
            with step("Do something"):
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
        with pytest.raises(RuntimeError):
            with step("Do something") as s:
                s.sub("partial result")
                msg = "boom"
                raise RuntimeError(msg)
        captured = capsys.readouterr()
        assert "partial result" in captured.out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/natelandau/repos/gx/.worktrees/feat/output-redesign && uv run pytest tests/unit/test_console.py::TestStepContextManager -v`
Expected: ImportError — `step` does not exist yet.

- [ ] **Step 3: Implement step() context manager and Step dataclass**

Add to `src/gx/lib/console.py`:

```python
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator

@dataclass
class Step:
    """Collects sub-items during a step for printing after completion."""

    message: str
    _subs: list[str] = field(default_factory=list, init=False)

    def sub(self, text: str) -> None:
        """Queue a sub-item to print after the step completes."""
        self._subs.append(text)


@contextmanager
def step(message: str) -> Generator[Step, None, None]:
    """Show a spinner while the block runs, then a completion marker.

    On success, prints a green ✓ followed by the message. On any exception
    (including typer.Exit), prints a red ✗ then re-raises. Sub-items queued
    via Step.sub() are printed after the marker with a gray pipe prefix.
    """
    s = Step(message)
    try:
        with console.status(
            f"[step.message]{message}...[/]",
            spinner="dots",
            spinner_style="step.spinner",
        ):
            yield s
        console.print(f"[step.success]✓[/] [step.message]{message}[/]")
    except BaseException:
        console.print(f"[step.fail]✗[/] [step.message]{message}[/]")
        raise
    finally:
        for sub_text in s._subs:
            console.print(f"  [sub.pipe]│[/] {sub_text}")
```

- [ ] **Step 4: Update print helpers**

Update existing helpers in `src/gx/lib/console.py`. Remove `info()`. Update `debug()`, `trace()`, `warning()`, `error()`:

```python
def debug(message: str, **kwargs: Any) -> None:
    """Print debug-level output to stdout. Shown with -v or higher."""
    if _verbosity >= Verbosity.DEBUG:
        console.print(f"  [debug.marker]›[/] [debug.message]{message}[/]", **kwargs)


def trace(message: str, **kwargs: Any) -> None:
    """Print trace-level git output to stdout. Shown with -vv."""
    if _verbosity >= Verbosity.TRACE:
        console.print(f"    [trace.marker]git>[/] [trace.message]{message}[/]", **kwargs)


def warning(message: str, *, detail: bool = False, **kwargs: Any) -> None:
    """Print warning output to stderr. First call bold, detail=True for subsequent lines."""
    style = "warning.detail" if detail else "warning.message"
    marker = "" if detail else "[warning.marker]![/] "
    prefix = "    " if detail else ""
    err_console.print(f"{marker}{prefix}[{style}]{message}[/]", **kwargs)


def error(message: str, *, detail: bool = False, **kwargs: Any) -> None:
    """Print error output to stderr. First call bold, detail=True for subsequent lines."""
    style = "error.detail" if detail else "error.message"
    marker = "" if detail else "[error.marker]✗[/] "
    prefix = "    " if detail else ""
    err_console.print(f"{marker}{prefix}[{style}]{message}[/]", **kwargs)
```

- [ ] **Step 5: Write tests for updated warning/error detail parameter**

```python
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


class TestErrorDetail:
    """Tests for error() detail parameter."""

    def test_error_detail_no_marker(self, capsys):
        """Verify detail=True omits the ✗ marker and indents."""
        error("first line")
        error("second line", detail=True)
        captured = capsys.readouterr()
        lines = captured.err.strip().split("\n")
        assert "✗" in lines[0]
        assert "✗" not in lines[1]
```

- [ ] **Step 6: Run all console tests**

Run: `cd /Users/natelandau/repos/gx/.worktrees/feat/output-redesign && uv run pytest tests/unit/test_console.py -v`
Expected: PASS. Some existing tests for `info()` will fail since it's been removed — update those next.

- [ ] **Step 7: Update existing console tests**

Specific changes needed in `tests/unit/test_console.py`:

1. **Remove** `TestInfoHelper` class entirely (2 tests)
2. **Update imports:** remove `info` from the import list, add `step, Step, GitHighlighter`
3. **Add `import typer`** at the top of the file (needed by `TestStepContextManager`)
4. **Add `from rich.text import Text`** (needed by `TestGitHighlighter`)
5. **Update `TestDryrunHelper.test_dryrun_theme_is_bold_cyan`:** change `GX_THEME.styles["dryrun"]` to `GX_THEME.styles["dryrun.message"]`
6. **Update `TestDebugHelper` assertions:** debug output now includes the `›` marker prefix, so assert `"›" in captured.out` and `"visible" in captured.out`
7. **Update `TestTraceHelper` assertions:** trace output prefix changed from `"  git> "` to `"    git>"`, update the assertion accordingly
8. **Update `TestWarningHelper` and `TestErrorHelper`:** warning output now includes `!` marker, error output now includes `✗` marker — update assertions to check for these markers

Also update the `dryrun()` helper itself — add marker styling:
```python
def dryrun(message: str, **kwargs: Any) -> None:
    """Print a dry-run notice to stdout."""
    console.print(f"[dryrun.marker]\\[DRY RUN][/] [dryrun.message]{message}[/]", **kwargs)
```
Note: the `[` in `[DRY RUN]` must be escaped as `\\[` in Rich markup to avoid being interpreted as a style tag.

- [ ] **Step 8: Run full console test suite**

Run: `cd /Users/natelandau/repos/gx/.worktrees/feat/output-redesign && uv run pytest tests/unit/test_console.py -v`
Expected: All PASS.

- [ ] **Step 9: Run linters**

Run: `cd /Users/natelandau/repos/gx/.worktrees/feat/output-redesign && uv run ruff check src/gx/lib/console.py && uv run ruff format src/gx/lib/console.py tests/unit/test_console.py`

- [ ] **Step 10: Commit**

```
feat(console): add step() context manager and update helpers

Replace info() with step() spinner-based context manager. Update
warning/error with detail parameter for bold-first pattern. Add
styled markers for debug (›) and trace (git>).
```

---

### Task 3: Verify git.py raise_on_error() compatibility

**Files:**
- Review: `src/gx/lib/git.py`
- Test: `tests/unit/test_git.py`

The `raise_on_error()` method calls `error()` (stderr) before raising `typer.Exit(1)`. The `step()` `✗` marker prints to stdout. These are separate streams, so there is no visual duplication — keep `raise_on_error()` as-is. The user sees `✗ Step message` on stdout and the git stderr on stderr.

However, the `error()` import in `git.py` now references the updated `error()` with its `detail` keyword. Verify the call in `raise_on_error()` still works (it passes no `detail` kwarg, so it defaults to `False` — bold first line behavior, which is correct).

- [ ] **Step 1: Read current test_git.py to verify existing tests still pass**

Read: `tests/unit/test_git.py`

- [ ] **Step 2: Run tests to confirm no breakage**

Run: `cd /Users/natelandau/repos/gx/.worktrees/feat/output-redesign && uv run pytest tests/unit/test_git.py -v`
Expected: PASS — no changes needed to `git.py` or its tests.

- [ ] **Step 3: Verify error() import works with updated signature**

The `error()` function in `console.py` now has signature `error(message: str, *, detail: bool = False, **kwargs: Any)`. The call `error(self.stderr or f"Command failed: {self.command}")` in `raise_on_error()` passes only a positional string — this is compatible. No change needed.

---

### Task 4: Refactor pull.py to use step()

**Files:**
- Modify: `src/gx/commands/pull.py`
- Test: `tests/unit/test_pull.py`, `tests/integration/test_pull.py`

- [ ] **Step 1: Refactor pull.py**

Replace all `info()` calls with `step()` blocks. Update messages to active tense. Key changes:

In `stash_if_dirty()`:
```python
def stash_if_dirty() -> bool:
    if not is_dirty():
        return False

    with step("Stash local changes"):
        git("stash", "--include-untracked").raise_on_error()
    return True
```

In `fetch_and_rebase()`:
```python
def fetch_and_rebase(remote: str, remote_branch: str, *, stashed: bool) -> None:
    with step(f"Fetch from {remote}"):
        result = git("fetch", remote)
        if not result.success:
            rollback(stashed=stashed)

    with step(f"Pull with rebase from {remote}/{remote_branch}"):
        result = git("pull", "--rebase", remote, remote_branch)
        if not result.success:
            if is_rebase_in_progress():
                error("Rebase conflict detected")
                error("1. Fix the conflicts in the affected files", detail=True)
                error("2. Stage the resolved files with 'git add'", detail=True)
                error("3. Continue with 'git rebase --continue'", detail=True)
                error("Or abort with 'git rebase --abort'", detail=True)
            else:
                error(f"Failed to pull from {remote}/{remote_branch}")
            rollback(stashed=stashed)
```

In `update_submodules()`:
```python
def update_submodules(*, stashed: bool) -> None:
    if not has_submodules():
        return

    with step("Update submodules"):
        result = git("submodule", "update", "--init", "--recursive")
        if not result.success:
            error("Failed to update submodules")
            rollback(stashed=stashed)
```

In `unstash()`:
```python
def unstash(*, stashed: bool) -> None:
    if not stashed:
        return

    with step("Restore stashed changes"):
        result = git("stash", "pop")
        if not result.success:
            warning("Could not cleanly restore stashed changes")
            warning("Your pull succeeded, but stashed changes conflict with pulled code", detail=True)
            warning("Run 'git stash show' to see stashed changes", detail=True)
            warning("Run 'git stash pop' to try again, or 'git stash drop' to discard", detail=True)
            raise typer.Exit(1)
```

In `print_summary()` — this is a display function, not an operation, so use direct `console.print()` with step styling instead of `step()`. The `step()` context manager is for wrapping operations that take time (where the spinner adds value):

```python
def print_summary(head_before: str, remote: str, remote_branch: str) -> None:
    head_after = git("rev-parse", "HEAD")
    if head_before == head_after.stdout:
        console.print("[step.success]✓[/] [step.message]Already up to date[/]")
        return

    log_result = git("log", "--oneline", f"{head_before}..{head_after.stdout}")
    if log_result.success and log_result.stdout:
        commits = log_result.stdout.splitlines()
        console.print(
            f"[step.success]✓[/] [step.message]Pull {len(commits)} new commit(s) "
            f"from {remote}/{remote_branch}[/]"
        )
        for commit in commits:
            console.print(f"  [sub.pipe]│[/] {commit}")
    else:
        console.print("[step.success]✓[/] [step.message]Pull complete[/]")
```

Update imports: replace `info` with `step` and add `console` import.

- [ ] **Step 2: Update unit tests in test_pull.py**

Update assertions that check for old output strings:
- `"2 new commit(s)"` → `"2 new commit(s)"` (still present in step message)
- `"Already up to date"` → `"Already up to date"` (still present)
- `"Failed to pull"` → `"Failed to pull"` (now via `error()`)
- `"Stashing local changes"` → no longer in output, check for `stash` git call instead
- `"Failed to update submodules"` → `"Failed to update submodules"` (now via `error()`)

Review each test's `capsys` assertions and update to match the new output format. Output previously on stdout via `info()` is now on stdout via `console.print()` (from `step()`). Error output is still on stderr via `error()`.

- [ ] **Step 3: Run unit tests**

Run: `cd /Users/natelandau/repos/gx/.worktrees/feat/output-redesign && uv run pytest tests/unit/test_pull.py -v`
Expected: PASS

- [ ] **Step 4: Run integration tests**

Run: `cd /Users/natelandau/repos/gx/.worktrees/feat/output-redesign && uv run pytest tests/integration/test_pull.py -v`
Expected: Update assertions for `"1 new commit(s)"` → `"1 new commit"` if wording changed, and `"Already up to date"` (should still match).

- [ ] **Step 5: Run linters**

Run: `cd /Users/natelandau/repos/gx/.worktrees/feat/output-redesign && uv run ruff check src/gx/commands/pull.py && uv run ruff format src/gx/commands/pull.py tests/unit/test_pull.py tests/integration/test_pull.py`

- [ ] **Step 6: Commit**

```
feat(pull): use step() for spinner-based output

Wrap git operations in step() context managers with active tense
messages. Sub-items show commit lists under pipe markers.
```

---

### Task 5: Refactor push.py to use step()

**Files:**
- Modify: `src/gx/commands/push.py`
- Test: `tests/unit/test_push.py`, `tests/integration/test_push.py`

- [ ] **Step 1: Refactor push.py**

Replace `info()` calls with `step()` and `warning()`. Key changes:

`_warn_dirty_tree()` — already uses `warning()`, just update message if needed.

The main `push()` function: wrap the push git call in a `step()`:
```python
with step(f"Push to {remote}/{remote_branch}"):
    git(*push_args, timeout=120).raise_on_error()
```

`_print_summary()` — this is a display function (not an operation), so use direct `console.print()` with step styling, same pattern as `pull.py`'s `print_summary()`:
```python
def _print_summary(
    remote_ref_before: str | None, remote: str, remote_branch: str, default: str
) -> None:
    if remote_ref_before is not None:
        log_range = f"{remote_ref_before}..HEAD"
    else:
        log_range = f"{default}..HEAD"

    log_result = git("log", "--oneline", log_range)
    if not log_result.success or not log_result.stdout:
        return

    commits = log_result.stdout.splitlines()
    verb = "Would push" if get_dry_run() else "Push"
    console.print(
        f"[step.success]✓[/] [step.message]{verb} {len(commits)} commit(s) "
        f"to {remote}/{remote_branch}[/]"
    )
    for commit in commits:
        console.print(f"  [sub.pipe]│[/] {commit}")
```

Update imports: replace `info` with `step` and add `console` import.

- [ ] **Step 2: Update tests**

Read `tests/unit/test_push.py` and `tests/integration/test_push.py`. Update output assertions for new format.

- [ ] **Step 3: Run tests**

Run: `cd /Users/natelandau/repos/gx/.worktrees/feat/output-redesign && uv run pytest tests/unit/test_push.py tests/integration/test_push.py -v`
Expected: PASS

- [ ] **Step 4: Run linters**

Run: `cd /Users/natelandau/repos/gx/.worktrees/feat/output-redesign && uv run ruff check src/gx/commands/push.py && uv run ruff format src/gx/commands/push.py`

- [ ] **Step 5: Commit**

```
feat(push): use step() for spinner-based output

Wrap push operation and summary in step() context managers with
active tense messages.
```

---

### Task 6: Refactor done.py to use step()

**Files:**
- Modify: `src/gx/commands/done.py`
- Test: `tests/unit/test_done.py`, `tests/integration/test_done.py`

- [ ] **Step 1: Refactor done.py**

Replace `info()` calls. Key changes:

`_checkout_and_pull()` — the inner pull functions (from pull.py) already use `step()` after Task 4. Just need to add a step for the checkout itself:
```python
def _checkout_and_pull(target_branch: str) -> None:
    with step(f"Switch to {target_branch}"):
        result = git("checkout", target_branch)
        if not result.success:
            error(f"Failed to checkout {target_branch}: {result.stderr}")
            raise typer.Exit(1)
    ...
```

`_delete_branch()`:
```python
def _delete_branch(branch: str) -> None:
    with step(f"Delete branch {branch}"):
        result = git("branch", "-D", branch)
        if not result.success:
            warning(f"Could not delete branch {branch}: {result.stderr}")
```

Worktree removal:
```python
with step(f"Remove worktree {worktree.path}"):
    result = remove_worktree(worktree.path)
    if not result.success:
        error(f"Failed to remove worktree {worktree.path}: {result.stderr}")
        raise typer.Exit(1)
```

The final `info(f"Your previous working directory was removed...")` becomes:
```python
warning(f"Your previous working directory was removed. Run: cd {main_path}")
```

Update imports: replace `info` with `step`, add `console` if needed.

- [ ] **Step 2: Update tests**

Read and update `tests/unit/test_done.py` and `tests/integration/test_done.py`.

- [ ] **Step 3: Run tests**

Run: `cd /Users/natelandau/repos/gx/.worktrees/feat/output-redesign && uv run pytest tests/unit/test_done.py tests/integration/test_done.py -v`
Expected: PASS

- [ ] **Step 4: Run linters**

Run: `cd /Users/natelandau/repos/gx/.worktrees/feat/output-redesign && uv run ruff check src/gx/commands/done.py && uv run ruff format src/gx/commands/done.py`

- [ ] **Step 5: Commit**

```
feat(done): use step() for spinner-based output

Wrap checkout, pull, branch deletion, and worktree removal in
step() context managers with active tense messages.
```

---

### Task 7: Refactor feat.py to use step()

**Files:**
- Modify: `src/gx/commands/feat.py`
- Test: `tests/unit/test_feat.py`, `tests/integration/test_feat.py`

- [ ] **Step 1: Refactor feat.py**

Replace `info()` calls. Key changes:

In `_normalize_name()`: the `info(f'Normalized "{original}" to "{name}"')` can become a `debug()` call since it's informational, not a step.

In `_create_branch()`:
```python
def _create_branch(name: str | None) -> None:
    feat_branch, default = _prepare_feat_branch(name)

    with step(f"Create branch {feat_branch} from {default}"):
        result = git("checkout", "-b", feat_branch, default)
        if not result.success:
            if "would be overwritten" in result.stderr:
                error("Checkout failed due to uncommitted changes that conflict with the target branch")
                error("Commit or stash your changes first, then try again", detail=True)
            else:
                error(result.stderr or f"Failed to create branch {feat_branch}")
            raise typer.Exit(1)
```

In `_prepare_feat_branch()`: the `git("fetch", ...)` call becomes a step:
```python
with step(f"Fetch latest {default} from {config.remote_name}"):
    git("fetch", config.remote_name, default).raise_on_error()
```

The `warning(f"Currently on {branch}")` stays as-is.

In `_create_worktree_branch()`:
```python
with step(f"Create worktree at {display_path}") as s:
    create_worktree(worktree_path, feat_branch, start_point=default).raise_on_error()
    s.sub(f"Branch {feat_branch} from {default}")
```

Update imports: replace `info` with `step`, add `console` if needed.

- [ ] **Step 2: Update tests**

Read and update `tests/unit/test_feat.py` and `tests/integration/test_feat.py`.

- [ ] **Step 3: Run tests**

Run: `cd /Users/natelandau/repos/gx/.worktrees/feat/output-redesign && uv run pytest tests/unit/test_feat.py tests/integration/test_feat.py -v`
Expected: PASS

- [ ] **Step 4: Run linters**

Run: `cd /Users/natelandau/repos/gx/.worktrees/feat/output-redesign && uv run ruff check src/gx/commands/feat.py && uv run ruff format src/gx/commands/feat.py`

- [ ] **Step 5: Commit**

```
feat(feat): use step() for spinner-based output

Wrap fetch, branch creation, and worktree creation in step()
context managers with active tense messages.
```

---

### Task 8: Refactor clean.py to use step()

**Files:**
- Modify: `src/gx/commands/clean.py`
- Test: `tests/unit/test_clean.py`, `tests/integration/test_clean.py`

- [ ] **Step 1: Refactor clean.py**

Replace `info()` calls. Key changes:

`_fetch()`:
```python
def _fetch() -> None:
    with step("Fetch with prune"):
        git("fetch", "--prune").raise_on_error()
```

`_display_candidates()` — restructure to use step with sub-items:
```python
def _display_candidates(
    worktree_candidates: list[CleanCandidate],
    branch_candidates: list[CleanCandidate],
    skipped: list[CleanCandidate],
) -> None:
    total = len(worktree_candidates) + len(branch_candidates)
    if total > 0:
        with step(f"Find {total} stale item{'s' if total != 1 else ''}") as s:
            if worktree_candidates:
                s.sub("Worktrees:")
                for c in worktree_candidates:
                    if c.worktree is not None:
                        s.sub(f"  {c.worktree.path}  (branch: {c.branch}, {c.reason})")
            if branch_candidates:
                s.sub("Branches:")
                for c in branch_candidates:
                    s.sub(f"  {c.branch}  ({c.reason})")

    if skipped:
        warning("Skipped (dirty worktree, use --force):")
        for c in skipped:
            if c.worktree is not None:
                warning(f"  {c.worktree.path}  (branch: {c.branch}, {c.reason})", detail=True)
```

`_print_removal_summary()` — this is a display function (not an operation), so use direct `console.print()` with step styling:
```python
def _print_removal_summary(wt_removed: int, br_removed: int) -> None:
    parts: list[str] = []
    if wt_removed:
        parts.append(f"{wt_removed} worktree{'s' if wt_removed != 1 else ''}")
    if br_removed:
        parts.append(f"{br_removed} branch{'es' if br_removed != 1 else ''}")

    if parts:
        verb = "Would remove" if get_dry_run() else "Remove"
        console.print(f"[step.success]✓[/] [step.message]{verb} {' and '.join(parts)}[/]")
```

Update imports: replace `info` with `step`, add `console` if needed.

- [ ] **Step 2: Update tests**

Read and update `tests/unit/test_clean.py` and `tests/integration/test_clean.py`.

- [ ] **Step 3: Run tests**

Run: `cd /Users/natelandau/repos/gx/.worktrees/feat/output-redesign && uv run pytest tests/unit/test_clean.py tests/integration/test_clean.py -v`
Expected: PASS

- [ ] **Step 4: Run linters**

Run: `cd /Users/natelandau/repos/gx/.worktrees/feat/output-redesign && uv run ruff check src/gx/commands/clean.py && uv run ruff format src/gx/commands/clean.py`

- [ ] **Step 5: Commit**

```
feat(clean): use step() for spinner-based output

Wrap fetch, candidate display, and removal summary in step()
context managers with active tense messages.
```

---

### Task 9: Fix remaining info() references and run full test suite

**Files:**
- Modify: any files still importing `info` from `gx.lib.console`
- Modify: `src/gx/lib/git.py` (imports `error` — verify it still works)
- Modify: `src/gx/lib/console.py` docstring

- [ ] **Step 1: Search for remaining info() imports**

Run: `cd /Users/natelandau/repos/gx/.worktrees/feat/output-redesign && grep -r "from gx.lib.console import.*info" src/`

Fix any remaining imports. Also check `CLAUDE.md` for documentation referencing `info()` that needs updating.

- [ ] **Step 2: Update console.py module docstring**

Update the usage docstring at the top of `console.py` to reflect the new API:

```python
"""Global console configuration and leveled print helpers.

Usage in commands:
    from gx.lib.console import console, step, debug, trace, dryrun, warning, error

    with step("Fetch from origin"):          # Spinner → ✓/✗ marker (always shown)
        git("fetch", remote).raise_on_error()
    debug("Resolved remote: origin")         # Shown with -v (cyan, › prefix)
    trace("push origin main")               # Shown with -vv (bright_black, git> prefix)
    dryrun("git push origin main")           # Always shown, bold cyan, [DRY RUN] prefix
    warning("Branch has no upstream")        # Always shown on stderr (yellow, ! prefix)
    error("Failed to push")                  # Always shown on stderr (bold red, ✗ prefix)
    console.print(table)                     # Direct Rich output (tables, panels, etc.)
"""
```

- [ ] **Step 3: Run full test suite**

Run: `cd /Users/natelandau/repos/gx/.worktrees/feat/output-redesign && uv run pytest -x --tb=short`
Expected: All tests PASS.

- [ ] **Step 4: Run full linter suite**

Run: `cd /Users/natelandau/repos/gx/.worktrees/feat/output-redesign && uv run duty lint`
Expected: All checks PASS.

- [ ] **Step 5: Commit**

```
refactor(console): clean up remaining info() references

Update module docstring and fix any remaining imports after
removing the info() helper.
```

---

### Task 10: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update Console Output section**

Update the "Console Output" section in `CLAUDE.md` to reflect the new API. Replace `info()` documentation with `step()` documentation. Document the new helpers, markers, and the `detail` parameter on `warning()`/`error()`.

- [ ] **Step 2: Commit**

```
docs: update CLAUDE.md for new console output API

Replace info() documentation with step() context manager and
updated helper signatures.
```
