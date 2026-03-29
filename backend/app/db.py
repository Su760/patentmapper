"""
Supabase async client — singleton pattern via FastAPI dependency.
"""
from supabase._async.client import AsyncClient, create_client

from app.core.config import settings

_supabase_client: AsyncClient | None = None


async def get_supabase() -> AsyncClient:
    """FastAPI dependency that returns a shared AsyncClient instance."""
    global _supabase_client
    if _supabase_client is None:
        _supabase_client = await create_client(
            settings.supabase_url,
            settings.supabase_service_key,
        )
    return _supabase_client
