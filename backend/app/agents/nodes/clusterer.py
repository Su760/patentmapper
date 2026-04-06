"""
Clusterer Node
In:  deduped_patents
Out: clusters (3-5 thematic clusters)
Real impl: pass top 50 abstracts to Groq llama-3.3-70b-versatile, ask for thematic grouping
"""
import json
import logging
from typing import Any, Dict, List, Optional

from groq import AsyncGroq
from tenacity import retry, stop_after_attempt, wait_exponential

from supabase import AsyncClient

from app.agents.state import LandscapeState
from app.core.config import settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a patent analyst. Group the following patents into 3-5 thematic clusters."
    " Return ONLY a valid JSON object with a single key 'clusters' containing an array of objects."
    " Each object must have: 'theme_name' (string), 'description' (one sentence),"
    " 'patent_ids' (array of patent_id strings),"
    " 'ipc_codes' (array of 0-2 IPC classification strings like 'G06F 40/30',"
    " empty array if unsure)."
    " No markdown, no explanation — just the JSON object."
)

MOCK_CLUSTERS = [
    {
        "theme_name": "Semantic Search & Retrieval",
        "description": "Patents focused on using neural embeddings and NLP to find semantically similar documents across large patent corpora.",
        "patent_ids": ["US10234567B2", "US10987654B1", "US10654321A1"],
        "ipc_codes": ["G06F 16/903", "G06N 3/08"],
        "top_assignees": [
            {"name": "TechCorp Inc.", "count": 1},
            {"name": "AI Research Labs", "count": 1},
            {"name": "DefenseIP LLC", "count": 1},
        ],
        # US10234567B2→2019, US10987654B1→2020, US10654321A1→2023 — accelerating
        "filing_trend": [
            {"year": 2019, "count": 1},
            {"year": 2020, "count": 1},
            {"year": 2023, "count": 1},
        ],
    },
    {
        "theme_name": "Patent Classification & Knowledge Graphs",
        "description": "Systems that categorize patents into technical domains and construct structured knowledge representations from patent literature.",
        "patent_ids": ["US11345678A1", "US11567890A1", "US11223344B1"],
        "ipc_codes": ["G06F 40/30", "G06N 5/04"],
        "top_assignees": [
            {"name": "PatentTech Solutions", "count": 1},
            {"name": "Graph Analytics Ltd", "count": 1},
            {"name": "GlobalIP Solutions", "count": 1},
        ],
        # US11345678A1→2020, US11567890A1→2021, US11223344B1→2023 — stable
        "filing_trend": [
            {"year": 2020, "count": 1},
            {"year": 2021, "count": 1},
            {"year": 2023, "count": 1},
        ],
    },
    {
        "theme_name": "Automated Drafting & Competitive Intelligence",
        "description": "Tools that assist with patent drafting using AI, identify whitespace opportunities, and score invention novelty against existing prior art.",
        "patent_ids": ["US11234500B2", "US10543210B1", "US11098765B2", "US10876543B2"],
        "ipc_codes": ["G06Q 50/18"],
        "top_assignees": [
            {"name": "InnovateCo", "count": 1},
            {"name": "IP Strategy Group", "count": 1},
            {"name": "LegalAI Inc.", "count": 1},
        ],
        # US10876543B2→2019, US11234500B2→2021, US10543210B1→2022, US11098765B2→2022 — slowing
        "filing_trend": [
            {"year": 2019, "count": 1},
            {"year": 2021, "count": 1},
            {"year": 2022, "count": 2},
        ],
    },
]


async def clusterer_node(state: LandscapeState, supabase: AsyncClient) -> Dict[str, Any]:
    """Cluster deduped patents into thematic groups."""
    search_id = state["search_id"]
    logger.info(
        "[clusterer] starting for search_id=%s, %d patents",
        search_id,
        len(state["deduped_patents"]),
    )

    await supabase.table("searches").update({"current_step": "clustering"}).eq(
        "id", search_id
    ).execute()

    if settings.mock_mode:
        logger.info("[clusterer] mock mode — returning %d clusters", len(MOCK_CLUSTERS))
        return {"clusters": MOCK_CLUSTERS}

    top_patents = state["deduped_patents"][:30]
    estimated = sum(
        len((p.get("title") or "")[:80]) + len((p.get("abstract") or "")[:150])
        for p in top_patents
    ) // 4
    logger.info("[clusterer] estimated tokens for Groq: ~%d", estimated)
    abstracts_text = "\n\n".join(
        f"[{p['patent_id']}] {(p.get('title') or '')[:80]}: {(p.get('abstract') or '')[:150]}"
        for p in top_patents
    )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def _call_groq() -> List[Dict[str, Any]]:
        client = AsyncGroq(api_key=settings.groq_api_key)
        response = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": abstracts_text},
            ],
            response_format={"type": "json_object"},
        )
        parsed = json.loads(response.choices[0].message.content)
        if isinstance(parsed, list):
            return parsed
        return parsed.get("clusters") or list(parsed.values())[0]

    patent_assignee: Dict[str, str] = {
        p["patent_id"]: p.get("assignee", "")
        for p in state["deduped_patents"]
        if p.get("patent_id")
    }

    clusters = await _call_groq()

    patent_year: Dict[str, Optional[int]] = {
        p["patent_id"]: p.get("filing_year")
        for p in state["deduped_patents"]
        if p.get("patent_id")
    }

    for cluster in clusters:
        if not isinstance(cluster.get("ipc_codes"), list):
            cluster["ipc_codes"] = []

        counts: Dict[str, int] = {}
        for pid in cluster.get("patent_ids", []):
            name = patent_assignee.get(pid, "").strip()
            if name:
                counts[name] = counts.get(name, 0) + 1
        top = [
            item for i, item in
            enumerate(sorted(counts.items(), key=lambda x: x[1], reverse=True))
            if i < 3
        ]
        cluster["top_assignees"] = [{"name": n, "count": c} for n, c in top]

        year_counts: Dict[int, int] = {}
        for pid in cluster.get("patent_ids", []):
            year = patent_year.get(pid)
            if year is not None:
                year_counts[year] = year_counts.get(year, 0) + 1
        trend = sorted(
            [{"year": y, "count": c} for y, c in year_counts.items()],
            key=lambda x: x["year"],
        )
        cluster["filing_trend"] = trend if len(trend) >= 2 else []

    logger.info("[clusterer] real mode — got %d clusters", len(clusters))
    return {"clusters": clusters}
