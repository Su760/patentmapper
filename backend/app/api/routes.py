"""
API Routes
POST /jobs  — create a new patent landscape search job
GET  /jobs/{job_id} — poll job status
"""
import json
import logging
import uuid
from typing import Annotated, Any, Dict, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from groq import AsyncGroq
from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError
from supabase import AsyncClient

from app.agents.graph import build_graph
from app.agents.state import LandscapeState
from app.core.config import settings
from app.core.security import owned_job, require_bearer, require_user
from app.db import get_supabase
from app.services.llm import create_chat_completion
from app.services.usage import reserve_usage

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(require_bearer), Depends(require_user)])


# ── Request / Response models ──────────────────────────────────────────────────


class JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invention_idea: Annotated[str, StringConstraints(
        strip_whitespace=True, min_length=settings.invention_min_chars,
        max_length=settings.invention_max_chars,
    )]
    jurisdiction: Literal["all", "us", "ep", "wo"] = "all"


class JobCreatedResponse(BaseModel):
    job_id: str
    status: str = "processing"


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    current_step: Optional[str] = None
    error_message: Optional[str] = None


class IdeateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    white_space_title: Annotated[str, StringConstraints(
        strip_whitespace=True, min_length=1, max_length=settings.ideation_title_max_chars,
    )]
    white_space_description: Annotated[str, StringConstraints(
        strip_whitespace=True, min_length=1, max_length=settings.ideation_description_max_chars,
    )]


def authenticated_body(model: type[BaseModel]):
    # A body-model parameter makes FastAPI decode JSON before dependencies. Read
    # it here so credentials are verified even when a caller sends malformed JSON.
    async def parse(request: Request, user: Any = Depends(require_user)):
        try:
            payload = await request.json()
        except (ValueError, UnicodeError):
            raise HTTPException(422, "Invalid JSON request body") from None
        try:
            return model.model_validate(payload)
        except ValidationError as exc:
            raise RequestValidationError(exc.errors()) from None
    return parse


def body_schema(model: type[BaseModel]) -> dict:
    return {"requestBody": {"required": True, "content": {
        "application/json": {"schema": model.model_json_schema()},
    }}}


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


@router.post("/jobs", response_model=JobCreatedResponse, status_code=202, openapi_extra=body_schema(JobRequest))
async def create_job(
    body: Annotated[JobRequest, Depends(authenticated_body(JobRequest))],
    background_tasks: BackgroundTasks,
    user: Any = Depends(require_user),
    supabase: AsyncClient = Depends(get_supabase),
) -> JobCreatedResponse:
    """Create a new patent landscape search job. Returns immediately with a job_id."""
    user_id = str(user.id)
    search_id = str(uuid.uuid4())
    await reserve_usage(supabase, user_id, "job", search_id)

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


@router.post("/jobs/{search_id}/ideate", openapi_extra=body_schema(IdeateRequest))
async def ideate_white_space(
    search_id: UUID,
    job: Dict[str, Any] = Depends(owned_job),
    body: IdeateRequest = Depends(authenticated_body(IdeateRequest)),
    supabase: AsyncClient = Depends(get_supabase),
) -> Dict[str, Any]:
    """Generate a concrete invention idea for a white space opportunity using Groq."""
    await reserve_usage(supabase, str(job["user_id"]), "ideation")
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
        response = await create_chat_completion(
            client,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=600,
        )
        idea = json.loads(response.choices[0].message.content)
        return idea
    except Exception as e:
        logger.error("[ideate] Groq error for search %s: %s", search_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jobs/{search_id}/analyze-claims")
async def get_claims_analysis(
    search_id: UUID,
    job: Dict[str, Any] = Depends(owned_job),
    supabase: AsyncClient = Depends(get_supabase),
) -> Dict[str, Any]:
    """Return cached claims analysis if previously generated."""
    result = await supabase.table("search_results").select("claims_analysis").eq("search_id", str(search_id)).execute()
    row = result.data[0] if result.data else None
    return {"claims": row.get("claims_analysis") if row else None}


@router.post("/jobs/{search_id}/analyze-claims")
async def analyze_claims(
    search_id: UUID,
    job: Dict[str, Any] = Depends(owned_job),
    supabase: AsyncClient = Depends(get_supabase),
) -> Dict[str, Any]:
    """Analyze prior art claim overlap for a search's patents using Groq."""
    invention_idea = job["invention_idea"]

    patents_res = await supabase.table("patents").select("patent_id, title, abstract").eq("search_id", str(search_id)).limit(8).execute()
    patents = patents_res.data or []
    if not patents:
        raise HTTPException(status_code=404, detail="No patents found for this search")

    await reserve_usage(supabase, str(job["user_id"]), "claims")

    n = len(patents)
    patents_text = "\n".join(
        f"{p['patent_id']} | {p['title']} | {(p.get('abstract') or '')[:300]}"
        for p in patents
    )

    prompt = (
        f"Invention: {invention_idea}\n\n"
        f"Analyze these {n} patents for claim overlap with the invention. "
        "For each patent, identify what specific technical aspects it likely claims "
        "and whether those claims overlap with the invention.\n\n"
        "Return ONLY a JSON object:\n"
        "{\n"
        '  "claims": [\n'
        "    {\n"
        '      "patent_id": "US123...",\n'
        '      "title": "...",\n'
        '      "likely_claims": ["Claim: a method for...", "Claim: a device comprising..."],\n'
        '      "overlap_level": "high|medium|low|none",\n'
        '      "overlap_explanation": "This patent likely claims X which directly covers Y in your invention...",\n'
        '      "differentiators": "Your invention differs by..."\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        f"Patents:\n{patents_text}\n\n"
        "Return ONLY valid JSON, no markdown."
    )

    try:
        client = AsyncGroq(api_key=settings.groq_api_key)
        response = await create_chat_completion(
            client,
            messages=[
                {"role": "system", "content": "You are a senior patent attorney analyzing prior art."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            max_tokens=1500,
        )
        result = json.loads(response.choices[0].message.content)
        claims = result.get("claims", [])

        await supabase.table("search_results").update({"claims_analysis": claims}).eq("search_id", str(search_id)).execute()

        return {"claims": claims}
    except Exception as e:
        logger.error("[analyze_claims] Groq error for search %s: %s", search_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jobs/{search_id}", response_model=JobStatusResponse)
async def get_job(
    search_id: UUID,
    job: Dict[str, Any] = Depends(owned_job),
) -> JobStatusResponse:
    """Poll the status of a patent landscape search job."""
    row = job
    return JobStatusResponse(
        job_id=str(search_id),
        status=row["status"],
        current_step=row.get("current_step"),
        error_message=row.get("error_message"),
    )
