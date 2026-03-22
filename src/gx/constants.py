"""Constants for the gx package."""

import os
from enum import IntEnum
from pathlib import Path
from typing import Literal

PACKAGE_NAME = (
    __package__.replace("_", "-").replace(".", "-").replace(" ", "-") if __package__ else "gx"
)
CONFIG_DIR = Path(os.getenv("XDG_CONFIG_HOME", "~/.config")).expanduser().absolute() / PACKAGE_NAME
DATA_DIR = Path(os.getenv("XDG_DATA_HOME", "~/.local/share")).expanduser().absolute() / PACKAGE_NAME
STATE_DIR = (
    Path(os.getenv("XDG_STATE_HOME", "~/.local/state")).expanduser().absolute() / PACKAGE_NAME
)
CACHE_DIR = Path(os.getenv("XDG_CACHE_HOME", "~/.cache")).expanduser().absolute() / PACKAGE_NAME
PROJECT_ROOT_PATH = Path(__file__).parents[2].absolute()
PACKAGE_ROOT_PATH = Path(__file__).parents[0].absolute()


class Verbosity(IntEnum):
    """Output verbosity levels for the CLI."""

    INFO = 0
    DEBUG = 1
    TRACE = 2


READ_ONLY_GIT_COMMANDS: frozenset[str] = frozenset(
    {
        "status",
        "log",
        "diff",
        "show",
        "rev-parse",
        "remote",
        "config",
        "ls-files",
        "describe",
        "symbolic-ref",
        "merge-base",
        "for-each-ref",
        "rev-list",
        "check-ref-format",
        "check-ignore",
    }
)

READ_ONLY_GIT_COMPOUND_COMMANDS: dict[str, frozenset[str]] = {
    "branch": frozenset(
        {"--merged", "--no-merged", "-vv", "--list", "-l", "-a", "--all", "-r", "--remotes"}
    ),
    "stash": frozenset({"list"}),
    "worktree": frozenset({"list"}),
}

StaleReason = Literal["gone", "merged", "empty"]
