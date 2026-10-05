"""
Deduplicator Node
In:  raw_patents
Out: deduped_patents (unique by patent_id, normalized fields)
"""
import logging
from typing import Any, Dict

from supabase import AsyncClient

from app.agents.state import LandscapeState
from app.services.execution import update_stage
from app.services.evidence import deduplicate

logger = logging.getLogger(__name__)


async def deduplicator_node(state: LandscapeState, supabase: AsyncClient) -> Dict[str, Any]:
    """Deduplicate patents by patent_id and normalize fields."""
    search_id = state["search_id"]
    raw = state["raw_patents"]
    logger.info("[deduplicator] starting for search_id=%s, %d raw patents", search_id, len(raw))

    await update_stage(supabase, state, "deduplicating")

    deduped = deduplicate(raw)

    logger.info("[deduplicator] %d → %d patents after dedup", len(raw), len(deduped))
    if not deduped:
        return {"deduped_patents": [], "retrieval_outcome": "insufficient_evidence",
                "clusters": [], "white_space_analysis": "", "final_report": "", "citation_links": []}
    return {"deduped_patents": deduped}
