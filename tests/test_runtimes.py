"""Tests for backend.runtimes discovery module."""

import re
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
import pytest_asyncio

from backend.runtimes import (
    _get_strategies,
    _get_version,
    discover_all,
    discover_for_type,
    get_interpreter_version,
    _cache,
    DiscoveredRuntime,
)


# ── Version regex parsing ──────────────────────────────────────────────────


class TestParseVersion:
    """Verify version regex patterns against real-world output."""

    def _match(self, script_type: str, output: str) -> str | None:
        strategy = _get_strategies()[script_type]
        m = re.search(strategy.version_regex, output)
        return m.group(1) if m else None

    def test_python_version(self):
        assert self._match("python", "Python 3.12.2") == "3.12.2"

    def test_python_version_dev(self):
        assert self._match("python", "Python 3.13.0a4") == "3.13.0"

    def test_node_version(self):
        assert self._match("node", "v20.11.1") == "20.11.1"

    def test_ruby_version(self):
        assert self._match("ruby", "ruby 3.3.0 (2023-12-25)") == "3.3.0"

    def test_go_version(self):
        assert self._match("go", "go version go1.22.1 darwin/arm64") == "1.22.1"

    def test_deno_version(self):
        assert self._match("deno", "deno 1.40.5 (release, aarch64-apple-darwin)") == "1.40.5"

    def test_r_version(self):
        assert self._match("r", "R version 4.3.2 (2023-10-31)") == "4.3.2"

    def test_julia_version(self):
        assert self._match("julia", "julia version 1.10.2") == "1.10.2"

    def test_java_version(self):
        assert self._match("java", 'openjdk version "21.0.2" 2024-01-16') == "21.0.2"

    def test_swift_version(self):
        assert self._match("swift", "Swift version 5.9.2 (swift-5.9.2-RELEASE)") == "5.9.2"

    def test_lua_version(self):
        assert self._match("lua", "Lua 5.4.6  Copyright (C) 1994-2023") == "5.4.6"

    def test_bash_version(self):
        assert self._match("bash", "GNU bash, version 5.2.26(1)-release") == "5.2.26"

    def test_zsh_version(self):
        assert self._match("zsh", "zsh 5.9 (x86_64-apple-darwin23.0)") == "5.9"

    def test_perl_version(self):
        assert self._match("perl", "This is perl 5, version 38, subversion 2 (v5.38.2)") == "5.38.2"

    def test_php_version(self):
        assert self._match("php", "PHP 8.3.4 (cli) (built: Mar 16 2024)") == "8.3.4"

    def test_powershell_version(self):
        assert self._match("powershell", "PowerShell 7.4.1") == "7.4.1"


# ── Discovery strategies ──────────────────────────────────────────────────


class TestDiscoveryStrategies:
    def test_all_non_special_types_have_strategies(self):
        """Every script type except 'executable' and 'other' should have a discovery strategy."""
        strategies = _get_strategies()
        from backend.executor import DEFAULT_INTERPRETERS
        for script_type in DEFAULT_INTERPRETERS:
            if script_type in ("executable", "other"):
                continue
            assert script_type in strategies, f"Missing strategy for {script_type}"

    def test_strategies_have_required_fields(self):
        strategies = _get_strategies()
        for name, strat in strategies.items():
            assert len(strat.binaries) > 0, f"{name} has no binaries"
            assert strat.version_regex, f"{name} has no version_regex"
            assert strat.display_prefix, f"{name} has no display_prefix"


# ── Caching behavior ──────────────────────────────────────────────────────


class TestDiscoverAll:
    @pytest.mark.asyncio
    async def test_caching(self):
        """discover_all returns cached results on second call."""
        import backend.runtimes as mod
        mod._cache.clear()

        # First call populates cache
        with patch.object(mod, '_discover_for_type', new_callable=AsyncMock) as mock_discover:
            mock_discover.return_value = [
                DiscoveredRuntime("python", "/usr/bin/python3", "3.12.2", "Python 3.12.2", True, "system")
            ]
            result1 = await discover_all(force_refresh=True)
            call_count = mock_discover.call_count

        # Second call should use cache
        with patch.object(mod, '_discover_for_type', new_callable=AsyncMock) as mock_discover2:
            result2 = await discover_all(force_refresh=False)
            assert mock_discover2.call_count == 0  # Not called — used cache

        mod._cache.clear()

    @pytest.mark.asyncio
    async def test_force_refresh_clears_cache(self):
        """force_refresh=True should re-scan."""
        import backend.runtimes as mod
        mod._cache = {"python": [
            DiscoveredRuntime("python", "/usr/bin/python3", "3.12.2", "Python 3.12.2", True, "system")
        ]}

        with patch.object(mod, '_discover_for_type', new_callable=AsyncMock) as mock_discover:
            mock_discover.return_value = []
            await discover_all(force_refresh=True)
            assert mock_discover.call_count > 0

        mod._cache.clear()


# ── get_interpreter_version ───────────────────────────────────────────────


class TestGetInterpreterVersion:
    @pytest.mark.asyncio
    async def test_returns_version(self):
        """Should extract version from mocked subprocess output."""
        import backend.runtimes as mod

        async def mock_create_subprocess(*args, **kwargs):
            proc = MagicMock()
            future = asyncio.Future()
            future.set_result((b"Python 3.12.2\n", b""))
            proc.communicate = MagicMock(return_value=future)
            return proc

        import asyncio
        with patch("asyncio.create_subprocess_exec", side_effect=mock_create_subprocess):
            version = await get_interpreter_version("/usr/bin/python3", "python")
            assert version == "3.12.2"

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_type(self):
        version = await get_interpreter_version("/usr/bin/unknown", "nonexistent")
        assert version is None
