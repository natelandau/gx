"""Branch ownership, reachability, and colors for the log graph."""

from __future__ import annotations

import zlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nclutils import pp

from gx.lib.git import git

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from gx.lib.graph_layout import Pipe

PALETTE: tuple[str, ...] = (
    "cyan",
    "magenta",
    "bright_blue",
    "red",
    "bright_green",
    "bright_yellow",
)
DIM = "dim"

type Parents = Mapping[str, tuple[str, ...]]


def dimmed(style: str) -> str:
    """Add `dim` to a Rich style without doubling it.

    Args:
        style: The style to dim.

    Returns:
        The style with `dim` included once.
    """
    return style if DIM in style.split() else f"{style} {DIM}".strip()


def reachable(
    tips: Iterable[str], parents: Parents, *, stop: frozenset[str] = frozenset()
) -> frozenset[str]:
    """Collect every commit reachable from the tips through in-window parents.

    Args:
        tips: Commits to start from.
        parents: Map of sha to parent shas, covering window commits only.
        stop: Commits that are neither returned nor expanded.

    Returns:
        The reachable commits, including the tips that are in the window.
    """
    seen: set[str] = set()
    stack = [tip for tip in tips if tip in parents and tip not in stop]
    while stack:
        sha = stack.pop()
        if sha in seen:
            continue
        seen.add(sha)
        stack.extend(p for p in parents[sha] if p in parents and p not in stop and p not in seen)
    return frozenset(seen)


def assign_owners(
    parents: Parents,
    *,
    default_tip: str | None,
    branch_tips: Mapping[str, str],
    current: str | None,
    default: str | None,
) -> dict[str, str]:
    """Decide which branch owns each commit in the window.

    The default branch owns everything it reaches. Every other branch competes for
    the commits only it reaches, and the branch with the smallest such set wins a
    shared commit, so stacked branches keep their own commits.

    Args:
        parents: Map of sha to parent shas, covering window commits only.
        default_tip: Tip of the default branch, if any.
        branch_tips: Map of branch name to tip sha.
        current: Name of the checked-out branch, preferred on ties.
        default: Name of the default branch.

    Returns:
        Map of sha to owning branch name. Unreached commits are absent.
    """
    base: frozenset[str] = frozenset()
    owners: dict[str, str] = {}
    if default_tip is not None and default is not None:
        base = reachable([default_tip], parents)
        owners = dict.fromkeys(base, default)

    exclusive = {
        name: reachable([tip], parents, stop=base)
        for name, tip in branch_tips.items()
        if name != default
    }
    best: dict[str, tuple[int, bool, str]] = {}
    for name, commits in exclusive.items():
        rank = (len(commits), name != current, name)
        for sha in commits:
            if sha not in best or rank < best[sha]:
                best[sha] = rank
    owners.update({sha: rank[2] for sha, rank in best.items()})
    return owners


def assign_colors(names: Iterable[str]) -> dict[str, str]:
    """Give each branch a stable palette color.

    A name starts at the slot its CRC32 selects, in sorted order, and probes forward
    to the next free slot. When every slot is taken, the starting slot is reused.

    Args:
        names: Branch names to color.

    Returns:
        Map of branch name to palette color.
    """
    size = len(PALETTE)
    taken: set[int] = set()
    colors: dict[str, str] = {}
    for name in sorted(set(names)):
        start = zlib.crc32(name.encode()) % size
        slot = next(
            ((start + step) % size for step in range(size) if (start + step) % size not in taken),
            start,
        )
        taken.add(slot)
        colors[name] = PALETTE[slot]
    return colors


@dataclass(frozen=True)
class BranchState:
    """A visible branch and how it is drawn."""

    name: str
    color: str
    is_current: bool
    is_default: bool


@dataclass(frozen=True)
class LogContext:
    """Everything the graph renderer needs to style commits and pipes by branch."""

    default: str | None
    current: str | None
    branches: Mapping[str, BranchState]
    owners: Mapping[str, str]
    head_reachable: frozenset[str]
    parents: Parents

    def owner(self, sha: str) -> BranchState | None:
        """Return the branch that owns a commit, if it is visible.

        Args:
            sha: Commit to look up.

        Returns:
            The owning branch state, or None when unowned or hidden.
        """
        name = self.owners.get(sha)
        return self.branches.get(name) if name is not None else None

    def _style(self, owner: BranchState | None, sha: str) -> str:
        """Return the owner's color, or dim for no owner, dimmed when HEAD misses the commit."""
        base = owner.color if owner is not None else DIM
        return base if sha in self.head_reachable else dimmed(base)

    def commit_style(self, sha: str) -> str:
        """Return the Rich style for a commit.

        Args:
            sha: Commit to style.

        Returns:
            The owner's color, dimmed when HEAD does not reach the commit.
        """
        return self._style(self.owner(sha), sha)

    def sha_style(self, sha: str) -> str:
        """Return the Rich style for a commit's abbreviated SHA.

        Args:
            sha: Commit to style.

        Returns:
            The owner's color, or an empty style for default-branch and unowned commits.
        """
        owner = self.owner(sha)
        return owner.color if owner is not None else ""

    def pipe_style(self, pipe: Pipe) -> str:
        """Return the Rich style for a pipe.

        A first-parent pipe continues the child's branch. Any other pipe belongs to
        the branch it merges in.

        Args:
            pipe: Pipe to style.

        Returns:
            The owner's color, dimmed when HEAD does not reach the child commit.
        """
        child_parents = self.parents.get(pipe.from_sha, ())
        is_first_parent = bool(child_parents) and pipe.to_sha == child_parents[0]
        owner = self.owner(pipe.from_sha if is_first_parent else pipe.to_sha)
        return self._style(owner, pipe.from_sha)


@dataclass(frozen=True)
class BranchRefs:
    """Local branch tips and where HEAD points."""

    tips: Mapping[str, str]
    current: str | None
    head_sha: str | None


def read_branch_refs() -> BranchRefs:
    """Read local branch tips, the checked-out branch, and the HEAD commit.

    Returns:
        The branch tips by name, the current branch name (None when detached),
        and the HEAD sha (None when HEAD is unborn).
    """
    # lstrip=2 drops `refs/heads/`; `:short` would yield `heads/x` when a tag shares the name.
    result = git(
        "for-each-ref", "--format=%(HEAD)%1f%(refname:lstrip=2)%1f%(objectname)", "refs/heads"
    )
    if not result.ok:
        pp.debug(f"git for-each-ref failed, branch colors unavailable: {result.stderr}")
    tips: dict[str, str] = {}
    current: str | None = None
    head_sha: str | None = None
    for line in result.stdout.splitlines() if result.ok else []:
        marker, name, sha = line.split("\x1f")
        tips[name] = sha
        if marker == "*":
            current, head_sha = name, sha
    if current is None:
        head = git("rev-parse", "--verify", "--quiet", "HEAD")
        head_sha = head.stdout if head.ok and head.stdout else None
    return BranchRefs(tips=tips, current=current, head_sha=head_sha)


def build_log_context(
    parents: Parents,
    *,
    default: str | None,
    default_tip: str | None,
    refs: BranchRefs | None = None,
) -> LogContext:
    """Assemble the branch context that colors the log graph.

    Only branches with a presence in the window get a state and a palette slot, so
    branches outside the window cannot shift the colors of visible ones.

    Args:
        parents: Map of sha to parent shas, covering window commits only.
        default: Name of the default branch, which may be a remote-tracking ref.
        default_tip: Tip sha of the default branch.
        refs: Branch tips and HEAD already read from git, or None to read them.

    Returns:
        The context for styling commits and pipes.
    """
    refs = refs if refs is not None else read_branch_refs()
    tips, current, head_sha = refs.tips, refs.current, refs.head_sha
    head_reachable = reachable([head_sha] if head_sha else [], parents)
    owners = assign_owners(
        parents, default_tip=default_tip, branch_tips=tips, current=current, default=default
    )

    owning = set(owners.values())
    visible = sorted(
        name for name, tip in tips.items() if name != default and (name in owning or tip in parents)
    )
    colors = assign_colors(visible)

    branches: dict[str, BranchState] = {}
    if default is not None and default_tip in parents:
        branches[default] = BranchState(
            name=default, color="", is_current=default == current, is_default=True
        )
    branches.update(
        {
            name: BranchState(
                name=name, color=colors[name], is_current=name == current, is_default=False
            )
            for name in visible
        }
    )
    return LogContext(
        default=default,
        current=current,
        branches=branches,
        owners=owners,
        head_reachable=head_reachable,
        parents=parents,
    )
