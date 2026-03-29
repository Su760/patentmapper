"""
White Space Analyzer Node
In:  invention_idea + clusters
Out: white_space_analysis (markdown with cited gaps)
Real impl: Groq llama-3.3-70b-versatile with heavy citation mechanics
"""
import logging
from typing import Any, Dict

from groq import AsyncGroq
from tenacity import retry, stop_after_attempt, wait_exponential

from supabase import AsyncClient

from app.agents.state import LandscapeState
from app.core.config import settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a patent landscape analyst. Identify 2-3 specific technical gaps not addressed by the prior art clusters."
    " For each gap you MUST cite specific patent IDs using format [US1234567B2]."
    " Format your response as markdown with ### Gap N: Title headers and **Viability: High/Medium/Low** on its own line."
)

MOCK_WHITESPACE = """## White Space Analysis

### Gap 1: Real-Time Collaborative Patent Drafting
**Viability: High**

Current prior art (Cluster 3 — patents [US11098765B2, US10543210B1]) covers AI-assisted single-user drafting workflows. None of these patents address multi-user, real-time collaborative editing with conflict resolution. This gap exists because Cluster 3 patents [US11098765B2] only covers retrieval-augmented generation for individual sessions, and [US10543210B1] focuses on post-hoc whitespace analysis rather than live collaborative tooling.

### Gap 2: Explainable Similarity Scoring for Examiner Use
**Viability: High**

Cluster 1 patents ([US10234567B2], [US10654321A1]) cover semantic similarity engines but output only ranked lists without human-interpretable explanations. No existing patent in the landscape addresses the explainability layer required for patent examiners to trust and act on AI-ranked prior art. Cluster 1 [US10987654B1] provides structural claim parsing but does not produce examiner-facing rationale narratives.
"""


async def whitespace_node(state: LandscapeState, supabase: AsyncClient) -> Dict[str, Any]:
    """Identify white space opportunities relative to invention idea and clusters."""
    search_id = state["search_id"]
    logger.info("[whitespace] starting for search_id=%s", search_id)

    await supabase.table("searches").update({"current_step": "analyzing_gaps"}).eq(
        "id", search_id
    ).execute()

    if settings.mock_mode:
        logger.info("[whitespace] mock mode — returning fake analysis")
        return {"white_space_analysis": MOCK_WHITESPACE}

    cluster_summary = "\n\n".join(
        f"Cluster {i + 1}: {c['theme_name']}\n{c['description']}\nPatents: {', '.join(c.get('patent_ids', []))}"
        for i, c in enumerate(state["clusters"])
    )
    user_content = f"Invention: {state['invention_idea']}\n\nPrior Art Clusters:\n{cluster_summary}"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def _call_groq() -> str:
        client = AsyncGroq(api_key=settings.groq_api_key)
        response = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
        )
        return response.choices[0].message.content

    analysis = await _call_groq()
    logger.info("[whitespace] real mode — analysis generated (%d chars)", len(analysis))
    return {"white_space_analysis": analysis}
