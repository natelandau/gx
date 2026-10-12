"""Duty tasks for the project."""

from __future__ import annotations

import os
import re
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

from duty import duty
from rich.console import Console

if TYPE_CHECKING:
    from duty.context import Context


console = Console()
PYPROJECT = Path("pyproject.toml")
PY_SRC_PATHS = (Path(_) for _ in ("src/", "tests/", "duties.py", "scripts/") if Path(_).exists())
PY_SRC_LIST = tuple(str(_) for _ in PY_SRC_PATHS)
# ruff formats Python fences in Markdown, so format the same docs the prek ruff-format hook sees
FORMAT_LIST = (*PY_SRC_LIST, *(_ for _ in ("docs/", "README.md") if Path(_).exists()))
CI = os.environ.get("CI", "").strip().lower() in {"1", "true", "yes"}
PROJECT_ROOT = Path(__file__).parent
VERSION = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from a string.

    Args:
        text (str): String to remove ANSI escape sequences from.

    Returns:
        str: String without ANSI escape sequences.
    """
    ansi_chars = re.compile(r"(\x9B|\x1B\[)[0-?]*[ -\/]*[@-~]")

    # Replace [ with \[ so rich doesn't interpret output as style tags
    return ansi_chars.sub("", text).replace("[", r"\[")


def gated(name: str, cmd: list[str]) -> list[str]:
    """Wrap a gate command in gate-cache so it skips on a tree where it already passed.

    Args:
        name (str): Marker name for the gate.
        cmd (list[str]): Command to run.

    Returns:
        list[str]: The command prefixed with the gate-cache invocation.
    """
    return ["gate-cache", "--name", name, "--", *cmd]


def pyprefix(title: str) -> str:
    """Add a prefix to the title if CI is true.

    Returns:
        str: Title with prefix if CI is true.
    """
    if CI:
        prefix = f"(python{sys.version_info.major}.{sys.version_info.minor})"
        return f"{prefix:14}{title}"
    return title


@duty(silent=True)
def clean(ctx: Context) -> None:
    """Clean the project."""
    ctx.run("rm -rf .coverage*")
    ctx.run("rm -rf .cache")
    ctx.run("rm -rf build")
    ctx.run("rm -rf dist")
    ctx.run("rm -rf pip-wheel-metadata")
    ctx.run("find . -type d -name __pycache__ | xargs rm -rf")
    ctx.run("find . -name '.DS_Store' -delete")


@duty
def ruff(ctx: Context) -> None:
    """Check the code quality with ruff."""
    ctx.run(
        gated("ruff", ["ruff", "check", "--config", "pyproject.toml", "--no-fix", *PY_SRC_LIST]),
        title=pyprefix("code quality check"),
    )


@duty
def format(ctx: Context) -> None:  # noqa: A001
    """Format the code with ruff."""
    ctx.run(
        gated("format", ["ruff", "format", "--check", "--config", "pyproject.toml", *FORMAT_LIST]),
        title=pyprefix("code formatting"),
    )


@duty
def ty(ctx: Context) -> None:
    """Check the code with ty."""
    ctx.run(
        gated("ty", ["ty", "check", "src/", "tests/"]),
        title="ty check",
    )


@duty
def typos(ctx: Context) -> None:
    """Check the code with typos."""
    ctx.run(
        gated("typos", ["typos", "--config", ".typos.toml"]),
        title=pyprefix("typos check"),
    )


@duty(skip_if=CI, skip_reason="skip prek in CI environments")
def prek(ctx: Context) -> None:
    """Run prek hooks."""
    ctx.run(
        "PREK_SKIP=ty,pytest,ruff-check gate-cache --name prek -- prek run --all-files",
        title=pyprefix("prek hooks"),
    )


@duty(pre=[ruff, format, ty, typos, prek], capture=CI)
def lint(ctx: Context) -> None:
    """Run all linting duties."""


@duty(capture=CI)
def update(ctx: Context) -> None:
    """Update the project."""
    ctx.run(["uv", "lock", "--upgrade"], title="update uv lock")
    ctx.run(["uv", "sync"], title="update uv sync")
    ctx.run(["prek", "autoupdate"], title="prek autoupdate")
    ctx.run(["uvx", "uv-upx", "upgrade", "run"], title="uv-upx upgrade")


@duty()
def test(ctx: Context, *cli_args: str) -> None:
    """Test package and generate coverage reports."""
    cmd = [
        "pytest",
        "tests/",
        "-c",
        "pyproject.toml",
        "--color=yes",
        "--cov",
        "--cov-config=pyproject.toml",
        "--cov-report=xml",
        "--cov-report=term",
        *cli_args,
    ]
    # A marker covers the name, not the arguments, so a filtered pass must not skip the full suite
    ctx.run(
        cmd if cli_args else gated("test", cmd),
        title=pyprefix("Running tests - this may take a while"),
        capture=CI,
    )
