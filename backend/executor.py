"""Script execution logic with subprocess management."""

import asyncio
import os
import platform
import shutil
import signal
from datetime import datetime
from typing import Optional, Dict, Any, AsyncGenerator, List
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Script, Run, Schedule
from .database import async_session
from .config import get_local_now


# Track running processes for kill functionality
running_processes: Dict[int, asyncio.subprocess.Process] = {}

# Default interpreters for each script type (platform-aware)
DEFAULT_INTERPRETERS = {
    "python": ["python"] if platform.system() == "Windows" else ["python3"],
    "bash": ["bash"],
    "sh": ["sh"],
    "zsh": ["zsh"],
    "node": ["node"],
    "ruby": ["ruby"],
    "perl": ["perl"],
    "php": ["php"],
    "go": ["go", "run"],
    "r": ["Rscript"],
    "julia": ["julia"],
    "swift": ["swift"],
    "deno": ["deno", "run"],
    "lua": ["lua"],
    "java": ["java"],  # Java 11+ single-file source execution
    "powershell": ["pwsh"],
    "executable": [],  # Run directly
    "other": [],  # Requires custom interpreter
}

# File extension to script type mapping
EXTENSION_TO_TYPE = {
    ".py": "python",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "zsh",
    ".js": "node",
    ".mjs": "node",
    ".rb": "ruby",
    ".pl": "perl",
    ".php": "php",
    ".go": "go",
    ".r": "r",
    ".R": "r",
    ".jl": "julia",
    ".swift": "swift",
    ".ts": "deno",
    ".lua": "lua",
    ".java": "java",
    ".ps1": "powershell",
}


def get_script_type_from_extension(path: str) -> str:
    """Detect script type from file extension."""
    ext = Path(path).suffix
    # Try exact match first (for case-sensitive like .R), then lowercase
    return EXTENSION_TO_TYPE.get(ext) or EXTENSION_TO_TYPE.get(ext.lower(), "other")


def build_command(script: Script) -> List[str]:
    """Build the command array for executing a script."""
    script_type = script.script_type or "python"
    path = script.path

    # If custom interpreter is specified, use it
    if script.interpreter_path:
        cmd = [script.interpreter_path, path]
    elif script_type == "python" and getattr(script, 'venv_path', None):
        venv_path = Path(script.venv_path)
        if platform.system() == "Windows":
            venv_python = str(venv_path / "Scripts" / "python.exe")
        else:
            venv_python = str(venv_path / "bin" / "python3")
            if not Path(venv_python).exists():
                venv_python = str(venv_path / "bin" / "python")
        cmd = [venv_python, path]
    elif script_type == "executable":
        # Run directly as executable
        cmd = [path]
    elif script_type in DEFAULT_INTERPRETERS:
        interpreter = DEFAULT_INTERPRETERS[script_type]
        if interpreter:
            cmd = interpreter + [path]
        else:
            cmd = [path]
    else:
        # Fallback: try to run directly
        cmd = [path]

    # Add arguments
    if script.args:
        cmd.extend(script.args.split())

    return cmd


def validate_script(script: Script) -> List[str]:
    """Validate script configuration. Returns list of issues."""
    issues = []

    # Check script file exists
    if not Path(script.path).exists():
        issues.append(f"Script file not found: {script.path}")
    elif script.script_type == "executable":
        # Check if executable
        if not os.access(script.path, os.X_OK):
            issues.append(f"File is not executable: {script.path}")

    # Check interpreter if specified
    if script.interpreter_path:
        if not Path(script.interpreter_path).exists():
            if not shutil.which(script.interpreter_path):
                issues.append(f"Interpreter not found: {script.interpreter_path}")
    elif script.script_type not in ["executable", "other"]:
        # Check default interpreter
        default = DEFAULT_INTERPRETERS.get(script.script_type, [])
        if default:
            interpreter = default[0]
            if not shutil.which(interpreter):
                issues.append(f"Default interpreter not found: {interpreter}")

    # Check virtual environment
    if getattr(script, 'venv_path', None):
        venv_path = Path(script.venv_path)
        if not venv_path.exists():
            issues.append(f"Virtual environment not found: {script.venv_path}")
        elif script.script_type == "python":
            if platform.system() == "Windows":
                venv_python = venv_path / "Scripts" / "python.exe"
            else:
                venv_python = venv_path / "bin" / "python3"
                if not venv_python.exists():
                    venv_python = venv_path / "bin" / "python"
            if not venv_python.exists():
                issues.append(f"Python binary not found in virtual environment: {venv_path}")

    # Check working directory
    if script.working_directory and not Path(script.working_directory).exists():
        issues.append(f"Working directory not found: {script.working_directory}")

    return issues


async def execute_script(
    script_id: int,
    schedule_id: Optional[int] = None,
    trigger_type: str = "manual"
) -> int:
    """
    Execute a script and record the run.

    Returns the run ID.
    """
    async with async_session() as session:
        # Get the script
        result = await session.execute(
            select(Script).where(Script.id == script_id)
        )
        script = result.scalar_one_or_none()
        if not script:
            raise ValueError(f"Script {script_id} not found")

        # Create run record
        run = Run(
            script_id=script_id,
            schedule_id=schedule_id,
            started_at=get_local_now(),
            status="running",
            trigger_type=trigger_type
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        run_id = run.id

    # Execute in background
    asyncio.create_task(_run_script_process(script_id, run_id))
    return run_id


async def _run_script_process(script_id: int, run_id: int) -> None:
    """Execute the script process and update the run record."""
    async with async_session() as session:
        # Get fresh script data
        result = await session.execute(
            select(Script).where(Script.id == script_id)
        )
        script = result.scalar_one_or_none()
        if not script:
            return

        result = await session.execute(
            select(Run).where(Run.id == run_id)
        )
        run = result.scalar_one_or_none()
        if not run:
            return

        stdout_data = []
        stderr_data = []
        process = None
        retry_attempt = 0
        max_retries = script.retry_count

        while retry_attempt <= max_retries:
            try:
                # Prepare environment
                env = os.environ.copy()
                # Remove venv-specific variables that can interfere with other Python versions
                env.pop('__PYVENV_LAUNCHER__', None)
                env.pop('VIRTUAL_ENV', None)

                # Set up venv environment if configured
                if getattr(script, 'venv_path', None) and script.script_type == "python":
                    venv_p = Path(script.venv_path)
                    venv_bin = venv_p / ("Scripts" if platform.system() == "Windows" else "bin")
                    if venv_bin.exists():
                        env["VIRTUAL_ENV"] = str(venv_p)
                        env["PATH"] = str(venv_bin) + os.pathsep + env.get("PATH", "")
                        env.pop("PYTHONHOME", None)

                if getattr(script, 'venv_path', None) and script.script_type == "node":
                    node_modules = Path(script.venv_path) / "node_modules"
                    if node_modules.exists():
                        env["NODE_PATH"] = str(node_modules)

                if script.env_vars:
                    env.update(script.env_vars)

                # Build command based on script type
                cmd = build_command(script)

                # Prepare working directory
                cwd = script.working_directory or str(Path(script.path).parent)

                # Validate script before running
                issues = validate_script(script)
                if issues:
                    run.status = "failed"
                    run.stderr = "Validation failed:\n" + "\n".join(f"- {i}" for i in issues)
                    run.ended_at = get_local_now()
                    run.duration = 0
                    await session.commit()
                    return

                # Create subprocess
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                    env=env,
                )

                # Track the process
                running_processes[run_id] = process

                try:
                    # Wait with timeout
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(),
                        timeout=script.timeout
                    )

                    stdout_data.append(stdout.decode("utf-8", errors="replace"))
                    stderr_data.append(stderr.decode("utf-8", errors="replace"))

                    if process.returncode == 0:
                        run.status = "success"
                        break  # Success, no need to retry
                    else:
                        run.status = "failed"
                        run.exit_code = process.returncode
                        if retry_attempt < max_retries:
                            stderr_data.append(
                                f"\n--- Retry {retry_attempt + 1}/{max_retries} "
                                f"after {script.retry_delay}s ---\n"
                            )
                            await asyncio.sleep(script.retry_delay)
                            retry_attempt += 1
                            continue
                        break

                except asyncio.TimeoutError:
                    # Kill the process
                    process.kill()
                    await process.wait()
                    run.status = "timeout"
                    stderr_data.append(
                        f"\nProcess killed after {script.timeout}s timeout"
                    )
                    break

            except asyncio.CancelledError:
                if process:
                    process.kill()
                    await process.wait()
                run.status = "killed"
                break

            except Exception as e:
                stderr_data.append(f"\nExecution error: {str(e)}")
                run.status = "failed"
                if retry_attempt < max_retries:
                    await asyncio.sleep(script.retry_delay)
                    retry_attempt += 1
                    continue
                break

            finally:
                # Remove from tracking
                running_processes.pop(run_id, None)

        # Update run record
        run.ended_at = get_local_now()
        run.duration = (run.ended_at - run.started_at).total_seconds()
        run.stdout = "".join(stdout_data)
        run.stderr = "".join(stderr_data)
        if process:
            run.exit_code = process.returncode

        await session.commit()

        # Trigger notifications if needed
        from .notifications import send_run_notification
        await send_run_notification(run_id)


async def kill_script(run_id: int) -> bool:
    """Kill a running script by run ID."""
    process = running_processes.get(run_id)
    if process:
        try:
            process.terminate()
            # Give it a moment to terminate gracefully
            await asyncio.sleep(0.5)
            if process.returncode is None:
                process.kill()
            return True
        except ProcessLookupError:
            pass
    return False


async def get_running_scripts() -> list[int]:
    """Get list of currently running run IDs."""
    return list(running_processes.keys())


async def stream_output(run_id: int) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Stream output from a running script.

    Yields dict with 'stdout', 'stderr', 'status' keys.
    """
    async with async_session() as session:
        last_stdout_len = 0
        last_stderr_len = 0

        while True:
            result = await session.execute(
                select(Run).where(Run.id == run_id)
            )
            run = result.scalar_one_or_none()

            if not run:
                yield {"error": "Run not found", "status": "error"}
                break

            # Get new output since last check
            stdout = run.stdout or ""
            stderr = run.stderr or ""

            new_stdout = stdout[last_stdout_len:]
            new_stderr = stderr[last_stderr_len:]

            last_stdout_len = len(stdout)
            last_stderr_len = len(stderr)

            yield {
                "stdout": new_stdout,
                "stderr": new_stderr,
                "status": run.status,
                "exit_code": run.exit_code,
            }

            if run.status != "running":
                break

            await asyncio.sleep(0.5)
            await session.refresh(run)
