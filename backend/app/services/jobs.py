"""Durable job admission and service-only lease RPCs. No providers run here."""

import asyncio
from typing import Any
from uuid import UUID
from supabase import AsyncClient
from fastapi import HTTPException
from app.core.config import settings


async def rpc(db: AsyncClient, name: str, params: dict[str, Any]) -> Any:
    response = await asyncio.wait_for(
        db.rpc(name, params).execute(), settings.worker_rpc_timeout_seconds
    )
    return response.data


async def admit_job(
    db: AsyncClient, user_id: str, key: UUID, idea: str, jurisdiction: str
) -> dict[str, Any]:
    try:
        data = await rpc(
            db,
            "admit_analysis",
            {
                "p_user_id": user_id,
                "p_submission_key": str(key),
                "p_payload": {"invention_idea": idea, "jurisdiction": jurisdiction},
                "p_execution_inputs": {
                    "version": 2,
                    "groq_model": settings.groq_model,
                    "mock_mode": settings.mock_mode,
                    "serpapi_enabled": settings.serpapi_enabled,
                },
                "p_free_limit": settings.free_job_limit,
                "p_pro_limit": settings.pro_job_limit,
                "p_global_limit": settings.global_operation_limit,
                "p_window_seconds": settings.quota_window_days * 86400,
            },
        )
        outcome = data["outcome"]
        if outcome == "accepted" and data.get("job_id") and data.get("status"):
            return data
        if outcome == "conflict":
            raise HTTPException(
                409,
                "This submission key belongs to different inputs. Restore the original inputs or explicitly start a fresh analysis.",
            )
        if outcome == "user_limit":
            raise HTTPException(
                402,
                {
                    "error": "limit_reached",
                    "message": "Your analysis allowance has been reached. Check your rolling usage window.",
                },
            )
        if outcome == "global_limit":
            raise HTTPException(429, "Service usage budget reached; try again later.")
        raise ValueError("Unconfirmed admission")
    except HTTPException:
        raise
    except Exception:
        # A transport timeout can happen AFTER commit. Never assert no job exists.
        raise HTTPException(
            503,
            "Submission could not be confirmed. Retry the same inputs and submission key to recover the job without another reservation.",
        ) from None


class LostLease(RuntimeError):
    pass


class Lease:
    def __init__(self, db: AsyncClient, job: dict[str, Any]) -> None:
        self.db = db
        self.params = {"p_search_id": job["search_id"], "p_token": job["lease_token"]}

    async def call(self, name: str, **params: Any) -> None:
        try:
            ok = await rpc(self.db, name, {**self.params, **params})
        except Exception as exc:
            raise LostLease("Lease/store unavailable; stop execution") from exc
        if ok is not True:
            raise LostLease("Worker no longer owns a live lease")

    async def heartbeat(self) -> None:
        await self.call(
            "heartbeat_analysis", p_lease_seconds=settings.worker_lease_seconds
        )
