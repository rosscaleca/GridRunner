"""Runtime discovery — scan the system for installed interpreters and versions."""

import asyncio
import os
import platform
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class DiscoveredRuntime:
    script_type: str       # e.g. "python"
    path: str              # e.g. "/usr/local/bin/python3.12"
    version: str | None    # e.g. "3.12.2"
    display_name: str      # e.g. "Python 3.12.2"
    is_default: bool       # True if this is what shutil.which() finds
    source: str            # "system", "pyenv", "homebrew", "nvm", etc.


@dataclass
class DiscoveryStrategy:
    """How to find and version-check interpreters for a script type."""
    binaries: list[str]
    extra_dirs: list[str] = field(default_factory=list)
    version_args: list[str] = field(default_factory=lambda: ["--version"])
    version_regex: str = r"(\d+\.\d+[\.\d]*)"
    display_prefix: str = ""
    stderr_version: bool = False  # Some tools print version to stderr


def _expand_path(p: str) -> list[str]:
    """Expand ~ and globs in a path string, returning existing directories."""
    expanded = os.path.expanduser(p)
    from glob import glob
    return glob(expanded)


def _get_strategies() -> dict[str, DiscoveryStrategy]:
    """Return discovery strategies for all supported script types."""
    python_binaries = ["python3"] + [f"python3.{v}" for v in range(8, 15)] + ["python"]
    python_extra = []
    for p in ["~/.pyenv/versions/*/bin"]:
        python_extra.append(p)
    if platform.system() == "Darwin":
        python_extra.append("/usr/local/opt/python@*/bin")
        python_extra.append("/opt/homebrew/opt/python@*/bin")

    return {
        "python": DiscoveryStrategy(
            binaries=python_binaries,
            extra_dirs=python_extra,
            version_regex=r"Python (\d+\.\d+\.\d+)",
            display_prefix="Python",
        ),
        "node": DiscoveryStrategy(
            binaries=["node"],
            extra_dirs=[
                "~/.nvm/versions/node/*/bin",
                "~/.fnm/node-versions/*/installation/bin",
            ],
            version_regex=r"v?(\d+\.\d+\.\d+)",
            display_prefix="Node.js",
        ),
        "ruby": DiscoveryStrategy(
            binaries=["ruby"],
            extra_dirs=[
                "~/.rbenv/versions/*/bin",
                "~/.rvm/rubies/*/bin",
            ],
            version_regex=r"ruby (\d+\.\d+\.\d+)",
            display_prefix="Ruby",
        ),
        "go": DiscoveryStrategy(
            binaries=["go"],
            version_args=["version"],
            version_regex=r"go(\d+\.\d+\.\d+)",
            display_prefix="Go",
        ),
        "deno": DiscoveryStrategy(
            binaries=["deno"],
            extra_dirs=["~/.deno/bin"],
            version_regex=r"deno (\d+\.\d+\.\d+)",
            display_prefix="Deno",
        ),
        "r": DiscoveryStrategy(
            binaries=["Rscript", "R"],
            version_regex=r"R version (\d+\.\d+\.\d+)",
            display_prefix="R",
            stderr_version=True,
        ),
        "julia": DiscoveryStrategy(
            binaries=["julia"],
            version_regex=r"julia version (\d+\.\d+\.\d+)",
            display_prefix="Julia",
        ),
        "java": DiscoveryStrategy(
            binaries=["java"],
            version_args=["-version"],
            version_regex=r'"(\d+\.\d+[\.\d]*)',
            display_prefix="Java",
            stderr_version=True,
        ),
        "swift": DiscoveryStrategy(
            binaries=["swift"],
            version_regex=r"Swift version (\d+\.\d+[\.\d]*)",
            display_prefix="Swift",
        ),
        "lua": DiscoveryStrategy(
            binaries=["lua", "lua5.4", "lua5.3"],
            version_regex=r"Lua (\d+\.\d+[\.\d]*)",
            display_prefix="Lua",
        ),
        "bash": DiscoveryStrategy(
            binaries=["bash"],
            version_regex=r"version (\d+\.\d+[\.\d]*)",
            display_prefix="Bash",
        ),
        "zsh": DiscoveryStrategy(
            binaries=["zsh"],
            version_regex=r"zsh (\d+\.\d+[\.\d]*)",
            display_prefix="Zsh",
        ),
        "sh": DiscoveryStrategy(
            binaries=["sh"],
            version_regex=r"(\d+\.\d+[\.\d]*)",
            display_prefix="Shell",
        ),
        "perl": DiscoveryStrategy(
            binaries=["perl"],
            version_regex=r"v(\d+\.\d+\.\d+)",
            display_prefix="Perl",
        ),
        "php": DiscoveryStrategy(
            binaries=["php"],
            version_regex=r"PHP (\d+\.\d+\.\d+)",
            display_prefix="PHP",
        ),
        "powershell": DiscoveryStrategy(
            binaries=["pwsh"],
            version_regex=r"(\d+\.\d+\.\d+)",
            display_prefix="PowerShell",
        ),
    }


# Module-level cache
_cache: dict[str, list[DiscoveredRuntime]] = {}


async def _get_version(binary_path: str, strategy: DiscoveryStrategy) -> str | None:
    """Run the version command and extract version string."""
    try:
        proc = await asyncio.create_subprocess_exec(
            binary_path, *strategy.version_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        output = stderr.decode("utf-8", errors="replace") if strategy.stderr_version else stdout.decode("utf-8", errors="replace")
        # Some tools output to both — try both if primary fails
        if not output.strip():
            output = (stdout if strategy.stderr_version else stderr).decode("utf-8", errors="replace")
        match = re.search(strategy.version_regex, output)
        return match.group(1) if match else None
    except (asyncio.TimeoutError, FileNotFoundError, PermissionError, OSError):
        return None


async def _discover_for_type(script_type: str, strategy: DiscoveryStrategy) -> list[DiscoveredRuntime]:
    """Discover all runtimes for a given script type."""
    found: dict[str, str] = {}  # resolved path -> binary name (dedup)

    # Find default binary (what shutil.which resolves to)
    default_path = None
    for binary in strategy.binaries:
        which = shutil.which(binary)
        if which:
            resolved = str(Path(which).resolve())
            if resolved not in found:
                found[resolved] = binary
            if default_path is None:
                default_path = resolved
            break

    # Scan PATH for all matching binaries
    for binary in strategy.binaries:
        which = shutil.which(binary)
        if which:
            resolved = str(Path(which).resolve())
            if resolved not in found:
                found[resolved] = binary

    # Scan extra directories
    for extra_dir_pattern in strategy.extra_dirs:
        for dir_path in _expand_path(extra_dir_pattern):
            for binary in strategy.binaries:
                candidate = Path(dir_path) / binary
                if candidate.exists() and candidate.is_file():
                    resolved = str(candidate.resolve())
                    if resolved not in found:
                        found[resolved] = binary

    # Get versions concurrently
    runtimes = []

    async def _check(path: str, binary: str):
        version = await _get_version(path, strategy)
        display = f"{strategy.display_prefix} {version}" if version else f"{strategy.display_prefix} ({binary})"
        source = "system"
        if "pyenv" in path:
            source = "pyenv"
        elif "homebrew" in path or "/opt/homebrew" in path:
            source = "homebrew"
        elif "nvm" in path:
            source = "nvm"
        elif "fnm" in path:
            source = "fnm"
        elif "rbenv" in path:
            source = "rbenv"
        elif "rvm" in path:
            source = "rvm"
        elif ".deno" in path:
            source = "deno"
        runtimes.append(DiscoveredRuntime(
            script_type=script_type,
            path=path,
            version=version,
            display_name=display,
            is_default=(path == default_path),
            source=source,
        ))

    await asyncio.gather(*[_check(path, binary) for path, binary in found.items()])

    # Sort: default first, then by version descending
    runtimes.sort(key=lambda r: (not r.is_default, r.version or ""), reverse=False)
    return runtimes


async def discover_all(force_refresh: bool = False) -> dict[str, list[DiscoveredRuntime]]:
    """Discover all runtimes. Results are cached for the process lifetime."""
    global _cache
    if _cache and not force_refresh:
        return _cache

    strategies = _get_strategies()
    results = await asyncio.gather(
        *[_discover_for_type(st, strat) for st, strat in strategies.items()]
    )
    _cache = {}
    for st, runtimes in zip(strategies.keys(), results):
        if runtimes:
            _cache[st] = runtimes
    return _cache


async def discover_for_type(script_type: str) -> list[DiscoveredRuntime]:
    """Discover runtimes for a specific script type."""
    all_runtimes = await discover_all()
    return all_runtimes.get(script_type, [])


async def get_interpreter_version(binary_path: str, script_type: str) -> str | None:
    """Get the version string for a specific binary."""
    strategies = _get_strategies()
    strategy = strategies.get(script_type)
    if not strategy:
        return None
    return await _get_version(binary_path, strategy)
