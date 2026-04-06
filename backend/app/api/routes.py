"""
API Routes
POST /jobs  — create a new patent landscape search job
GET  /jobs/{job_id} — poll job status
"""
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from groq import AsyncGroq
from pydantic import BaseModel
from supabase import AsyncClient

from app.agents.graph import build_graph
from app.agents.state import LandscapeState
from app.core.config import settings
from app.db import get_supabase

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Request / Response models ──────────────────────────────────────────────────


class JobRequest(BaseModel):
    invention_idea: str
    jurisdiction: str = "all"


class JobCreatedResponse(BaseModel):
    job_id: str
    status: str = "processing"


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    current_step: Optional[str] = None
    error_message: Optional[str] = None


class IdeateRequest(BaseModel):
    white_space_title: str
    white_space_description: str


# ── Background task ────────────────────────────────────────────────────────────


async def _run_graph(search_id: str, invention_idea: str, jurisdiction: str, supabase: AsyncClient) -> None:
    """Run the full LangGraph pipeline in the background."""
    initial_state: LandscapeState = {
        "search_id": search_id,
        "invention_idea": invention_idea,
        "jurisdiction": jurisdiction,
        "search_queries": [],
        "raw_patents": [],
        "deduped_patents": [],
        "clusters": [],
        "white_space_analysis": "",
        "final_report": "",
        "errors": [],
    }

    try:
        graph = build_graph(supabase)
        final_state: LandscapeState = await graph.ainvoke(initial_state)

        # Persist results to search_results table
        await supabase.table("search_results").insert(
            {
                "search_id": search_id,
                "clusters": final_state["clusters"],
                "white_space_analysis": final_state["white_space_analysis"],
                "citation_links": final_state.get("citation_links", []),
            }
        ).execute()

        # Persist individual patents
        if final_state["deduped_patents"]:
            patent_rows = [
                {
                    "search_id": search_id,
                    "patent_id": p.get("patent_id"),
                    "title": p.get("title"),
                    "abstract": p.get("abstract"),
                    "assignee": p.get("assignee"),
                    "url": p.get("url"),
                }
                for p in final_state["deduped_patents"]
            ]
            await supabase.table("patents").insert(patent_rows).execute()

        await supabase.table("searches").update(
            {"status": "completed", "current_step": "done"}
        ).eq("id", search_id).execute()

        logger.info("[routes] job %s completed", search_id)

    except Exception as exc:
        logger.exception("[routes] job %s failed: %s", search_id, exc)
        error_str = str(exc).lower()
        if "429" in error_str or "rate limit" in error_str:
            friendly = "Patent database temporarily unavailable. Please try again in a few minutes."
        elif any(kw in error_str for kw in ("groq", "llm", "json")):
            friendly = "AI analysis failed. Please try again — this sometimes happens with unusual invention descriptions."
        elif any(kw in error_str for kw in ("supabase", "database")):
            friendly = "Database error. Please try again."
        else:
            friendly = "Analysis failed. Please try again."
        await supabase.table("searches").update(
            {"status": "failed", "error_message": friendly}
        ).eq("id", search_id).execute()


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.post("/jobs", response_model=JobCreatedResponse, status_code=202)
async def create_job(
    body: JobRequest,
    background_tasks: BackgroundTasks,
    authorization: Optional[str] = Header(default=None),
    supabase: AsyncClient = Depends(get_supabase),
) -> JobCreatedResponse:
    """Create a new patent landscape search job. Returns immediately with a job_id."""
    user_id: Optional[str] = None
    if authorization and authorization.startswith("Bearer "):
        jwt = authorization.removeprefix("Bearer ")
        try:
            resp = await supabase.auth.get_user(jwt)
            user_id = resp.user.id if resp.user else None
        except Exception:
            pass

    # Usage limit check for authenticated users (anonymous = unlimited)
    if user_id is not None:
        try:
            sub_result = (
                await supabase.table("subscriptions")
                .select("plan, status")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            sub_data = sub_result.data[0] if sub_result.data else None
            is_pro = (
                sub_data is not None
                and sub_data.get("plan") == "pro"
                and sub_data.get("status") == "active"
            )
            if not is_pro:
                since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
                count_result = (
                    await supabase.table("searches")
                    .select("id", count="exact")
                    .eq("user_id", user_id)
                    .gte("created_at", since)
                    .execute()
                )
                if (count_result.count or 0) >= 3:
                    raise HTTPException(
                        status_code=402,
                        detail={
                            "error": "limit_reached",
                            "message": "You've used your 3 free analyses this month. Upgrade to Pro for unlimited searches.",
                            "upgrade_url": "/pricing",
                        },
                    )
        except HTTPException:
            raise  # re-raise the 402, don't swallow it
        except Exception as e:
            logger.warning("[routes] usage check failed, allowing job: %s", e)
            # fail open — if we can't check limits, let the job run

    search_id = str(uuid.uuid4())

    await supabase.table("searches").insert(
        {
            "id": search_id,
            "invention_idea": body.invention_idea,
            "user_id": user_id,
            "status": "processing",
            "current_step": "queued",
        }
    ).execute()

    background_tasks.add_task(_run_graph, search_id, body.invention_idea, body.jurisdiction, supabase)

    logger.info("[routes] created job %s", search_id)
    return JobCreatedResponse(job_id=search_id)


@router.post("/jobs/{search_id}/ideate")
async def ideate_white_space(
    search_id: str,
    body: IdeateRequest,
) -> Dict[str, Any]:
    """Generate a concrete invention idea for a white space opportunity using Groq."""
    prompt = (
        "You are a patent strategist. Given this white space opportunity "
        "in a patent landscape, generate ONE concrete invention idea that fills this gap. "
        "Be specific — describe the mechanism, key differentiators, and why it avoids existing prior art.\n\n"
        f"White space: {body.white_space_title}\n"
        f"Description: {body.white_space_description}\n\n"
        "Respond in this JSON format:\n"
        "{\n"
        '  "invention_name": "...",\n'
        '  "one_liner": "...",\n'
        '  "mechanism": "...",\n'
        '  "key_differentiators": ["...", "...", "..."],\n'
        '  "why_novel": "..."\n'
        "}\n"
        "Return ONLY valid JSON, no markdown."
    )
    try:
        client = AsyncGroq(api_key=settings.groq_api_key)
        response = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=600,
        )
        idea = json.loads(response.choices[0].message.content)
        return idea
    except Exception as e:
        logger.error("[ideate] Groq error for search %s: %s", search_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job(
    job_id: str,
    supabase: AsyncClient = Depends(get_supabase),
) -> JobStatusResponse:
    """Poll the status of a patent landscape search job."""
    result = await supabase.table("searches").select("*").eq("id", job_id).single().execute()

    if not result.data:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    row = result.data
    return JobStatusResponse(
        job_id=job_id,
        status=row["status"],
        current_step=row.get("current_step"),
        error_message=row.get("error_message"),
    )
