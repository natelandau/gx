"""Branch ownership, reachability, and colors for the log graph."""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from nclutils import pp

from gx.lib.branch import branch_file_statuses
from gx.lib.config import config
from gx.lib.git import git
from gx.lib.refs import read_remotes, remote_glyph
from gx.lib.worktree import parse_worktree_porcelain

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
REMOTE_REF_PREFIX = "refs/remotes/"

type Parents = Mapping[str, tuple[str, ...]]
type FileCounts = tuple[int, int, int, int]


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
    upstream: str | None = None
    ahead: int = 0
    behind: int = 0
    upstream_gone: bool = False
    has_remote_upstream: bool = False
    tip: str | None = None
    worktree: Path | None = None
    dirty: FileCounts | None = None
    stale: Literal["merged", "gone"] | None = None


@dataclass(frozen=True)
class LogContext:
    """Everything the graph renderer needs to style commits and pipes by branch."""

    default: str | None
    current: str | None
    branches: Mapping[str, BranchState]
    owners: Mapping[str, str]
    head_reachable: frozenset[str]
    parents: Parents
    unpushed: frozenset[str] = frozenset()
    remotes: frozenset[str] = frozenset()
    remote_glyphs: Mapping[str, str] = field(default_factory=dict)
    stale: frozenset[str] = frozenset()

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
class Tracking:
    """A local branch's upstream and how far the two have drifted."""

    upstream: str
    upstream_ref: str
    ahead: int
    behind: int
    gone: bool


@dataclass(frozen=True)
class BranchRefs:
    """Local branch tips, their upstreams, and where HEAD points."""

    tips: Mapping[str, str]
    current: str | None
    head_sha: str | None
    tracking: Mapping[str, Tracking] = field(default_factory=dict)


def parse_track(track: str) -> tuple[int, int, bool]:
    """Read git's `upstream:track` text into counts.

    Args:
        track: The field value, such as `[ahead 2, behind 1]`, `[gone]`, or empty.

    Returns:
        The ahead count, the behind count, and whether the upstream is gone.
    """
    ahead = re.search(r"ahead (\d+)", track)
    behind = re.search(r"behind (\d+)", track)
    return (
        int(ahead.group(1)) if ahead else 0,
        int(behind.group(1)) if behind else 0,
        track == "[gone]",
    )


def read_branch_refs() -> BranchRefs:
    """Read local branch tips, upstreams, the checked-out branch, and the HEAD commit.

    Returns:
        The branch tips by name, the current branch name (None when detached),
        the HEAD sha (None when HEAD is unborn), and tracking for branches with an upstream.
    """
    # lstrip=2 drops `refs/heads/`; `:short` would yield `heads/x` when a tag shares the name.
    result = git(
        "for-each-ref",
        "--format=%(HEAD)%1f%(refname:lstrip=2)%1f%(objectname)"
        "%1f%(upstream)%1f%(upstream:lstrip=2)%1f%(upstream:track)",
        "refs/heads",
    )
    if not result.ok:
        pp.debug(f"git for-each-ref failed, branch colors unavailable: {result.stderr}")
    tips: dict[str, str] = {}
    tracking: dict[str, Tracking] = {}
    current: str | None = None
    head_sha: str | None = None
    for line in result.stdout.splitlines() if result.ok else []:
        marker, name, sha, upstream_ref, upstream, track = line.split("\x1f")
        tips[name] = sha
        if marker == "*":
            current, head_sha = name, sha
        if upstream_ref:
            ahead, behind, gone = parse_track(track)
            tracking[name] = Tracking(
                upstream=upstream,
                upstream_ref=upstream_ref,
                ahead=ahead,
                behind=behind,
                gone=gone,
            )
    if current is None:
        head = git("rev-parse", "--verify", "--quiet", "HEAD")
        head_sha = head.stdout if head.ok and head.stdout else None
    return BranchRefs(tips=tips, current=current, head_sha=head_sha, tracking=tracking)


def read_unpushed(
    tracking: Mapping[str, Tracking], tips: Mapping[str, str], window: Iterable[str]
) -> frozenset[str]:
    """Find window commits that exist on a branch but not on its remote upstream.

    Ask git rather than infer from the window, because an upstream tip can lie
    outside a limited window. Branches tracking another local branch are skipped,
    since their commits are not unpushed to any remote.

    Args:
        tracking: Upstream state by branch name.
        tips: Tip sha by branch name.
        window: Commits shown in the graph.

    Returns:
        The unpushed commits that are in the window.
    """
    shown = set(window)
    unpushed: set[str] = set()
    for name, track in tracking.items():
        if track.ahead <= 0 or not track.upstream_ref.startswith(REMOTE_REF_PREFIX):
            continue
        # The window is topo-ordered, so a tip outside it cuts off all its ancestors too.
        if tips.get(name) not in shown:
            continue
        result = git("rev-list", f"{track.upstream_ref}..refs/heads/{name}")
        if not result.ok:
            pp.debug(
                f"git rev-list failed for {name}, unpushed commits unavailable: {result.stderr}"
            )
            continue
        unpushed.update(sha for sha in result.stdout.split() if sha in shown)
    return frozenset(unpushed)


@dataclass(frozen=True)
class Checkout:
    """A branch checked out in a worktree and its uncommitted file counts."""

    path: Path
    dirty: FileCounts | None
    is_main: bool = False
    is_locked: bool = False

    @property
    def cleanable(self) -> bool:
        """Whether `gx clean` may remove this worktree.

        Clean never removes the main or a locked worktree, nor a dirty one without --force.
        """
        return not (self.is_main or self.is_locked or self.dirty is not None)


def read_checkouts(current: str | None) -> dict[str, Checkout]:
    """Map each checked-out branch to its worktree and uncommitted changes.

    Args:
        current: Name of the branch checked out in the working directory.

    Returns:
        Checkouts by branch name. Bare, detached, and prunable entries are left out.
        A locked worktree whose folder is missing stays in, since it still holds its branch.
    """
    result = git("worktree", "list", "--porcelain")
    if not result.ok:
        pp.debug(f"git worktree list failed, worktree marks unavailable: {result.stderr}")
        return {}
    checkouts: dict[str, Checkout] = {}
    for index, raw in enumerate(parse_worktree_porcelain(result.stdout)):
        name = raw.get("branch")
        if name is None or {"bare", "detached", "prunable"} & raw.keys():
            continue
        path = Path(raw["path"])
        counts = branch_file_statuses(is_current=name == current, wt_path=path)
        checkouts[name] = Checkout(
            path=path,
            dirty=counts if any(counts) else None,
            is_main=index == 0,
            is_locked="locked" in raw,
        )
    return checkouts


def read_merged(default: str | None) -> frozenset[str]:
    """List the local branches merged into the default branch.

    Args:
        default: Name of the default branch, or None when there is none.

    Returns:
        The merged branch names, empty when there is no default or git fails.
    """
    if default is None:
        return frozenset()
    result = git("branch", "--merged", default, "--format=%(refname:lstrip=2)")
    if not result.ok:
        pp.debug(f"git branch --merged failed, merged state unavailable: {result.stderr}")
        return frozenset()
    return frozenset(result.stdout.split())


def build_log_context(
    parents: Parents,
    *,
    default: str | None,
    default_tip: str | None,
    refs: BranchRefs | None = None,
    remotes: Mapping[str, str] | None = None,
    checkouts: Mapping[str, Checkout] | None = None,
    merged: frozenset[str] | None = None,
) -> LogContext:
    """Assemble the branch context that colors the log graph.

    Branches with a presence in the window, and checked-out branches with uncommitted
    changes, get a state and a palette slot. Other branches outside the window get
    none, so they cannot shift the colors of visible ones.

    Args:
        parents: Map of sha to parent shas, covering window commits only.
        default: Name of the default branch, which may be a remote-tracking ref.
        default_tip: Tip sha of the default branch.
        refs: Branch tips and HEAD already read from git, or None to read them.
        remotes: Map of remote name to fetch URL, or None to read them.
        checkouts: Worktree checkouts by branch, or None to read them.
        merged: Local branches merged into the default, or None to read them.

    Returns:
        The context for styling commits and pipes.
    """
    refs = refs if refs is not None else read_branch_refs()
    remotes = remotes if remotes is not None else read_remotes()
    tips, current, head_sha = refs.tips, refs.current, refs.head_sha
    checkouts = checkouts if checkouts is not None else read_checkouts(current)
    merged = merged if merged is not None else read_merged(default)
    head_reachable = reachable([head_sha] if head_sha else [], parents)
    owners = assign_owners(
        parents, default_tip=default_tip, branch_tips=tips, current=current, default=default
    )

    owning = set(owners.values())
    visible = sorted(
        name
        for name, tip in tips.items()
        if name != default
        and (
            name in owning
            or tip in parents
            or (name in checkouts and checkouts[name].dirty is not None)
        )
    )
    colors = assign_colors(visible)

    def stale_kind(name: str) -> Literal["merged", "gone"] | None:
        track = refs.tracking.get(name)
        if name in (default, current) or name in config.protected_branches:
            return None
        if track is not None and track.gone:
            return "gone"
        return "merged" if name in merged and track is not None else None

    stale_by_name = {name: kind for name in tips if (kind := stale_kind(name)) is not None}

    def state(name: str, color: str, *, is_default: bool) -> BranchState:
        track = refs.tracking.get(name)
        checkout = checkouts.get(name)
        return BranchState(
            name=name,
            color=color,
            is_current=name == current,
            is_default=is_default,
            upstream=track.upstream if track else None,
            ahead=track.ahead if track else 0,
            behind=track.behind if track else 0,
            upstream_gone=track.gone if track else False,
            has_remote_upstream=bool(track and track.upstream_ref.startswith(REMOTE_REF_PREFIX)),
            tip=tips.get(name),
            worktree=checkout.path if checkout and name != current else None,
            dirty=checkout.dirty if checkout else None,
            stale=stale_by_name.get(name),
        )

    branches: dict[str, BranchState] = {}
    if default is not None and default_tip in parents:
        branches[default] = state(default, "", is_default=True)
    branches.update({name: state(name, colors[name], is_default=False) for name in visible})
    return LogContext(
        default=default,
        current=current,
        branches=branches,
        owners=owners,
        head_reachable=head_reachable,
        parents=parents,
        unpushed=read_unpushed(refs.tracking, tips, parents),
        remotes=frozenset(remotes),
        remote_glyphs=(
            {name: remote_glyph(url) for name, url in remotes.items()} if config.nerd_font else {}
        ),
        stale=frozenset(
            name for name in stale_by_name if name not in checkouts or checkouts[name].cleanable
        ),
    )
