"""
API Routes
POST /jobs  — create a new patent landscape search job
GET  /jobs/{job_id} — poll job status
"""
import json
import logging
from typing import Annotated, Any, Dict, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from groq import AsyncGroq
from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError
from supabase import AsyncClient

from app.core.config import settings
from app.core.security import owned_job, require_bearer, require_user
from app.db import get_supabase
from app.services.llm import create_chat_completion
from app.services.usage import reserve_usage
from app.services.jobs import admit_job, rpc

from app.services.evidence import saved_evidence, validate_references, filter_claims

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(require_bearer), Depends(require_user)])


# ── Request / Response models ──────────────────────────────────────────────────


class JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invention_idea: Annotated[str, StringConstraints(
        strip_whitespace=True, min_length=settings.invention_min_chars,
        max_length=settings.invention_max_chars,
    )]
    submission_key: UUID
    jurisdiction: Literal["all", "us", "ep", "wo"] = "all"


class JobCreatedResponse(BaseModel):
    job_id: str
    status: str = "queued"


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


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.post("/jobs", response_model=JobCreatedResponse, status_code=202, openapi_extra=body_schema(JobRequest))
async def create_job(
    body: Annotated[JobRequest, Depends(authenticated_body(JobRequest))],
    user: Any = Depends(require_user),
    supabase: AsyncClient = Depends(get_supabase),
) -> JobCreatedResponse:
    """Create a new patent landscape search job. Returns immediately with a job_id."""
    data = await admit_job(supabase, str(user.id), body.submission_key, body.invention_idea, body.jurisdiction)
    return JobCreatedResponse(job_id=data['job_id'], status=data['status'])


@router.post("/jobs/{search_id}/ideate", openapi_extra=body_schema(IdeateRequest))
async def ideate_white_space(
    search_id: UUID,
    job: Dict[str, Any] = Depends(owned_job),
    body: IdeateRequest = Depends(authenticated_body(IdeateRequest)),
    supabase: AsyncClient = Depends(get_supabase),
) -> Dict[str, Any]:
    """Generate a concrete invention idea for a white space opportunity using Groq."""
    if job["status"] != "completed":
        raise HTTPException(409, "This analysis has no completed evidence for ideation.")
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


@router.get("/jobs/{search_id}/evidence")
async def get_evidence(
    search_id: UUID,
    job: Dict[str, Any] = Depends(owned_job),
    supabase: AsyncClient = Depends(get_supabase),
) -> Dict[str, Any]:
    """Owner-authorized saved data only. No provider calls, quota or regeneration."""
    patents = (await supabase.table("patents").select("patent_id,title,abstract,assignee,url,evidence")
               .eq("search_id", str(search_id)).execute()).data or []
    results = (await supabase.table("search_results").select("clusters,citation_links,evidence_version,requested_jurisdiction,analysis_warnings")
               .eq("search_id", str(search_id)).execute()).data or []
    result = results[0] if results else {}
    clusters, links, warnings = validate_references(result.get("clusters", []), result.get("citation_links", []), patents)
    return {"patents": [saved_evidence(p) for p in patents], "clusters": clusters, "citation_links": links,
            "evidence_version": result.get("evidence_version"),
            "requested_jurisdiction": result.get("requested_jurisdiction"),
            "warnings": list(dict.fromkeys((result.get("analysis_warnings") or []) + warnings))}


@router.get("/jobs/{search_id}/analyze-claims")
async def get_claims_analysis(
    search_id: UUID,
    job: Dict[str, Any] = Depends(owned_job),
    supabase: AsyncClient = Depends(get_supabase),
) -> Dict[str, Any]:
    """Return cached claims analysis if previously generated."""
    result = await supabase.table("search_results").select("claims_analysis").eq("search_id", str(search_id)).execute()
    row = result.data[0] if result.data else None
    cached = row.get("claims_analysis") if row else None
    if cached is None:
        return {"claims": None}
    warnings = []
    if isinstance(cached, dict):
        if type(cached.get("version")) is not int or cached["version"] != 1:
            return {"claims": None, "warnings": ["Unsupported saved overlap version; no generation was requested."]}
        saved_warnings = cached.get("warnings", [])
        if isinstance(saved_warnings, list):
            warnings = [warning for warning in saved_warnings if isinstance(warning, str)]
        if not isinstance(saved_warnings, list) or len(warnings) != len(saved_warnings):
            warnings.append("Excluded malformed saved overlap warnings.")
        cached = cached.get("claims")
    patents = (await supabase.table("patents").select("patent_id,title").eq("search_id", str(search_id)).execute()).data or []
    claims, excluded = filter_claims(cached, patents)
    warnings = list(dict.fromkeys(warnings + excluded))
    return {"claims": claims, **({"warnings": warnings} if warnings else {})}


@router.post("/jobs/{search_id}/analyze-claims")
async def analyze_claims(
    search_id: UUID,
    job: Dict[str, Any] = Depends(owned_job),
    supabase: AsyncClient = Depends(get_supabase),
) -> Dict[str, Any]:
    """Analyze prior art claim overlap for a search's patents using Groq."""
    if job["status"] != "completed":
        raise HTTPException(409, "This analysis has no completed evidence for claims generation.")
    invention_idea = job["invention_idea"]

    patents_res = await supabase.table("patents").select("patent_id, title, abstract, evidence").eq("search_id", str(search_id)).limit(8).execute()
    patents = patents_res.data or []
    if not patents:
        raise HTTPException(status_code=404, detail="No patents found for this search")

    await reserve_usage(supabase, str(job["user_id"]), "claims")

    n = len(patents)
    patents_text = "\n".join(
        f"{p['patent_id']} | {p['title']} | Available text excerpt (source type may be unknown): {(p.get('abstract') or p.get('title') or '')[:300]}"
        for p in patents
    )

    prompt = (
        f"Invention: {invention_idea}\n\n"
        f"Analyze these {n} records for conceptual overlap with the invention. "
        "This is AI inference from available abstracts, search snippets or title text; no patent claims were retrieved. "
        "Describe inferred technical aspects, never quote invented claim language or assert legal scope. "
        "Use only the supplied patent_id values.\n\n"
        "Return ONLY a JSON object:\n"
        "{\n"
        '  "claims": [\n'
        "    {\n"
        '      "patent_id": "US123...",\n'
        '      "title": "...",\n'
        '      "likely_claims": ["Inferred technical aspect..."],\n'
        '      "overlap_level": "high|medium|low|none",\n'
        '      "overlap_explanation": "The available text suggests a conceptual overlap in...",\n'
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
                {"role": "system", "content": "You analyze conceptual overlap from limited text. All conclusions are AI inference, not retrieved claims or legal opinions."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            max_tokens=1500,
        )
        result = json.loads(response.choices[0].message.content)
        claims, warnings = filter_claims(result.get("claims") if isinstance(result, dict) else None, patents)

        await supabase.table("search_results").update({"claims_analysis": {"version": 1, "claims": claims, "warnings": warnings}}).eq("search_id", str(search_id)).execute()

        return {"claims": claims, **({"warnings": warnings} if warnings else {})}
    except Exception as e:
        logger.error("[analyze_claims] Groq error for search %s: %s", search_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jobs/{search_id}", response_model=JobStatusResponse)
async def get_job(
    search_id: UUID,
    job: Dict[str, Any] = Depends(owned_job),
    supabase: AsyncClient = Depends(get_supabase),
) -> JobStatusResponse:
    """Free owned status read; expire running work even when workers are offline."""
    row = job
    if row["status"] == "running":
        try:
            row = await rpc(supabase, "read_analysis_status", {"p_search_id": str(search_id), "p_user_id": str(job["user_id"])})
            if not row: raise ValueError("Missing status")
        except Exception:
            raise HTTPException(503, "Job status could not be confirmed. Retry status; this starts no paid work.") from None
    return JobStatusResponse(
        job_id=str(search_id),
        status=row["status"],
        current_step=row.get("current_step"),
        error_message=row.get("error_message"),
    )
