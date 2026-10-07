"""Typed ref badges and sync suffixes for the log graph.

Usage:
    from gx.lib.log_badges import badge_symbols, render_badges

    text = render_badges(parse_refs(raw, context.remotes), context, badge_symbols(charset))
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from rich.text import Text

from gx.lib.graph_layout import ASCII
from gx.lib.refs import remote_of

if TYPE_CHECKING:
    from gx.lib.graph_layout import Charset
    from gx.lib.log_context import BranchState, LogContext
    from gx.lib.refs import RefDecoration


@dataclass(frozen=True)
class BadgeSymbols:
    """Glyphs used by badges for one charset."""

    tag: str
    ahead: str
    behind: str
    in_sync: str
    unpushed: str
    worktree: str
    dirty: str


NERD_FOLDER = "\uf07b"

UNICODE_BADGES = BadgeSymbols(
    tag="◆", ahead="↑", behind="↓", in_sync="⇅", unpushed="↑", worktree="⌂ ", dirty="◌"
)
ASCII_BADGES = BadgeSymbols(
    tag="#", ahead="^", behind="v", in_sync="=", unpushed="+", worktree="wt:", dirty="o"
)


def badge_symbols(charset: Charset, *, nerd_font: bool = False) -> BadgeSymbols:
    """Pick the badge glyphs matching a graph charset.

    Args:
        charset: The charset the graph is drawn with.
        nerd_font: Use the nerd font folder glyph for worktrees; ignored for ASCII.

    Returns:
        ASCII symbols for the ASCII charset, unicode symbols otherwise.
    """
    if charset is ASCII:
        return ASCII_BADGES
    if nerd_font:
        return replace(UNICODE_BADGES, worktree=f"{NERD_FOLDER} ")
    return UNICODE_BADGES


def sync_suffix(branch: BranchState, symbols: BadgeSymbols) -> str:
    """Describe how a branch differs from its upstream.

    Args:
        branch: The local branch.
        symbols: Glyphs for the current charset.

    Returns:
        `↑n`, `↓m`, or `↑n↓m`; empty with no upstream, a gone upstream, or no difference.
    """
    if not _has_live_upstream(branch):
        return ""
    ahead = f"{symbols.ahead}{branch.ahead}" if branch.ahead else ""
    behind = f"{symbols.behind}{branch.behind}" if branch.behind else ""
    return ahead + behind


def _style(*parts: str) -> str:
    return " ".join(part for part in parts if part)


def _has_live_upstream(branch: BranchState) -> bool:
    return branch.upstream is not None and not branch.upstream_gone


def _is_in_sync(branch: BranchState) -> bool:
    return _has_live_upstream(branch) and not (branch.ahead or branch.behind)


def _local_badge(
    name: str,
    state: BranchState | None,
    collapsed: set[str],
    symbols: BadgeSymbols,
    brackets: tuple[str, str],
    style: tuple[str, ...],
) -> Text:
    label = name
    stale = ""
    color = ""
    if state is not None:
        color = state.color
        sync = symbols.in_sync if state.upstream in collapsed else sync_suffix(state, symbols)
        if sync:
            label += f" {sync}"
        if state.worktree is not None:
            label += f" {symbols.worktree}{state.worktree.name}"
        stale = state.stale or ""
    badge_style = _style(*style, color)
    # Per-segment styles, not a base style, so join() cannot paint over the dim suffix.
    text = Text()
    text.append(f"{brackets[0]}{label}", style=badge_style)
    if stale:
        text.append(f" {stale}", style="dim")
    text.append(brackets[1], style=badge_style)
    return text


def render_badges(refs: RefDecoration, context: LogContext, symbols: BadgeSymbols) -> Text:
    """Render the refs decorating a commit as styled badges.

    Order is the HEAD badge, other local branches, tags, remote branches, then other refs.
    A remote ref is omitted when a local branch on the same row tracks it and is in sync;
    that local badge gets the in-sync mark instead.

    Args:
        refs: Typed refs for one commit.
        context: Branch states, remotes, and remote glyphs.
        symbols: Glyphs for the current charset.

    Returns:
        The badges separated by single spaces; empty when there is nothing to show.
    """
    collapsed: set[str] = set()
    for name in refs.branches:
        state = context.branches.get(name)
        if state is not None and state.upstream in refs.remotes and _is_in_sync(state):
            collapsed.add(str(state.upstream))

    def local(name: str, open_: str, close: str, *style: str) -> Text:
        return _local_badge(
            name, context.branches.get(name), collapsed, symbols, (open_, close), style
        )

    badges: list[Text] = []
    if refs.head is not None:
        badges.append(local(refs.head, "[", "]", "reverse"))
    elif refs.detached:
        badges.append(Text("[HEAD]", style="reverse"))

    badges.extend(local(name, "(", ")", "bold") for name in refs.branches if name != refs.head)
    badges.extend(Text(f"{symbols.tag} {tag}", style="bold") for tag in refs.tags)

    for remote in refs.remotes:
        if remote in collapsed:
            continue
        name = remote_of(remote, context.remotes)
        glyph = context.remote_glyphs.get(name) if name is not None else None
        badges.append(Text(f"{glyph} {remote}" if glyph else remote, style="dim"))

    badges.extend(Text(other, style="dim") for other in refs.others)

    return Text(" ").join(badges)
