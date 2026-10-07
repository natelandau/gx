"""Typed ref badges and sync suffixes for the log graph.

Usage:
    from gx.lib.log_badges import badge_symbols, render_badges

    text = render_badges(parse_refs(raw, context.remotes), context, badge_symbols(charset))
"""

from __future__ import annotations

from dataclasses import dataclass
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


UNICODE_BADGES = BadgeSymbols(tag="◆", ahead="↑", behind="↓", in_sync="⇅", unpushed="↑")
ASCII_BADGES = BadgeSymbols(tag="#", ahead="^", behind="v", in_sync="=", unpushed="+")


def badge_symbols(charset: Charset) -> BadgeSymbols:
    """Pick the badge glyphs matching a graph charset.

    Args:
        charset: The charset the graph is drawn with.

    Returns:
        ASCII symbols for the ASCII charset, unicode symbols otherwise.
    """
    return ASCII_BADGES if charset is ASCII else UNICODE_BADGES


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
        state = context.branches.get(name)
        suffix = ""
        if state is not None:
            suffix = symbols.in_sync if state.upstream in collapsed else sync_suffix(state, symbols)
        label = f"{name} {suffix}" if suffix else name
        color = state.color if state is not None else ""
        return Text(f"{open_}{label}{close}", style=_style(*style, color))

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
