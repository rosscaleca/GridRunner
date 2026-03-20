"""Tests for backend.executor pure functions."""

import platform
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.executor import (
    build_command,
    get_script_type_from_extension,
    validate_script,
    DEFAULT_INTERPRETERS,
    EXTENSION_TO_TYPE,
)
from backend.models import Script


# ── get_script_type_from_extension ──────────────────────────────────────────


class TestGetScriptTypeFromExtension:
    def test_python(self):
        assert get_script_type_from_extension("/foo/bar.py") == "python"

    def test_bash(self):
        assert get_script_type_from_extension("script.sh") == "bash"

    def test_node(self):
        assert get_script_type_from_extension("app.js") == "node"

    def test_unknown_extension(self):
        assert get_script_type_from_extension("data.csv") == "other"

    def test_no_extension(self):
        assert get_script_type_from_extension("/usr/local/bin/myscript") == "other"

    def test_powershell(self):
        assert get_script_type_from_extension("setup.ps1") == "powershell"


# ── build_command ───────────────────────────────────────────────────────────


class TestBuildCommand:
    def test_python_default(self, sample_script):
        cmd = build_command(sample_script)
        expected_interp = "python" if platform.system() == "Windows" else "python3"
        assert cmd == [expected_interp, "/tmp/test_script.py"]

    def test_bash_default(self, sample_bash_script):
        cmd = build_command(sample_bash_script)
        assert cmd == ["bash", "/tmp/test_script.sh"]

    def test_executable(self, sample_script):
        sample_script.script_type = "executable"
        cmd = build_command(sample_script)
        assert cmd == ["/tmp/test_script.py"]

    def test_custom_interpreter(self, sample_script):
        sample_script.interpreter_path = "/usr/local/bin/python3.12"
        cmd = build_command(sample_script)
        assert cmd == ["/usr/local/bin/python3.12", "/tmp/test_script.py"]

    def test_with_args(self, sample_script):
        sample_script.args = "--verbose --count 5"
        cmd = build_command(sample_script)
        expected_interp = "python" if platform.system() == "Windows" else "python3"
        assert cmd == [expected_interp, "/tmp/test_script.py", "--verbose", "--count", "5"]


# ── validate_script ────────────────────────────────────────────────────────


class TestValidateScript:
    def test_missing_file(self, sample_script):
        sample_script.path = "/nonexistent/path/script.py"
        issues = validate_script(sample_script)
        assert any("not found" in i for i in issues)

    def test_valid_file(self, sample_script, tmp_path):
        script_file = tmp_path / "ok.py"
        script_file.write_text("print('hi')")
        sample_script.path = str(script_file)
        issues = validate_script(sample_script)
        # No file-not-found issue (interpreter may still be missing in CI)
        assert not any("Script file not found" in i for i in issues)

    def test_bad_interpreter(self, sample_script, tmp_path):
        script_file = tmp_path / "ok.py"
        script_file.write_text("print('hi')")
        sample_script.path = str(script_file)
        sample_script.interpreter_path = "/nonexistent/interpreter"
        issues = validate_script(sample_script)
        assert any("Interpreter not found" in i for i in issues)

    def test_bad_working_directory(self, sample_script, tmp_path):
        script_file = tmp_path / "ok.py"
        script_file.write_text("print('hi')")
        sample_script.path = str(script_file)
        sample_script.working_directory = "/nonexistent/dir"
        issues = validate_script(sample_script)
        assert any("Working directory not found" in i for i in issues)


# ── New script types ─────────────────────────────────────────────────────


class TestBuildCommandNewTypes:
    def _make_script(self, script_type, path="/tmp/test_file"):
        return Script(
            id=10, name="Test", path=path, script_type=script_type,
            timeout=60, retry_count=0, retry_delay=10,
        )

    def test_go(self):
        cmd = build_command(self._make_script("go", "/tmp/main.go"))
        assert cmd == ["go", "run", "/tmp/main.go"]

    def test_deno(self):
        cmd = build_command(self._make_script("deno", "/tmp/app.ts"))
        assert cmd == ["deno", "run", "/tmp/app.ts"]

    def test_julia(self):
        cmd = build_command(self._make_script("julia", "/tmp/script.jl"))
        assert cmd == ["julia", "/tmp/script.jl"]

    def test_r(self):
        cmd = build_command(self._make_script("r", "/tmp/analysis.r"))
        assert cmd == ["Rscript", "/tmp/analysis.r"]

    def test_lua(self):
        cmd = build_command(self._make_script("lua", "/tmp/script.lua"))
        assert cmd == ["lua", "/tmp/script.lua"]

    def test_swift(self):
        cmd = build_command(self._make_script("swift", "/tmp/main.swift"))
        assert cmd == ["swift", "/tmp/main.swift"]

    def test_java(self):
        cmd = build_command(self._make_script("java", "/tmp/Main.java"))
        assert cmd == ["java", "/tmp/Main.java"]


class TestBuildCommandWithVenv:
    def test_python_with_venv(self, sample_python_venv_script):
        cmd = build_command(sample_python_venv_script)
        venv_python = str(Path(sample_python_venv_script.venv_path) / "bin" / "python3")
        assert cmd == [venv_python, "/tmp/test_script.py"]

    def test_interpreter_path_takes_precedence(self, sample_python_venv_script):
        sample_python_venv_script.interpreter_path = "/usr/local/bin/python3.12"
        cmd = build_command(sample_python_venv_script)
        assert cmd == ["/usr/local/bin/python3.12", "/tmp/test_script.py"]

    def test_non_python_ignores_venv(self):
        script = Script(
            id=10, name="Bash", path="/tmp/test.sh", script_type="bash",
            timeout=60, retry_count=0, retry_delay=10, venv_path="/tmp/venv",
        )
        cmd = build_command(script)
        assert cmd == ["bash", "/tmp/test.sh"]


class TestValidateScriptVenv:
    def test_missing_venv(self, sample_script):
        sample_script.venv_path = "/nonexistent/venv"
        issues = validate_script(sample_script)
        assert any("Virtual environment not found" in i for i in issues)

    def test_valid_venv(self, sample_python_venv_script, tmp_path):
        script_file = tmp_path / "ok.py"
        script_file.write_text("print('hi')")
        sample_python_venv_script.path = str(script_file)
        issues = validate_script(sample_python_venv_script)
        assert not any("Virtual environment not found" in i for i in issues)
        assert not any("Python binary not found" in i for i in issues)

    def test_venv_without_python(self, sample_script, tmp_path):
        venv_dir = tmp_path / "empty_venv"
        venv_dir.mkdir()
        (venv_dir / "bin").mkdir()
        # No python binary inside
        sample_script.venv_path = str(venv_dir)
        script_file = tmp_path / "ok.py"
        script_file.write_text("print('hi')")
        sample_script.path = str(script_file)
        issues = validate_script(sample_script)
        assert any("Python binary not found" in i for i in issues)


class TestGetScriptTypeNewExtensions:
    def test_go(self):
        assert get_script_type_from_extension("main.go") == "go"

    def test_julia(self):
        assert get_script_type_from_extension("script.jl") == "julia"

    def test_r_lowercase(self):
        assert get_script_type_from_extension("analysis.r") == "r"

    def test_r_uppercase(self):
        assert get_script_type_from_extension("analysis.R") == "r"

    def test_typescript_deno(self):
        assert get_script_type_from_extension("app.ts") == "deno"

    def test_lua(self):
        assert get_script_type_from_extension("script.lua") == "lua"

    def test_swift(self):
        assert get_script_type_from_extension("main.swift") == "swift"

    def test_java(self):
        assert get_script_type_from_extension("Main.java") == "java"
