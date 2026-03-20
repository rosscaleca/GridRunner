"""Python environment management API endpoints."""

import asyncio
import json
import platform
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .auth import require_auth

router = APIRouter()

VENV_NAMES = ["venv", ".venv", "env"]


def _find_pip(venv_path: Path) -> Path | None:
    """Locate pip inside a venv."""
    if platform.system() == "Windows":
        pip = venv_path / "Scripts" / "pip.exe"
    else:
        pip = venv_path / "bin" / "pip"
    return pip if pip.exists() else None


def _find_python(venv_path: Path) -> Path | None:
    """Locate python inside a venv."""
    if platform.system() == "Windows":
        py = venv_path / "Scripts" / "python.exe"
        return py if py.exists() else None
    for name in ["python3", "python"]:
        py = venv_path / "bin" / name
        if py.exists():
            return py
    return None


async def _get_python_version(python_path: Path) -> str | None:
    """Get version string from a python binary."""
    try:
        proc = await asyncio.create_subprocess_exec(
            str(python_path), "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        output = stdout.decode("utf-8", errors="replace").strip()
        if not output:
            output = stderr.decode("utf-8", errors="replace").strip()
        # "Python 3.12.2" → "3.12.2"
        return output.replace("Python ", "") if output.startswith("Python ") else output
    except (asyncio.TimeoutError, FileNotFoundError, OSError):
        return None


@router.get("/detect")
async def detect_venvs(
    request: Request,
    path: str,
    _: None = Depends(require_auth),
):
    """Detect virtual environments near a script path."""
    script_path = Path(path)
    if script_path.is_file():
        base_dir = script_path.parent
    else:
        base_dir = script_path

    venvs = []
    seen = set()

    # Search current directory and up to 3 parent levels
    search_dirs = [base_dir]
    current = base_dir
    for _ in range(3):
        current = current.parent
        if current == current.parent:
            break
        search_dirs.append(current)

    for search_dir in search_dirs:
        for venv_name in VENV_NAMES:
            candidate = search_dir / venv_name
            resolved = str(candidate.resolve())
            if resolved in seen:
                continue
            if candidate.is_dir():
                python = _find_python(candidate)
                if python:
                    seen.add(resolved)
                    version = await _get_python_version(python)
                    venvs.append({
                        "path": str(candidate),
                        "name": venv_name,
                        "python_version": version,
                    })

    return {"venvs": venvs}


class CreateVenvRequest(BaseModel):
    python_path: str
    venv_path: str


@router.post("/create")
async def create_venv(
    data: CreateVenvRequest,
    request: Request,
    _: None = Depends(require_auth),
):
    """Create a new Python virtual environment."""
    python_path = Path(data.python_path)
    if not python_path.exists():
        raise HTTPException(status_code=400, detail=f"Python not found: {data.python_path}")

    venv_path = Path(data.venv_path)
    if venv_path.exists():
        raise HTTPException(status_code=400, detail=f"Path already exists: {data.venv_path}")

    try:
        proc = await asyncio.create_subprocess_exec(
            str(python_path), "-m", "venv", str(venv_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60.0)

        if proc.returncode != 0:
            error = stderr.decode("utf-8", errors="replace")
            raise HTTPException(status_code=500, detail=f"Failed to create venv: {error}")

        # Get the version of the created venv
        venv_python = _find_python(venv_path)
        version = await _get_python_version(venv_python) if venv_python else None

        return {
            "path": str(venv_path),
            "python_version": version,
            "message": "Virtual environment created successfully",
        }
    except asyncio.TimeoutError:
        raise HTTPException(status_code=500, detail="Venv creation timed out")


@router.get("/packages")
async def list_packages(
    request: Request,
    venv_path: str,
    _: None = Depends(require_auth),
):
    """List installed packages in a virtual environment."""
    pip = _find_pip(Path(venv_path))
    if not pip:
        raise HTTPException(status_code=400, detail="pip not found in the specified virtual environment")

    try:
        proc = await asyncio.create_subprocess_exec(
            str(pip), "list", "--format=json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
        packages = json.loads(stdout.decode("utf-8", errors="replace"))
        return {"packages": packages}
    except (asyncio.TimeoutError, json.JSONDecodeError) as e:
        raise HTTPException(status_code=500, detail=f"Failed to list packages: {str(e)}")


class PackageInstallRequest(BaseModel):
    venv_path: str
    packages: list[str]


@router.post("/packages/install")
async def install_packages(
    data: PackageInstallRequest,
    request: Request,
    _: None = Depends(require_auth),
):
    """Install packages into a virtual environment."""
    pip = _find_pip(Path(data.venv_path))
    if not pip:
        raise HTTPException(status_code=400, detail="pip not found in the specified virtual environment")

    if not data.packages:
        raise HTTPException(status_code=400, detail="No packages specified")

    try:
        proc = await asyncio.create_subprocess_exec(
            str(pip), "install", *data.packages,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120.0)

        if proc.returncode != 0:
            error = stderr.decode("utf-8", errors="replace")
            raise HTTPException(status_code=500, detail=f"pip install failed: {error}")

        return {
            "message": f"Successfully installed: {', '.join(data.packages)}",
            "output": stdout.decode("utf-8", errors="replace"),
        }
    except asyncio.TimeoutError:
        raise HTTPException(status_code=500, detail="Package installation timed out")


class PackageUninstallRequest(BaseModel):
    venv_path: str
    packages: list[str]


@router.post("/packages/uninstall")
async def uninstall_packages(
    data: PackageUninstallRequest,
    request: Request,
    _: None = Depends(require_auth),
):
    """Uninstall packages from a virtual environment."""
    pip = _find_pip(Path(data.venv_path))
    if not pip:
        raise HTTPException(status_code=400, detail="pip not found in the specified virtual environment")

    if not data.packages:
        raise HTTPException(status_code=400, detail="No packages specified")

    try:
        proc = await asyncio.create_subprocess_exec(
            str(pip), "uninstall", "-y", *data.packages,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60.0)

        if proc.returncode != 0:
            error = stderr.decode("utf-8", errors="replace")
            raise HTTPException(status_code=500, detail=f"pip uninstall failed: {error}")

        return {
            "message": f"Successfully uninstalled: {', '.join(data.packages)}",
            "output": stdout.decode("utf-8", errors="replace"),
        }
    except asyncio.TimeoutError:
        raise HTTPException(status_code=500, detail="Package uninstall timed out")
