"""Per-execution settings and fail-closed guards at each paid request boundary."""

from contextvars import ContextVar
from typing import Any
from supabase import AsyncClient
from app.core.config import settings
from app.services.jobs import Lease

execution: ContextVar[tuple[Lease, dict[str, Any]] | None] = ContextVar(
    "analysis_execution", default=None
)


def option(name: str) -> Any:
    current = execution.get()
    return current[1][name] if current else getattr(settings, name)


async def before_paid_call() -> None:
    current = execution.get()
    if current:
        await current[0].heartbeat()


async def update_stage(db: AsyncClient, state: dict[str, Any], step: str) -> None:
    await Lease(db, state).call("stage_analysis", p_step=step)
