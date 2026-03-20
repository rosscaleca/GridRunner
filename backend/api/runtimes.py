"""Runtime discovery API endpoints."""

from typing import Optional

from fastapi import APIRouter, Depends, Request

from ..runtimes import discover_all, discover_for_type
from .auth import require_auth

router = APIRouter()


@router.get("")
async def list_runtimes(
    request: Request,
    script_type: Optional[str] = None,
    _: None = Depends(require_auth),
):
    """List all discovered runtimes, optionally filtered by script type."""
    if script_type:
        runtimes = await discover_for_type(script_type)
        return {
            script_type: [
                {
                    "script_type": r.script_type,
                    "path": r.path,
                    "version": r.version,
                    "display_name": r.display_name,
                    "is_default": r.is_default,
                    "source": r.source,
                }
                for r in runtimes
            ]
        }

    all_runtimes = await discover_all()
    result = {}
    for st, runtimes in all_runtimes.items():
        result[st] = [
            {
                "script_type": r.script_type,
                "path": r.path,
                "version": r.version,
                "display_name": r.display_name,
                "is_default": r.is_default,
                "source": r.source,
            }
            for r in runtimes
        ]
    return result


@router.post("/refresh")
async def refresh_runtimes(
    request: Request,
    _: None = Depends(require_auth),
):
    """Force re-scan of all runtimes, clearing the cache."""
    all_runtimes = await discover_all(force_refresh=True)
    count = sum(len(v) for v in all_runtimes.values())
    return {"message": f"Discovered {count} runtimes across {len(all_runtimes)} types"}
