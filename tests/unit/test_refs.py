"""Tests for the shared ref decoration parser and remote helpers."""

from __future__ import annotations

import pytest

from gx.lib.config import GxConfig
from gx.lib.refs import (
    GIT_GLYPH,
    GITHUB_GLYPH,
    GITLAB_GLYPH,
    REMOTE_FALLBACK,
    RefDecoration,
    parse_refs,
    read_remotes,
    remote_glyph,
    remote_of,
)

REMOTES = frozenset({"origin", "upstream"})


class TestParseRefs:
    """Tests for parsing a %D decoration string."""

    def test_head_branch_is_local_and_head(self):
        """Verify `HEAD -> x` is both the head and a local branch."""
        refs = parse_refs("HEAD -> feat, origin/feat, main", REMOTES)
        assert refs.head == "feat"
        assert refs.branches == ("feat", "main")
        assert refs.remotes == ("origin/feat",)
        assert refs.detached is False

    def test_bare_head_is_detached(self):
        """Verify a bare HEAD marks a detached head."""
        refs = parse_refs("HEAD, main", REMOTES)
        assert refs.detached is True
        assert refs.head is None
        assert refs.branches == ("main",)

    def test_tags(self):
        """Verify tag refs are collected."""
        assert parse_refs("tag: v1.0, tag: v1.0.1", REMOTES).tags == ("v1.0", "v1.0.1")

    def test_remote_head_alias_dropped(self):
        """Verify the symbolic <remote>/HEAD alias is dropped."""
        assert parse_refs("origin/HEAD, origin/main", REMOTES).remotes == ("origin/main",)

    def test_slash_branch_is_local(self):
        """Verify a slash branch with an unconfigured prefix is local."""
        refs = parse_refs("feat/x", REMOTES)
        assert refs.branches == ("feat/x",)
        assert refs.remotes == ()

    def test_any_configured_remote_is_remote(self):
        """Verify remote classification uses the given remote names."""
        assert parse_refs("gitea/main", frozenset({"gitea"})).remotes == ("gitea/main",)

    def test_unconfigured_prefix_is_local(self):
        """Verify a ref is local when no remotes are configured."""
        assert parse_refs("origin/main", frozenset()).branches == ("origin/main",)

    def test_full_refname_is_other(self):
        """Verify full ref names outside heads, remotes and tags land in others."""
        refs = parse_refs("refs/pull/1/head", REMOTES)
        assert refs.others == ("refs/pull/1/head",)
        assert refs.branches == ()

    def test_remote_name_with_slash(self):
        """Verify a remote whose name contains a slash qualifies its refs."""
        remotes = frozenset({"team/fork"})
        refs = parse_refs("team/fork/main, team/fork/HEAD, team/other", remotes)
        assert refs.remotes == ("team/fork/main",)
        assert refs.branches == ("team/other",)

    def test_longest_remote_wins(self):
        """Verify a nested remote name beats a shorter prefix remote."""
        refs = parse_refs("team/fork/main", frozenset({"team", "team/fork"}))
        assert refs.remotes == ("team/fork/main",)

    @pytest.mark.parametrize("raw", ["", "   "])
    def test_empty(self, raw):
        """Verify blank input yields an empty decoration."""
        assert parse_refs(raw, REMOTES) == RefDecoration()


def test_read_remotes(tmp_git_repo):
    """Verify remotes map name to fetch URL."""
    remotes = read_remotes()
    assert list(remotes) == ["origin"]
    assert remotes["origin"].endswith("remote.git")


def test_read_remotes_keeps_fetch_url_once_per_remote(mocker):
    """Verify duplicate fetch and push rows yield one entry holding the fetch URL."""
    stdout = (
        "origin\tgit@host:fetch.git (fetch)\norigin\tgit@host:push.git (push)\n"
        "up\tgit@host:up.git (fetch)\nup\tgit@host:up.git (push)"
    )
    mocker.patch("gx.lib.refs.git", autospec=True, return_value=mocker.Mock(ok=True, stdout=stdout))
    assert read_remotes() == {"origin": "git@host:fetch.git", "up": "git@host:up.git"}


class TestRemoteOf:
    """Tests for matching a ref to its configured remote."""

    def test_longest_match(self):
        """Verify the longest qualifying remote name is returned."""
        assert remote_of("team/fork/main", ["team", "team/fork"]) == "team/fork"

    def test_none_for_local_branch(self):
        """Verify a ref no remote qualifies yields None."""
        assert remote_of("feat/x", ["origin"]) is None

    def test_requires_slash_after_name(self):
        """Verify a remote name that merely prefixes the ref does not match."""
        assert remote_of("origin2/main", ["origin"]) is None


def test_read_remotes_failure(mocker):
    """Verify a failed git call yields no remotes."""
    mocker.patch("gx.lib.refs.git", autospec=True, return_value=mocker.Mock(ok=False, stdout=""))
    assert read_remotes() == {}


class TestRemoteGlyph:
    """Tests for host-aware remote glyph selection."""

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://github.com/me/repo.git", GITHUB_GLYPH),
            ("git@gitlab.com:me/repo.git", GITLAB_GLYPH),
            ("https://bitbucket.org/me/repo.git", GIT_GLYPH),
        ],
    )
    def test_glyph_by_host(self, url, expected):
        """Verify the glyph matches the remote host."""
        assert remote_glyph(url) == expected

    @pytest.mark.parametrize(
        "url",
        [
            "https://github.com/me/repo.git",
            "git@gitlab.com:me/repo.git",
            "https://bitbucket.org/me/repo.git",
        ],
    )
    def test_ascii_fallback_when_nerd_font_disabled(self, mocker, url):
        """Verify every host collapses to one ASCII symbol when nerd fonts are off."""
        mocker.patch("gx.lib.refs.config", GxConfig(nerd_font=False))
        assert remote_glyph(url) == REMOTE_FALLBACK
