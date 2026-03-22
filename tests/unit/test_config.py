"""Tests for gx config loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from gx.lib.config import GxConfig, _build_config, resolve_worktree_directory


class TestGxConfigDefaults:
    """Tests for GxConfig default values."""

    def test_default_branch_prefix(self):
        """Verify default branch prefix is 'feat'."""
        cfg = GxConfig()
        assert cfg.branch_prefix == "feat"

    def test_default_worktree_directory(self):
        """Verify default worktree directory is '.worktrees'."""
        cfg = GxConfig()
        assert cfg.worktree_directory == ".worktrees"

    def test_default_protected_branches(self):
        """Verify default protected branches include main, master, develop."""
        cfg = GxConfig()
        assert cfg.protected_branches == frozenset({"main", "master", "develop"})

    def test_default_remote_name(self):
        """Verify default remote name is 'origin'."""
        cfg = GxConfig()
        assert cfg.remote_name == "origin"

    def test_config_is_frozen(self):
        """Verify GxConfig instances are immutable."""
        import dataclasses

        cfg = GxConfig()
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.branch_prefix = "feature"  # type: ignore[misc]


class TestBuildConfigDefaults:
    """Tests for _build_config with no file or env vars."""

    def test_returns_defaults_when_no_file(self, tmp_path, monkeypatch):
        """Verify _build_config returns defaults when config file does not exist."""
        # Given CONFIG_DIR points to an empty temp directory
        monkeypatch.setattr("gx.lib.config.CONFIG_DIR", tmp_path)

        # When building config
        cfg = _build_config()

        # Then all defaults are used
        assert cfg.branch_prefix == "feat"
        assert cfg.worktree_directory == ".worktrees"
        assert cfg.protected_branches == frozenset({"main", "master", "develop"})
        assert cfg.remote_name == "origin"


class TestTomlLoading:
    """Tests for loading config from TOML file."""

    def test_loads_all_keys_from_toml(self, tmp_path, monkeypatch):
        """Verify all TOML keys override defaults."""
        # Given a config file with all keys set
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            '[branches]\nprefix = "feature"\nprotected = ["main", "production"]\n\n'
            '[worktree]\ndirectory = "wt"\n\n'
            '[remote]\nname = "upstream"\n'
        )
        monkeypatch.setattr("gx.lib.config.CONFIG_DIR", tmp_path)

        # When building config
        cfg = _build_config()

        # Then all values come from TOML
        assert cfg.branch_prefix == "feature"
        assert cfg.worktree_directory == "wt"
        assert cfg.protected_branches == frozenset({"main", "production"})
        assert cfg.remote_name == "upstream"

    def test_loads_partial_toml(self, tmp_path, monkeypatch):
        """Verify partial TOML only overrides specified keys."""
        # Given a config file with only branch prefix set
        config_file = tmp_path / "config.toml"
        config_file.write_text('[branches]\nprefix = "feature"\n')
        monkeypatch.setattr("gx.lib.config.CONFIG_DIR", tmp_path)

        # When building config
        cfg = _build_config()

        # Then only branch_prefix is overridden
        assert cfg.branch_prefix == "feature"
        assert cfg.worktree_directory == ".worktrees"
        assert cfg.protected_branches == frozenset({"main", "master", "develop"})
        assert cfg.remote_name == "origin"

    def test_ignores_unknown_keys(self, tmp_path, monkeypatch):
        """Verify unknown TOML keys are silently ignored."""
        # Given a config file with an unknown key
        config_file = tmp_path / "config.toml"
        config_file.write_text('[branches]\nprefix = "feature"\n\n[unknown]\nfoo = "bar"\n')
        monkeypatch.setattr("gx.lib.config.CONFIG_DIR", tmp_path)

        # When building config
        cfg = _build_config()

        # Then known keys load and unknown keys are ignored
        assert cfg.branch_prefix == "feature"

    def test_warns_on_invalid_toml(self, tmp_path, monkeypatch, capsys):
        """Verify invalid TOML syntax warns and falls back to defaults."""
        # Given a config file with invalid TOML
        config_file = tmp_path / "config.toml"
        config_file.write_text("this is not valid toml [[[")
        monkeypatch.setattr("gx.lib.config.CONFIG_DIR", tmp_path)

        # When building config
        cfg = _build_config()

        # Then defaults are used and a warning is printed
        assert cfg.branch_prefix == "feat"
        captured = capsys.readouterr()
        assert "config" in captured.err.lower() or "toml" in captured.err.lower()

    def test_warns_on_wrong_type(self, tmp_path, monkeypatch, capsys):
        """Verify wrong type for a key warns and skips that key."""
        # Given a config file with wrong type for prefix
        config_file = tmp_path / "config.toml"
        config_file.write_text("[branches]\nprefix = 123\n")
        monkeypatch.setattr("gx.lib.config.CONFIG_DIR", tmp_path)

        # When building config
        cfg = _build_config()

        # Then the bad key uses default and a warning is printed
        assert cfg.branch_prefix == "feat"
        captured = capsys.readouterr()
        assert "prefix" in captured.err.lower()


class TestEnvVarOverrides:
    """Tests for environment variable overrides."""

    def test_env_overrides_defaults(self, tmp_path, monkeypatch):
        """Verify env vars override default values."""
        monkeypatch.setattr("gx.lib.config.CONFIG_DIR", tmp_path)
        monkeypatch.setenv("GX_BRANCH_PREFIX", "feature")
        monkeypatch.setenv("GX_REMOTE_NAME", "upstream")
        cfg = _build_config()
        assert cfg.branch_prefix == "feature"
        assert cfg.remote_name == "upstream"

    def test_env_overrides_toml(self, tmp_path, monkeypatch):
        """Verify env vars take priority over TOML values."""
        config_file = tmp_path / "config.toml"
        config_file.write_text('[branches]\nprefix = "feature"\n')
        monkeypatch.setattr("gx.lib.config.CONFIG_DIR", tmp_path)
        monkeypatch.setenv("GX_BRANCH_PREFIX", "fix")
        cfg = _build_config()
        assert cfg.branch_prefix == "fix"

    def test_env_worktree_directory(self, tmp_path, monkeypatch):
        """Verify GX_WORKTREE_DIRECTORY env var works."""
        monkeypatch.setattr("gx.lib.config.CONFIG_DIR", tmp_path)
        monkeypatch.setenv("GX_WORKTREE_DIRECTORY", "~/worktrees")
        cfg = _build_config()
        assert cfg.worktree_directory == "~/worktrees"

    def test_env_protected_branches_comma_separated(self, tmp_path, monkeypatch):
        """Verify GX_PROTECTED_BRANCHES parses comma-separated values."""
        monkeypatch.setattr("gx.lib.config.CONFIG_DIR", tmp_path)
        monkeypatch.setenv("GX_PROTECTED_BRANCHES", "main, production")
        cfg = _build_config()
        assert cfg.protected_branches == frozenset({"main", "production"})

    def test_env_protected_branches_filters_empty(self, tmp_path, monkeypatch):
        """Verify trailing commas don't produce empty entries."""
        monkeypatch.setattr("gx.lib.config.CONFIG_DIR", tmp_path)
        monkeypatch.setenv("GX_PROTECTED_BRANCHES", "main, master,")
        cfg = _build_config()
        assert cfg.protected_branches == frozenset({"main", "master"})


class TestResolveWorktreeDirectory:
    """Tests for resolve_worktree_directory()."""

    def test_relative_path_resolves_against_repo_root(self, tmp_path, monkeypatch):
        """Verify relative path is resolved against the repo root."""
        monkeypatch.setattr("gx.lib.config.config", GxConfig(worktree_directory=".worktrees"))
        result = resolve_worktree_directory(tmp_path)
        assert result == tmp_path / ".worktrees"

    def test_absolute_path_used_as_is(self, tmp_path, monkeypatch):
        """Verify absolute path is used without modification."""
        absolute_dir = str(tmp_path / "worktrees")
        monkeypatch.setattr("gx.lib.config.config", GxConfig(worktree_directory=absolute_dir))
        result = resolve_worktree_directory(tmp_path / "repo")
        assert result == Path(absolute_dir)

    def test_home_relative_path_expands(self, monkeypatch):
        """Verify ~/path expands the home directory."""
        monkeypatch.setattr("gx.lib.config.config", GxConfig(worktree_directory="~/worktrees"))
        result = resolve_worktree_directory(Path("/some/repo"))
        assert result == Path.home() / "worktrees"
        assert result.is_absolute()
