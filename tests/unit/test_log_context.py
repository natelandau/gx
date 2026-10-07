"""Tests for branch ownership, reachability, and color assignment in the log graph."""

from __future__ import annotations

import itertools
import zlib
from typing import TYPE_CHECKING

import pytest
from nclutils.sh import CompletedCommand

from gx.lib.config import GxConfig
from gx.lib.git import git
from gx.lib.graph_layout import Pipe, PipeKind
from gx.lib.log_context import (
    PALETTE,
    BranchState,
    LogContext,
    Tracking,
    assign_colors,
    assign_owners,
    build_log_context,
    parse_track,
    reachable,
    read_branch_refs,
    read_unpushed,
)
from gx.lib.refs import GIT_GLYPH
from tests.conftest import (
    _run_git,
    checkout_tmp_branch,
    create_tmp_branch,
    create_tmp_commit,
    delete_tmp_remote_branch,
    detach_tmp_head,
    push_tmp_branch,
)

if TYPE_CHECKING:
    from pathlib import Path


def _slot(name: str) -> int:
    return zlib.crc32(name.encode()) % len(PALETTE)


def _context(
    parents: dict[str, tuple[str, ...]],
    owners: dict[str, str],
    head_reachable: frozenset[str],
) -> LogContext:
    return LogContext(
        default="main",
        current="feat",
        branches={
            "main": BranchState(name="main", color="", is_current=False, is_default=True),
            "feat": BranchState(name="feat", color="cyan", is_current=True, is_default=False),
        },
        owners=owners,
        head_reachable=head_reachable,
        parents=parents,
    )


def _pipe(from_sha: str, to_sha: str) -> Pipe:
    return Pipe(from_sha=from_sha, to_sha=to_sha, from_lane=0, to_lane=0, kind=PipeKind.CONTINUES)


def test_reachable_walks_all_parents():
    """Verify a merge commit reaches both of its sides."""
    # Given
    parents = {"m": ("a", "b"), "a": ("r",), "b": ("r",), "r": ()}

    # When
    result = reachable(["m"], parents)

    # Then
    assert result == frozenset({"m", "a", "b", "r"})


def test_reachable_ignores_parents_outside_window():
    """Verify parents missing from the map are neither followed nor returned."""
    # Given
    parents = {"a": ("b", "x"), "b": ("y",)}

    # When
    result = reachable(["a"], parents)

    # Then
    assert result == frozenset({"a", "b"})


def test_reachable_stops_at_stop_set():
    """Verify nodes in the stop set are not returned or expanded."""
    # Given
    parents = {"a": ("b",), "b": ("c",), "c": ()}

    # When
    result = reachable(["a"], parents, stop=frozenset({"b"}))

    # Then
    assert result == frozenset({"a"})


def test_default_owns_everything_it_reaches():
    """Verify the default branch owns its history and a feature owns only its own commits."""
    # Given
    parents = {"m2": ("m1",), "m1": (), "f1": ("m1",)}

    # When
    owners = assign_owners(
        parents,
        default_tip="m2",
        branch_tips={"main": "m2", "feat": "f1"},
        current=None,
        default="main",
    )

    # Then
    assert owners == {"m2": "main", "m1": "main", "f1": "feat"}


def test_stacked_branches_smallest_set_wins():
    """Verify a stacked branch keeps its own commit and the base branch keeps the shared one."""
    # Given
    parents = {"b1": ("a1",), "a1": ()}

    # When
    owners = assign_owners(
        parents,
        default_tip=None,
        branch_tips={"feat-api": "a1", "feat-auth": "b1"},
        current=None,
        default=None,
    )

    # Then
    assert owners == {"a1": "feat-api", "b1": "feat-auth"}


def test_tie_prefers_current_then_name():
    """Verify identical sets go to the current branch, else to the lower name."""
    # Given
    parents = {"a": ()}
    tips = {"beta": "a", "alpha": "a"}

    # When
    with_current = assign_owners(
        parents, default_tip=None, branch_tips=tips, current="beta", default=None
    )
    without_current = assign_owners(
        parents, default_tip=None, branch_tips=tips, current=None, default=None
    )

    # Then
    assert with_current == {"a": "beta"}
    assert without_current == {"a": "alpha"}


def test_merged_commit_belongs_to_default_even_if_branch_points_at_it():
    """Verify a stale branch tip already reached by the default branch owns nothing."""
    # Given
    parents = {"m2": ("m1",), "m1": ()}

    # When
    owners = assign_owners(
        parents,
        default_tip="m2",
        branch_tips={"main": "m2", "stale": "m1"},
        current=None,
        default="main",
    )

    # Then
    assert owners == {"m2": "main", "m1": "main"}


def test_unrelated_commit_has_no_owner():
    """Verify a commit no local branch reaches is absent from the result."""
    # Given
    parents = {"m1": (), "orphan": ()}

    # When
    owners = assign_owners(
        parents, default_tip="m1", branch_tips={"main": "m1"}, current=None, default="main"
    )

    # Then
    assert "orphan" not in owners


def test_no_default_branch():
    """Verify branches own their full reachable sets, split by the smallest-set rule."""
    # Given
    parents = {"f2": ("f1",), "f1": ("r",), "g1": ("r",), "r": ()}

    # When
    owners = assign_owners(
        parents,
        default_tip=None,
        branch_tips={"feat": "f2", "other": "g1"},
        current=None,
        default=None,
    )

    # Then
    assert owners == {"f2": "feat", "f1": "feat", "g1": "other", "r": "other"}


def test_default_without_tip_leaves_default_history_to_other_branches():
    """Verify a default name with no tip claims nothing, so a feature branch owns what it reaches."""
    # Given a default branch name whose tip is unknown
    parents = {"f1": ("m1",), "m1": ()}

    # When
    owners = assign_owners(
        parents,
        default_tip=None,
        branch_tips={"main": "m1", "feat": "f1"},
        current=None,
        default="main",
    )

    # Then the default branch owns nothing and feat owns the whole chain
    assert owners == {"f1": "feat", "m1": "feat"}


def test_color_slot_is_stable():
    """Verify a name maps to the same palette slot on every call."""
    # Given
    name = "feature/login"

    # When
    first = assign_colors([name])
    second = assign_colors([name])

    # Then
    assert first == second == {name: PALETTE[_slot(name)]}


def test_collision_probes_to_next_free_slot():
    """Verify the later of two colliding names takes the next free slot."""
    # Given
    names = (f"b{i}" for i in itertools.count())
    first = next(names)
    second = next(n for n in names if _slot(n) == _slot(first))
    ordered = sorted([first, second])

    # When
    colors = assign_colors([second, first])

    # Then
    assert colors[ordered[0]] == PALETTE[_slot(ordered[0])]
    assert colors[ordered[1]] == PALETTE[(_slot(ordered[0]) + 1) % len(PALETTE)]


def test_more_than_six_branches_reuse_colors():
    """Verify every branch gets a palette color and every slot is used past capacity."""
    # Given
    names = [f"branch-{i}" for i in range(8)]

    # When
    colors = assign_colors(names)

    # Then
    assert set(colors) == set(names)
    assert set(colors.values()) == set(PALETTE)


def test_commit_style():
    """Verify commit styles for feature, default, unowned, and unreachable commits."""
    # Given
    ctx = _context(
        parents={"f1": (), "m1": (), "o": (), "f2": ()},
        owners={"f1": "feat", "m1": "main", "f2": "feat"},
        head_reachable=frozenset({"f1", "m1", "o"}),
    )

    # When / Then
    assert ctx.commit_style("f1") == "cyan"
    assert ctx.commit_style("m1") == ""
    assert ctx.commit_style("o") == "dim"
    assert ctx.commit_style("f2") == "cyan dim"
    assert ctx.owner("f1") == ctx.branches["feat"]
    assert ctx.owner("o") is None


def test_sha_style():
    """Verify SHA styles are the owner color, plain for default and unowned, never dimmed."""
    # Given
    ctx = _context(
        parents={"f1": (), "m1": (), "o": ()},
        owners={"f1": "feat", "m1": "main"},
        head_reachable=frozenset(),
    )

    # When / Then
    assert ctx.sha_style("f1") == "cyan"
    assert ctx.sha_style("m1") == ""
    assert ctx.sha_style("o") == ""


def test_commit_style_default_outside_head_is_plain_dim():
    """Verify a default-branch commit outside HEAD's reach is exactly dim."""
    # Given
    ctx = _context(parents={"m1": ()}, owners={"m1": "main"}, head_reachable=frozenset())

    # When / Then
    assert ctx.commit_style("m1") == "dim"


def test_pipe_style_first_parent_takes_child_color():
    """Verify a first-parent pipe takes the color of the child commit's branch."""
    # Given
    ctx = _context(
        parents={"f1": ("m1",), "m1": ()},
        owners={"f1": "feat", "m1": "main"},
        head_reachable=frozenset({"f1", "m1"}),
    )

    # When / Then
    assert ctx.pipe_style(_pipe("f1", "m1")) == "cyan"


def test_pipe_style_merge_parent_takes_parent_color():
    """Verify a merge's second-parent pipe takes the merged branch's color."""
    # Given
    ctx = _context(
        parents={"m2": ("m1", "f1"), "m1": (), "f1": ()},
        owners={"m2": "main", "m1": "main", "f1": "feat"},
        head_reachable=frozenset({"m2", "m1", "f1"}),
    )

    # When / Then
    assert ctx.pipe_style(_pipe("m2", "f1")) == "cyan"
    assert ctx.pipe_style(_pipe("m2", "m1")) == ""


def test_pipe_style_second_parent_ignores_first_parent_outside_window():
    """Verify a merge's second-parent pipe takes that parent's color when the first parent is hidden."""
    # Given a merge whose first parent is outside the window
    ctx = _context(
        parents={"m2": ("hidden", "f1"), "f1": ()},
        owners={"m2": "main", "f1": "feat"},
        head_reachable=frozenset({"m2", "f1"}),
    )

    # When / Then
    assert ctx.pipe_style(_pipe("m2", "f1")) == "cyan"


def test_pipe_style_dims_when_child_unreachable():
    """Verify a pipe from a commit outside HEAD's reach is dimmed."""
    # Given
    ctx = _context(
        parents={"f1": ("m1",), "m1": ()},
        owners={"f1": "feat", "m1": "main"},
        head_reachable=frozenset({"m1"}),
    )

    # When / Then
    assert ctx.pipe_style(_pipe("f1", "m1")) == "cyan dim"


def test_pipe_style_parent_outside_window_is_dim():
    """Verify a non-first-parent pipe whose parent has no owner is dim."""
    # Given
    ctx = _context(
        parents={"m2": ("m1", "x"), "m1": ()},
        owners={"m2": "main", "m1": "main"},
        head_reachable=frozenset({"m2", "m1"}),
    )

    # When / Then
    assert ctx.pipe_style(_pipe("m2", "x")) == "dim"


def _window(repo: Path) -> tuple[dict[str, tuple[str, ...]], str]:
    out = _run_git("log", "--all", "--format=%H %P", cwd=repo).stdout
    parents = {
        line.split()[0]: tuple(line.split()[1:]) for line in out.splitlines() if line.strip()
    }
    return parents, _run_git("rev-parse", "main", cwd=repo).stdout.strip()


def test_current_branch_and_head(tmp_git_repo: Path):
    """Verify the current branch and HEAD's reachable commits are read from git."""
    # Given
    create_tmp_branch(tmp_git_repo, "feat")
    create_tmp_commit(tmp_git_repo, "feature work")
    parents, main_tip = _window(tmp_git_repo)
    feat_tip = _run_git("rev-parse", "feat", cwd=tmp_git_repo).stdout.strip()

    # When
    context = build_log_context(parents, default="main", default_tip=main_tip)

    # Then
    assert context.current == "feat"
    assert {feat_tip, main_tip} <= context.head_reachable
    assert context.branches["feat"].is_current
    assert context.branches["main"].is_default
    assert context.branches["main"].color == ""
    assert context.owners[feat_tip] == "feat"


def test_detached_head_has_no_current_branch(tmp_git_repo: Path):
    """Verify a detached HEAD yields no current branch but still computes reachability."""
    # Given
    create_tmp_branch(tmp_git_repo, "feat")
    create_tmp_commit(tmp_git_repo, "feature work")
    detach_tmp_head(tmp_git_repo)
    parents, main_tip = _window(tmp_git_repo)
    head = _run_git("rev-parse", "HEAD", cwd=tmp_git_repo).stdout.strip()

    # When
    context = build_log_context(parents, default="main", default_tip=main_tip)

    # Then
    assert context.current is None
    assert head in context.head_reachable
    assert not any(b.is_current for b in context.branches.values())


def test_branch_outside_window_is_not_visible(tmp_git_repo: Path):
    """Verify a branch whose commits are absent from the window is hidden."""
    # Given
    create_tmp_branch(tmp_git_repo, "far")
    create_tmp_commit(tmp_git_repo, "far work")
    far_tip = _run_git("rev-parse", "far", cwd=tmp_git_repo).stdout.strip()
    checkout_tmp_branch(tmp_git_repo, "main")
    parents, main_tip = _window(tmp_git_repo)
    del parents[far_tip]

    # When
    context = build_log_context(parents, default="main", default_tip=main_tip)

    # Then
    assert "far" not in context.branches
    assert "far" not in context.owners.values()


def test_empty_branch_at_visible_tip_is_visible(tmp_git_repo: Path):
    """Verify a branch sitting on a visible commit is shown without owning commits."""
    # Given
    _run_git("branch", "empty", cwd=tmp_git_repo)
    parents, main_tip = _window(tmp_git_repo)

    # When
    context = build_log_context(parents, default="main", default_tip=main_tip)

    # Then
    assert context.branches["empty"].color in PALETTE
    assert "empty" not in context.owners.values()


def test_colors_only_for_visible_branches(tmp_git_repo: Path):
    """Verify a hidden branch does not take a palette slot from a visible one."""
    # Given
    first, second = next(
        (a, b)
        for a, b in itertools.combinations((f"b{i}" for i in range(40)), 2)
        if _slot(a) == _slot(b)
    )
    for name in (first, second):
        create_tmp_branch(tmp_git_repo, name)
        create_tmp_commit(tmp_git_repo, f"{name} work")
        checkout_tmp_branch(tmp_git_repo, "main")
    parents, main_tip = _window(tmp_git_repo)
    del parents[_run_git("rev-parse", first, cwd=tmp_git_repo).stdout.strip()]

    # When
    context = build_log_context(parents, default="main", default_tip=main_tip)

    # Then
    assert first not in context.branches
    assert context.branches[second].color == PALETTE[_slot(second)]


def test_tag_sharing_a_branch_name_does_not_rename_the_branch(tmp_git_repo: Path):
    """Verify a tag named like a branch leaves the branch's plain name intact."""
    # Given a tag with the same name as the default branch and as a feature branch
    create_tmp_branch(tmp_git_repo, "feat")
    create_tmp_commit(tmp_git_repo, "feature work")
    _run_git("tag", "main", "main", cwd=tmp_git_repo)
    _run_git("tag", "feat", cwd=tmp_git_repo)
    parents, main_tip = _window(tmp_git_repo)

    # When
    context = build_log_context(parents, default="main", default_tip=main_tip)

    # Then the branches keep their names and the checked-out one is still current
    assert set(context.branches) == {"main", "feat"}
    assert context.current == "feat"
    assert context.branches["main"].is_default


def test_nested_branch_name_is_kept_whole(tmp_git_repo: Path):
    """Verify a branch name containing slashes is read in full."""
    # Given a checked-out branch with a nested name
    create_tmp_branch(tmp_git_repo, "feat/deep/x")
    create_tmp_commit(tmp_git_repo, "nested work")
    parents, main_tip = _window(tmp_git_repo)

    # When
    context = build_log_context(parents, default="main", default_tip=main_tip)

    # Then
    assert context.current == "feat/deep/x"
    assert "feat/deep/x" in context.branches


def test_failed_ref_listing_is_logged(tmp_git_repo: Path, mocker):
    """Verify a failing for-each-ref is reported at debug level instead of vanishing."""
    # Given for-each-ref failing
    real_git = git

    def fake_git(*args: str, **kwargs: object) -> CompletedCommand:
        if args[0] == "for-each-ref":
            return CompletedCommand(
                argv=("git",), returncode=1, stdout="", stderr="boom", duration=0.0, cwd=None
            )
        return real_git(*args, **kwargs)

    mocker.patch("gx.lib.log_context.git", side_effect=fake_git)
    debug = mocker.patch("gx.lib.log_context.pp.debug")
    parents, main_tip = _window(tmp_git_repo)

    # When
    build_log_context(parents, default="main", default_tip=main_tip)

    # Then
    debug.assert_called_once()
    assert "for-each-ref" in debug.call_args.args[0]


def _git_result(stdout: str) -> CompletedCommand:
    return CompletedCommand(
        argv=("git",), returncode=0, stdout=stdout, stderr="", duration=0.0, cwd=None
    )


def _sha(repo: Path, rev: str = "HEAD") -> str:
    return _run_git("rev-parse", rev, cwd=repo).stdout.strip()


@pytest.mark.parametrize(
    ("track", "expected"),
    [
        ("", (0, 0, False)),
        ("[ahead 2]", (2, 0, False)),
        ("[behind 3]", (0, 3, False)),
        ("[ahead 2, behind 1]", (2, 1, False)),
        ("[gone]", (0, 0, True)),
        ("[ahead 1, gone]", (1, 0, False)),
    ],
)
def test_parse_track(track: str, expected: tuple[int, int, bool]):
    """Verify the ahead, behind, and gone parts are read from upstream:track."""
    assert parse_track(track) == expected


def test_tracking_read_with_branch_refs(tmp_git_repo: Path):
    """Verify tracking carries the upstream names and the ahead count."""
    # Given feat pushed with an upstream, then one more local commit
    create_tmp_branch(tmp_git_repo, "feat")
    create_tmp_commit(tmp_git_repo, "one")
    push_tmp_branch(tmp_git_repo)
    create_tmp_commit(tmp_git_repo, "two")

    # When
    refs = read_branch_refs()

    # Then
    assert refs.tracking["feat"] == Tracking(
        upstream="origin/feat",
        upstream_ref="refs/remotes/origin/feat",
        ahead=1,
        behind=0,
        gone=False,
    )
    assert refs.tracking["main"].upstream == "origin/main"


def test_branch_without_upstream_has_no_tracking(tmp_git_repo: Path):
    """Verify a branch with no upstream is absent from tracking."""
    create_tmp_branch(tmp_git_repo, "feat")
    assert "feat" not in read_branch_refs().tracking


def test_gone_upstream(tmp_git_repo: Path):
    """Verify a deleted upstream is flagged gone and yields no unpushed commits."""
    # Given feat whose remote branch was deleted
    create_tmp_branch(tmp_git_repo, "feat")
    create_tmp_commit(tmp_git_repo, "one")
    push_tmp_branch(tmp_git_repo)
    delete_tmp_remote_branch(tmp_git_repo, "feat")

    # When
    tracking = read_branch_refs().tracking["feat"]
    parents, main_tip = _window(tmp_git_repo)
    context = build_log_context(parents, default="main", default_tip=main_tip)

    # Then
    assert (tracking.ahead, tracking.behind, tracking.gone) == (0, 0, True)
    assert context.branches["feat"].upstream_gone is True
    assert context.unpushed == frozenset()


def test_unpushed_are_exactly_the_ahead_commits(tmp_git_repo: Path):
    """Verify only commits missing from the upstream are unpushed."""
    # Given feat pushed at "one", then "two" and "three" local only
    create_tmp_branch(tmp_git_repo, "feat")
    create_tmp_commit(tmp_git_repo, "one")
    push_tmp_branch(tmp_git_repo)
    create_tmp_commit(tmp_git_repo, "two")
    sha_two = _sha(tmp_git_repo)
    create_tmp_commit(tmp_git_repo, "three")
    sha_three = _sha(tmp_git_repo)
    # And solo with a commit but no upstream
    checkout_tmp_branch(tmp_git_repo, "main")
    create_tmp_branch(tmp_git_repo, "solo")
    create_tmp_commit(tmp_git_repo, "solo-one")
    sha_solo = _sha(tmp_git_repo)
    parents, main_tip = _window(tmp_git_repo)

    # When
    context = build_log_context(parents, default="main", default_tip=main_tip)

    # Then
    assert context.unpushed == {sha_two, sha_three}
    assert sha_solo not in context.unpushed
    assert context.branches["feat"].ahead == 2
    assert context.branches["feat"].upstream == "origin/feat"


def test_unpushed_limited_to_window(mocker):
    """Verify unpushed commits outside the window are dropped."""
    mocker.patch("gx.lib.log_context.git", return_value=_git_result("a\nb"))
    tracking = {"feat": Tracking("origin/feat", "refs/remotes/origin/feat", 2, 0, gone=False)}
    assert read_unpushed(tracking, {"feat": "a"}, ["a"]) == {"a"}


def test_unpushed_skips_branch_tracking_a_local_branch(mocker):
    """Verify a local upstream never produces unpushed commits."""
    git_mock = mocker.patch("gx.lib.log_context.git")
    tracking = {"stacked": Tracking("main", "refs/heads/main", 2, 0, gone=False)}
    assert read_unpushed(tracking, {"stacked": "a"}, ["a"]) == frozenset()
    git_mock.assert_not_called()


def test_unpushed_skips_branch_whose_tip_is_outside_window(mocker):
    """Verify no rev-list runs for a branch whose tip the window does not reach."""
    git_mock = mocker.patch("gx.lib.log_context.git")
    tracking = {"feat": Tracking("origin/feat", "refs/remotes/origin/feat", 2, 0, gone=False)}
    assert read_unpushed(tracking, {"feat": "zzz"}, ["a"]) == frozenset()
    git_mock.assert_not_called()


def test_branch_tracking_a_local_branch_is_not_remote_tracked(tmp_git_repo: Path):
    """Verify a local upstream keeps its sync counts but marks no pushed commit unpushed."""
    # Given feat pushed with one commit, and stacked on top tracking local main
    create_tmp_branch(tmp_git_repo, "feat")
    create_tmp_commit(tmp_git_repo, "one")
    push_tmp_branch(tmp_git_repo)
    create_tmp_branch(tmp_git_repo, "stacked")
    create_tmp_commit(tmp_git_repo, "two")
    _run_git("branch", "-u", "main", "stacked", cwd=tmp_git_repo)
    parents, main_tip = _window(tmp_git_repo)

    # When
    context = build_log_context(parents, default="main", default_tip=main_tip)

    # Then the suffix data matches git status, but nothing is unpushed or remote-tracked
    stacked = context.branches["stacked"]
    assert (stacked.upstream, stacked.ahead) == ("main", 2)
    assert stacked.has_remote_upstream is False
    assert context.branches["feat"].has_remote_upstream is True
    assert context.unpushed == frozenset()


def test_behind_is_read_from_git(tmp_git_repo: Path):
    """Verify the behind count reaches the context."""
    # Given feat pushed with two commits, then reset one commit behind its upstream
    create_tmp_branch(tmp_git_repo, "feat")
    create_tmp_commit(tmp_git_repo, "one")
    create_tmp_commit(tmp_git_repo, "two")
    push_tmp_branch(tmp_git_repo)
    _run_git("reset", "--hard", "HEAD~1", cwd=tmp_git_repo)
    parents, main_tip = _window(tmp_git_repo)

    # When
    refs = read_branch_refs()
    context = build_log_context(parents, default="main", default_tip=main_tip, refs=refs)

    # Then
    assert (refs.tracking["feat"].ahead, refs.tracking["feat"].behind) == (0, 1)
    assert context.branches["feat"].behind == 1


def test_tracking_read_for_branch_sharing_a_tag_name(tmp_git_repo: Path):
    """Verify a tag named like a pushed branch does not hide the branch's upstream."""
    # Given a pushed branch v1 and a tag v1
    create_tmp_branch(tmp_git_repo, "v1")
    create_tmp_commit(tmp_git_repo, "one")
    push_tmp_branch(tmp_git_repo)
    _run_git("tag", "v1", cwd=tmp_git_repo)

    # When
    tracking = read_branch_refs().tracking

    # Then
    assert tracking["v1"].upstream == "origin/v1"
    assert tracking["v1"].upstream_ref == "refs/remotes/origin/v1"


def test_unpushed_skips_branches_not_ahead(mocker):
    """Verify git is not consulted for a branch with nothing to push."""
    git_mock = mocker.patch("gx.lib.log_context.git")
    tracking = {"feat": Tracking("origin/feat", "refs/remotes/origin/feat", 0, 3, gone=False)}
    read_unpushed(tracking, {"feat": "a"}, ["a"])
    git_mock.assert_not_called()


def test_unpushed_failure_is_logged_and_skipped(mocker):
    """Verify a failing rev-list is reported at debug level and skipped."""
    failed = CompletedCommand(
        argv=("git",), returncode=1, stdout="", stderr="boom", duration=0.0, cwd=None
    )
    mocker.patch("gx.lib.log_context.git", return_value=failed)
    debug = mocker.patch("gx.lib.log_context.pp.debug")
    tracking = {"feat": Tracking("origin/feat", "refs/remotes/origin/feat", 2, 0, gone=False)}
    assert read_unpushed(tracking, {"feat": "a"}, ["a"]) == frozenset()
    debug.assert_called_once()


def test_no_remotes_reads_no_tracking(tmp_git_repo: Path):
    """Verify a repo without remotes has no upstream, remotes, or unpushed commits."""
    _run_git("remote", "remove", "origin", cwd=tmp_git_repo)
    parents, main_tip = _window(tmp_git_repo)
    context = build_log_context(parents, default="main", default_tip=main_tip)
    assert context.remotes == frozenset()
    assert context.branches["main"].upstream is None
    assert context.unpushed == frozenset()


def test_remote_glyphs_follow_nerd_font(tmp_git_repo: Path, mocker):
    """Verify remote glyphs are only produced when nerd fonts are on."""
    parents, main_tip = _window(tmp_git_repo)
    for target in ("gx.lib.log_context.config", "gx.lib.refs.config"):
        mocker.patch(target, GxConfig(nerd_font=False))
    assert build_log_context(parents, default="main", default_tip=main_tip).remote_glyphs == {}
    for target in ("gx.lib.log_context.config", "gx.lib.refs.config"):
        mocker.patch(target, GxConfig(nerd_font=True))
    context = build_log_context(parents, default="main", default_tip=main_tip)
    assert context.remotes == {"origin"}
    assert context.remote_glyphs == {"origin": GIT_GLYPH}
