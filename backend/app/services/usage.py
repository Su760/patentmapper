"""Reserve usage atomically in Postgres before any provider-backed operation."""
from typing import Literal

from fastapi import HTTPException
from supabase import AsyncClient

from app.core.config import settings


async def usage_status(supabase: AsyncClient, user_id: str) -> dict:
    """Read the same ledger/window/plan definition used inside admission's lock."""
    window_seconds = settings.quota_window_days * 24 * 60 * 60
    try:
        result = await supabase.rpc("paid_usage_snapshot", {
            "p_user_id": user_id, "p_window_seconds": window_seconds,
        }).execute()
        data = result.data
        if data["plan"] not in ("free", "pro") or data["window_seconds"] != window_seconds:
            raise ValueError("Invalid usage snapshot")
        usage = {}
        for operation in ("job", "claims", "ideation"):
            used = data["used"][operation]
            if type(used) is not int or used < 0:
                raise ValueError("Invalid reservation count")
            limit = getattr(settings, f"{data['plan']}_{operation}_limit")
            usage[operation] = {"used": used, "limit": limit, "remaining": max(0, limit - used)}
        return {"plan": data["plan"], "usage": usage, "window_seconds": window_seconds,
                "as_of": data["as_of"]}
    except Exception:
        raise HTTPException(503, "Usage status unavailable. Reload to retry; your allowance has not been reset.") from None


async def reserve_usage(
    supabase: AsyncClient, user_id: str, operation: Literal["job", "claims", "ideation"],
    search_id: str | None = None,
) -> None:
    try:
        result = await supabase.rpc("reserve_paid_operation", {
            "p_user_id": user_id,
            "p_operation": operation,
            "p_free_limit": getattr(settings, f"free_{operation}_limit"),
            "p_pro_limit": getattr(settings, f"pro_{operation}_limit"),
            "p_global_limit": settings.global_operation_limit,
            "p_window_seconds": settings.quota_window_days * 24 * 60 * 60,
            "p_search_id": search_id,
        }).execute()
    except Exception:
        raise HTTPException(503, "Usage store unavailable; no paid work started") from None
    if result.data == "user_limit":
        raise HTTPException(402, detail={
            "error": "limit_reached",
            "message": "Your usage limit for this operation has been reached. Check your plan or try again after the rolling usage window.",
            "upgrade_url": "/pricing",
        })
    if result.data == "global_limit":
        raise HTTPException(429, "Service usage budget reached; try again later")
    if result.data != "allowed":
        # Missing RPC/malformed responses must never be interpreted as admission.
        raise HTTPException(503, "Usage store unavailable; no paid work started")
