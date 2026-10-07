"""Tests for typed ref badge rendering."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal

import pytest

from gx.lib.graph_layout import ASCII, BRANCH_SYMBOLS, UNICODE
from gx.lib.log_badges import (
    ASCII_BADGES,
    NERD_FOLDER,
    UNICODE_BADGES,
    badge_symbols,
    render_badges,
    sync_suffix,
)
from gx.lib.log_context import BranchState, LogContext
from gx.lib.refs import GITHUB_GLYPH, RefDecoration

if TYPE_CHECKING:
    from collections.abc import Mapping

    from rich.text import Text


def _ctx(
    current: str | None = None,
    feat_ahead: int = 0,
    feat_upstream: str = "origin/feat",
    remote_glyphs: Mapping[str, str] | None = None,
    *,
    fix_worktree: Path | None = None,
    fix_ahead: int = 0,
    fix_gone: bool = False,
    fix_stale: Literal["merged", "gone"] | None = None,
    old_stale: Literal["merged", "gone"] | None = None,
) -> LogContext:
    branches = {
        "main": BranchState(
            name="main",
            color="",
            is_current=current == "main",
            is_default=True,
            upstream="origin/main",
        ),
        "feat": BranchState(
            name="feat",
            color="cyan",
            is_current=current == "feat",
            is_default=False,
            upstream=feat_upstream,
            ahead=feat_ahead,
        ),
        "solo": BranchState(name="solo", color="magenta", is_current=False, is_default=False),
        "fix": BranchState(
            name="fix",
            color="green",
            is_current=False,
            is_default=False,
            upstream="origin/fix" if fix_ahead or fix_gone else None,
            ahead=fix_ahead,
            upstream_gone=fix_gone,
            worktree=fix_worktree,
            stale=fix_stale,
        ),
        "old": BranchState(
            name="old", color="magenta", is_current=False, is_default=False, stale=old_stale
        ),
    }
    return LogContext(
        default="main",
        current=current,
        branches=branches,
        owners={},
        head_reachable=frozenset(),
        parents={},
        remotes=frozenset({"origin"}),
        remote_glyphs=remote_glyphs or {},
    )


def _styles(text: Text) -> set[str]:
    return {str(span.style) for span in text.spans if str(span.style)}


def _style_of(text: Text, substring: str) -> str:
    start = text.plain.index(substring)
    for span in text.spans:
        if span.start <= start < span.end:
            return str(span.style)
    return ""


def test_badge_symbols_follow_charset():
    """Badge symbols follow charset."""
    assert badge_symbols(ASCII) is ASCII_BADGES
    assert badge_symbols(UNICODE) is UNICODE_BADGES
    assert badge_symbols(BRANCH_SYMBOLS) is UNICODE_BADGES


def test_unpushed_marker_is_not_a_revision_suffix():
    """The ascii unpushed marker avoids `^`, which git reads as parent-of."""
    assert ASCII_BADGES.unpushed == "+"
    assert UNICODE_BADGES.unpushed == "↑"


def test_current_branch_is_reverse_in_branch_color():
    """Current branch is reverse in branch color."""
    text = render_badges(
        RefDecoration(head="feat", branches=("feat",)), _ctx(current="feat"), UNICODE_BADGES
    )
    assert text.plain == "[feat]"
    assert _styles(text) == {"reverse cyan"}


def test_current_default_branch_is_plain_reverse():
    """Current default branch is plain reverse."""
    text = render_badges(
        RefDecoration(head="main", branches=("main",)), _ctx(current="main"), UNICODE_BADGES
    )
    assert text.plain == "[main]"
    assert _styles(text) == {"reverse"}


def test_other_local_branch_is_bold_in_color():
    """Other local branch is bold in color."""
    text = render_badges(RefDecoration(branches=("solo",)), _ctx(), UNICODE_BADGES)
    assert text.plain == "(solo)"
    assert _styles(text) == {"bold magenta"}


def test_other_default_branch_is_plain_bold():
    """Other default branch is plain bold."""
    text = render_badges(RefDecoration(branches=("main",)), _ctx(), UNICODE_BADGES)
    assert _styles(text) == {"bold"}


def test_unknown_branch_renders_without_color():
    """Unknown branch renders without color."""
    text = render_badges(RefDecoration(branches=("ghost",)), _ctx(), UNICODE_BADGES)
    assert text.plain == "(ghost)"
    assert _styles(text) == {"bold"}


def test_in_sync_pair_collapses():
    """In sync pair collapses."""
    text = render_badges(
        RefDecoration(branches=("main",), remotes=("origin/main",)), _ctx(), UNICODE_BADGES
    )
    assert text.plain == "(main ⇅)"


def test_in_sync_ascii():
    """In sync ascii."""
    text = render_badges(
        RefDecoration(branches=("main",), remotes=("origin/main",)), _ctx(), ASCII_BADGES
    )
    assert text.plain == "(main =)"


@pytest.mark.parametrize(
    ("ahead", "behind", "unicode", "ascii"),
    [(2, 0, "↑2", "^2"), (0, 1, "↓1", "v1"), (2, 1, "↑2↓1", "^2v1"), (0, 0, "", "")],
)
def test_sync_suffix(ahead, behind, unicode, ascii):
    """Sync suffix."""
    branch = BranchState(
        name="f",
        color="",
        is_current=False,
        is_default=False,
        upstream="origin/f",
        ahead=ahead,
        behind=behind,
    )
    assert sync_suffix(branch, UNICODE_BADGES) == unicode
    assert sync_suffix(branch, ASCII_BADGES) == ascii


def test_no_suffix_without_upstream_or_when_gone():
    """No suffix without upstream or when gone."""
    no_upstream = BranchState(name="f", color="", is_current=False, is_default=False, ahead=2)
    gone = BranchState(
        name="f",
        color="",
        is_current=False,
        is_default=False,
        upstream="origin/f",
        ahead=2,
        upstream_gone=True,
    )
    assert sync_suffix(no_upstream, UNICODE_BADGES) == ""
    assert sync_suffix(gone, UNICODE_BADGES) == ""


def test_ahead_branch_keeps_its_remote_badge():
    """Ahead branch keeps its remote badge."""
    ctx = _ctx(feat_ahead=1, current="feat")
    text = render_badges(RefDecoration(head="feat", branches=("feat",)), ctx, UNICODE_BADGES)
    assert text.plain == "[feat ↑1]"
    assert _styles(text) == {"reverse cyan"}
    assert render_badges(RefDecoration(remotes=("origin/feat",)), ctx, UNICODE_BADGES).plain == (
        "origin/feat"
    )


def test_ahead_branch_on_same_row_as_remote_does_not_collapse():
    """Ahead branch on same row as remote does not collapse."""
    ctx = _ctx(feat_ahead=1)
    refs = RefDecoration(branches=("feat",), remotes=("origin/feat",))
    assert render_badges(refs, ctx, UNICODE_BADGES).plain == "(feat ↑1) origin/feat"


def test_other_remote_is_dim_with_glyph_when_available():
    """Other remote is dim with glyph when available."""
    plain = render_badges(RefDecoration(remotes=("origin/x",)), _ctx(), UNICODE_BADGES)
    glyph = render_badges(
        RefDecoration(remotes=("origin/x",)),
        _ctx(remote_glyphs={"origin": GITHUB_GLYPH}),
        UNICODE_BADGES,
    )
    assert plain.plain == "origin/x"
    assert glyph.plain == f"{GITHUB_GLYPH} origin/x"
    assert _styles(plain) == _styles(glyph) == {"dim"}


def test_tag_badge():
    """Tag badge."""
    assert render_badges(RefDecoration(tags=("v1.2",)), _ctx(), UNICODE_BADGES).plain == "◆ v1.2"
    text = render_badges(RefDecoration(tags=("v1.2",)), _ctx(), ASCII_BADGES)
    assert text.plain == "# v1.2"
    assert _styles(text) == {"bold"}


def test_detached_head_badge():
    """Detached head badge."""
    text = render_badges(RefDecoration(detached=True, branches=("main",)), _ctx(), UNICODE_BADGES)
    assert text.plain == "[HEAD] (main)"
    assert _style_of(text, "[HEAD]") == "reverse"


def test_badge_order():
    """Badge order."""
    refs = RefDecoration(
        head="feat",
        branches=("solo", "feat"),
        tags=("v1",),
        remotes=("origin/x",),
        others=("refs/pull/1/head",),
    )
    text = render_badges(refs, _ctx(current="feat"), UNICODE_BADGES)
    assert text.plain == "[feat] (solo) ◆ v1 origin/x refs/pull/1/head"
    assert _style_of(text, "refs/pull") == "dim"


def test_local_upstream_does_not_collapse():
    """Local upstream does not collapse."""
    ctx = _ctx(feat_upstream="main")
    refs = RefDecoration(branches=("main", "feat"))
    assert render_badges(refs, ctx, UNICODE_BADGES).plain == "(main) (feat)"


def test_empty_refs():
    """Empty refs."""
    assert render_badges(RefDecoration(), _ctx(), UNICODE_BADGES).plain == ""


def test_gone_upstream_on_same_row_does_not_collapse():
    """A gone upstream keeps its remote badge, with no suffix and no in-sync mark."""
    ctx = _ctx()
    feat = BranchState(
        name="feat",
        color="cyan",
        is_current=False,
        is_default=False,
        upstream="origin/feat",
        upstream_gone=True,
    )
    ctx = LogContext(
        default=ctx.default,
        current=ctx.current,
        branches={**ctx.branches, "feat": feat},
        owners={},
        head_reachable=frozenset(),
        parents={},
        remotes=ctx.remotes,
    )
    refs = RefDecoration(branches=("feat",), remotes=("origin/feat",))
    assert render_badges(refs, ctx, UNICODE_BADGES).plain == "(feat) origin/feat"


def test_in_sync_branch_without_its_remote_on_the_row_has_no_suffix():
    """An in-sync non-current branch shows a bare name when its remote is elsewhere."""
    text = render_badges(RefDecoration(branches=("feat",)), _ctx(), UNICODE_BADGES)
    assert text.plain == "(feat)"


def test_remote_name_with_slash_finds_its_glyph():
    """The glyph lookup matches the configured remote, not the text before the first slash."""
    ctx = _ctx(remote_glyphs={"team/fork": GITHUB_GLYPH, "team": "X"})
    ctx = LogContext(
        default=ctx.default,
        current=ctx.current,
        branches=ctx.branches,
        owners={},
        head_reachable=frozenset(),
        parents={},
        remotes=frozenset({"team", "team/fork"}),
        remote_glyphs=ctx.remote_glyphs,
    )
    text = render_badges(RefDecoration(remotes=("team/fork/main",)), ctx, UNICODE_BADGES)
    assert text.plain == f"{GITHUB_GLYPH} team/fork/main"


def test_worktree_suffix():
    """A worktree adds its basename after the name, with a charset-specific prefix."""
    ctx = _ctx(fix_worktree=Path("/repo/.worktrees/gx-fix-log"))
    refs = RefDecoration(branches=("fix",))
    assert render_badges(refs, ctx, UNICODE_BADGES).plain == "(fix ⌂ gx-fix-log)"
    assert render_badges(refs, ctx, ASCII_BADGES).plain == "(fix wt:gx-fix-log)"
    nerd = badge_symbols(UNICODE, nerd_font=True)
    assert render_badges(refs, ctx, nerd).plain == f"(fix {NERD_FOLDER} gx-fix-log)"


def test_nerd_font_ignored_for_ascii():
    """The ASCII charset never uses the nerd font glyph."""
    assert badge_symbols(ASCII, nerd_font=True) is ASCII_BADGES


def test_stale_suffix_is_dim():
    """The stale suffix is its own dim span while the rest keeps the badge style."""
    text = render_badges(RefDecoration(branches=("old",)), _ctx(old_stale="merged"), UNICODE_BADGES)
    assert text.plain == "(old merged)"
    assert _style_of(text, "merged") == "dim"
    assert _style_of(text, "(old") == "bold magenta"


def test_suffix_order():
    """Suffixes appear as sync, worktree, then stale."""
    refs = RefDecoration(branches=("fix",))
    wt = Path("/w/gx-fix")
    gone = _ctx(fix_worktree=wt, fix_gone=True, fix_stale="gone")
    assert render_badges(refs, gone, UNICODE_BADGES).plain == "(fix ⌂ gx-fix gone)"
    live = _ctx(fix_worktree=wt, fix_ahead=1)
    assert render_badges(refs, live, UNICODE_BADGES).plain == "(fix ↑1 ⌂ gx-fix)"
    merged = _ctx(fix_worktree=wt, fix_ahead=1, fix_stale="merged")
    assert render_badges(refs, merged, UNICODE_BADGES).plain == "(fix ↑1 ⌂ gx-fix merged)"
