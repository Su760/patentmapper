"""
Query Expander Node
In:  invention_idea
Out: search_queries (5-10 queries)
Real impl: Groq llama-3.3-70b-versatile (JSON-mode function calling to force a list)
"""
import json
import logging
from typing import Any, Dict, List

from groq import AsyncGroq
from tenacity import retry, stop_after_attempt, wait_exponential

from supabase import AsyncClient

from app.agents.state import LandscapeState
from app.core.config import settings

logger = logging.getLogger(__name__)

MOCK_QUERIES = [
    "AI-powered patent search prior art machine learning",
    "natural language processing patent classification USPTO",
    "semantic similarity patent document retrieval",
    "automated patent landscaping competitive intelligence",
    "invention novelty detection neural network",
    "prior art search transformer embeddings",
    "patent claim analysis large language models",
]

_JURISDICTION_SUFFIX = {
    "us": "USPTO US patent",
    "ep": "EPO European patent",
    "wo": "WIPO PCT international patent",
}

_SYSTEM_PROMPT = (
    "You are a patent search expert. Given an invention description, generate diverse patent search queries."
    " Return ONLY a valid JSON object with a single key 'queries' containing an array of 7 strings."
    ' Example: {"queries": ["query 1", "query 2", ...]}'
    " Cover different angles: problem being solved, technical solution, domain/industry,"
    " key components, alternative approaches, use cases, and competitor technologies."
)


async def expander_node(state: LandscapeState, supabase: AsyncClient) -> Dict[str, Any]:
    """Expand invention idea into search queries."""
    search_id = state["search_id"]
    logger.info("[expander] starting for search_id=%s", search_id)

    await supabase.table("searches").update({"current_step": "generating_queries"}).eq(
        "id", search_id
    ).execute()

    suffix = _JURISDICTION_SUFFIX.get(state.get("jurisdiction", "all"), "")

    if settings.mock_mode:
        queries = [q for i, q in enumerate(MOCK_QUERIES) if i < 7]
        if suffix:
            queries = [f"{q} {suffix}" for q in queries]
        logger.info("[expander] mock mode — returning %d queries", len(queries))
        return {"search_queries": queries}

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def _call_groq() -> List[Any]:
        client = AsyncGroq(api_key=settings.groq_api_key)
        response = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": state["invention_idea"]},
            ],
            response_format={"type": "json_object"},
            temperature=0.7,
        )
        content = response.choices[0].message.content
        parsed = json.loads(content)
        if isinstance(parsed, list):
            return parsed
        return parsed.get("queries") or list(parsed.values())[0]

    queries = await _call_groq()
    if suffix:
        queries = [f"{q} {suffix}" for q in queries]
    queries = [q for i, q in enumerate(queries) if i < 10]
    logger.info("[expander] real mode — got %d queries", len(queries))
    return {"search_queries": queries}
