"""Ref decoration parsing and remote helpers shared by the log renderers.

Usage:
    from gx.lib.refs import parse_refs, read_remotes

    remotes = read_remotes()
    refs = parse_refs("HEAD -> main, origin/main", frozenset(remotes))
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from gx.lib.config import config
from gx.lib.git import git
from gx.lib.github import is_github_remote

if TYPE_CHECKING:
    from collections.abc import Iterable

# Plain-ASCII fallback used when nerd fonts are disabled (config.nerd_font = False),
# so terminals without a Nerd Font show a readable symbol instead of tofu. One
# symbol covers every host since the remote name follows it in labeled badges.
REMOTE_FALLBACK = "@"

# Host-aware Nerd Font glyphs for remote badges.
GITHUB_GLYPH = ""
GITLAB_GLYPH = ""
GIT_GLYPH = ""


@dataclass(frozen=True)
class RefDecoration:
    """The refs decorating one commit, grouped by kind.

    Attributes:
        head: Branch named by `HEAD -> x`, or None.
        detached: True when HEAD points at the commit without a branch.
        branches: Local branches in git's order, including `head`.
        tags: Tag names without the `tag: ` prefix.
        remotes: Remote-tracking refs such as `origin/main`, excluding `<remote>/HEAD`.
        others: Full ref names outside heads, remotes, and tags, such as `refs/pull/1/head`.
    """

    head: str | None = None
    detached: bool = False
    branches: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    remotes: tuple[str, ...] = ()
    others: tuple[str, ...] = ()


def remote_of(ref: str, remotes: Iterable[str]) -> str | None:
    """Find the configured remote that qualifies a ref.

    Match the longest remote name followed by a slash, because remote names may
    contain slashes themselves and a local branch like `feat/x` must not match.

    Args:
        ref: A ref name such as `origin/main`.
        remotes: Names of the configured remotes.

    Returns:
        The remote name, or None when no configured remote qualifies the ref.
    """
    matches = [name for name in remotes if name and ref.startswith(f"{name}/")]
    return max(matches, key=len, default=None)


def parse_refs(raw: str, remotes: frozenset[str]) -> RefDecoration:
    """Parse a raw `%D` decoration string into typed refs.

    A ref is remote when a configured remote qualifies it (see `remote_of`),
    so a local branch like `feat/x` is never mistaken for one.

    Args:
        raw: The raw `%D` output for a single commit.
        remotes: Names of the configured remotes.

    Returns:
        The refs grouped by kind.
    """
    if not raw.strip():
        return RefDecoration()

    head: str | None = None
    detached = False
    branches: list[str] = []
    tags: list[str] = []
    remote_refs: list[str] = []
    others: list[str] = []

    for item in raw.split(", "):
        ref = item.strip()
        if ref.startswith("HEAD -> "):
            head = ref.removeprefix("HEAD -> ")
            branches.append(head)
        elif ref == "HEAD":
            detached = True
        elif ref.startswith("tag: "):
            tags.append(ref.removeprefix("tag: "))
        elif ref.startswith("refs/"):
            others.append(ref)
        else:
            remote = remote_of(ref, remotes)
            if remote is not None:
                if ref != f"{remote}/HEAD":  # symbolic alias of the default, not a branch
                    remote_refs.append(ref)
            else:
                branches.append(ref)

    return RefDecoration(
        head=head,
        detached=detached,
        branches=tuple(branches),
        tags=tuple(tags),
        remotes=tuple(remote_refs),
        others=tuple(others),
    )


def read_remotes() -> dict[str, str]:
    """Map each configured remote name to its fetch URL.

    Returns:
        A map such as {"origin": "git@github.com:a/b.git"}, empty when git fails
        or no remotes exist.
    """
    result = git("remote", "-v")
    if not result.ok or not result.stdout:
        return {}

    # Lines are "<name>\t<url> (fetch|push)"; keep the first URL per remote.
    remotes: dict[str, str] = {}
    for line in result.stdout.splitlines():
        name, _, rest = line.partition("\t")
        url = rest.split(maxsplit=1)[0] if rest else ""
        if name and url:
            remotes.setdefault(name, url)
    return remotes


def remote_glyph(url: str) -> str:
    """Pick a host-aware badge token for a remote URL.

    Lets a remote badge echo where the code actually lives (GitHub, GitLab, or
    a generic git host) instead of a one-size-fits-all icon. When nerd fonts
    are disabled via config, every host collapses to a single ASCII symbol so
    the badge stays readable without a Nerd Font.

    Args:
        url: The remote URL to classify.
    """
    if not config.nerd_font:
        return REMOTE_FALLBACK
    if is_github_remote(url):
        return GITHUB_GLYPH
    if "gitlab" in url:
        return GITLAB_GLYPH
    return GIT_GLYPH
