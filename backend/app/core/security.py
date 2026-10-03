"""Shared server-verified credentials and job authorization; no UUID guest access."""
from typing import Any, Optional
from uuid import UUID

from fastapi import Depends, Header, HTTPException
from supabase import AsyncClient

from app.db import get_supabase


def require_bearer(authorization: Optional[str] = Header(default=None)) -> str:
    parts = authorization.split() if authorization else []
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})
    return parts[1]


async def validate_user(authorization: Optional[str], supabase: AsyncClient) -> Any:
    token = require_bearer(authorization)
    try:
        response = await supabase.auth.get_user(token)
        user = response.user if response else None
        if user is None or not user.id:
            raise ValueError("Missing verified user")
        UUID(str(user.id))
    except Exception:
        # Never fall through to an anonymous identity, including on Auth outages.
        raise HTTPException(401, "Invalid or expired access token", headers={"WWW-Authenticate": "Bearer"}) from None
    return user


async def require_user(
    authorization: Optional[str] = Header(default=None),
    supabase: AsyncClient = Depends(get_supabase),
) -> Any:
    return await validate_user(authorization, supabase)


async def owned_job(
    search_id: UUID,
    user: Any = Depends(require_user),
    supabase: AsyncClient = Depends(get_supabase),
) -> dict[str, Any]:
    # The server client bypasses RLS: the explicit owner filter is mandatory.
    # Using a list query also keeps nonexistent, foreign, and ownerless IDs identical.
    try:
        result = await supabase.table("searches").select("*").eq(
            "id", str(search_id)
        ).eq("user_id", str(user.id)).limit(1).execute()
    except Exception:
        raise HTTPException(503, "Job store unavailable") from None
    if not result.data:
        raise HTTPException(404, "Job not found")
    return result.data[0]
