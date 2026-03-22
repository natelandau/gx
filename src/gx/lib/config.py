"""User configuration for gx, loaded from TOML file with env var overrides."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from gx.constants import CONFIG_DIR
from gx.lib.console import warning


@dataclass(frozen=True)
class GxConfig:
    """User-configurable settings for gx.

    Immutable after creation. Defaults match the original hardcoded values
    so gx works identically without a config file.
    """

    branch_prefix: str = "feat"
    worktree_directory: str = ".worktrees"
    protected_branches: frozenset[str] = field(
        default_factory=lambda: frozenset({"main", "master", "develop"})
    )
    remote_name: str = "origin"


def _load_toml() -> dict:
    """Load config from TOML file if it exists.

    Returns:
        A dict of parsed TOML data, or empty dict if the file is missing or invalid.
    """
    config_path = CONFIG_DIR / "config.toml"
    if not config_path.is_file():
        return {}

    try:
        with config_path.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError:
        warning(f"Invalid TOML in config file {config_path}, using defaults.")
        return {}


def _extract_str(table: dict, key: str, config_path: str) -> str | None:
    """Extract a string value from a TOML table, warning if the type is wrong.

    Args:
        table: A TOML table dict.
        key: The key to look up in the table.
        config_path: Dotted config path for warning messages (e.g. "branches.prefix").

    Returns:
        The string value, or None if the key is absent or has the wrong type.
    """
    if key not in table:
        return None
    value = table[key]
    if isinstance(value, str):
        return value
    warning(f"Config: {config_path} must be a string, got {type(value).__name__}. Skipping.")
    return None


def _extract_toml_values(data: dict) -> dict:
    """Extract and validate known config values from parsed TOML data.

    Args:
        data: Parsed TOML dict (possibly with nested tables).

    Returns:
        A flat dict of validated config field names to values.
    """
    values: dict = {}

    branches = data.get("branches", {})
    if isinstance(branches, dict):
        if prefix := _extract_str(branches, "prefix", "branches.prefix"):
            values["branch_prefix"] = prefix
        if "protected" in branches:
            protected = branches["protected"]
            if isinstance(protected, list) and all(isinstance(b, str) for b in protected):
                values["protected_branches"] = frozenset(protected)
            else:
                warning("Config: branches.protected must be a list of strings. Skipping.")

    worktree = data.get("worktree", {})
    if isinstance(worktree, dict) and (
        directory := _extract_str(worktree, "directory", "worktree.directory")
    ):
        values["worktree_directory"] = directory

    remote = data.get("remote", {})
    if isinstance(remote, dict) and (name := _extract_str(remote, "name", "remote.name")):
        values["remote_name"] = name

    return values


def _load_env_overrides() -> dict:
    """Load config overrides from GX_* environment variables.

    Returns:
        A dict of config field names to override values.
    """
    overrides: dict = {}

    if val := os.environ.get("GX_BRANCH_PREFIX"):
        overrides["branch_prefix"] = val

    if val := os.environ.get("GX_WORKTREE_DIRECTORY"):
        overrides["worktree_directory"] = val

    if val := os.environ.get("GX_PROTECTED_BRANCHES"):
        branches = frozenset(b.strip() for b in val.split(",") if b.strip())
        overrides["protected_branches"] = branches

    if val := os.environ.get("GX_REMOTE_NAME"):
        overrides["remote_name"] = val

    return overrides


def _build_config() -> GxConfig:
    """Build a GxConfig from defaults, TOML file, and env var overrides."""
    toml_data = _load_toml()
    values = _extract_toml_values(toml_data)
    env_overrides = _load_env_overrides()
    values.update(env_overrides)
    return GxConfig(**values)


config: GxConfig = _build_config()


def resolve_worktree_directory(repo_root: Path) -> Path:
    """Resolve the configured worktree directory to an absolute path.

    Absolute or home-relative paths (~/...) are used as-is.
    Relative paths are resolved against the repo root.

    Args:
        repo_root: The root directory of the current git repository.

    Returns:
        An absolute Path to the worktree directory.
    """
    expanded = Path(config.worktree_directory).expanduser()

    if expanded.is_absolute():
        return expanded

    return repo_root / expanded
