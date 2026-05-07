"""Tests for backend.api.scripts pure helpers."""

from backend.api.scripts import find_running_run
from backend.models import Run


def _run(run_id: int, status: str) -> Run:
    """Construct a Run instance for testing (not persisted)."""
    return Run(id=run_id, script_id=1, status=status)


def test_find_running_run_returns_run_when_status_running_and_tracked():
    runs = [_run(10, "success"), _run(11, "running")]
    running_processes = {11: object()}
    result = find_running_run(runs, running_processes)
    assert result is not None
    assert result.id == 11


def test_find_running_run_returns_none_when_status_running_but_not_tracked():
    runs = [_run(11, "running")]
    running_processes = {}
    assert find_running_run(runs, running_processes) is None


def test_find_running_run_returns_none_when_no_running_runs():
    runs = [_run(10, "success"), _run(11, "failed")]
    running_processes = {99: object()}
    assert find_running_run(runs, running_processes) is None


def test_find_running_run_returns_none_for_empty_runs():
    assert find_running_run([], {}) is None
