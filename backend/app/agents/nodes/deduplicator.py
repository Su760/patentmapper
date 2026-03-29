"""
Deduplicator Node
In:  raw_patents
Out: deduped_patents (unique by patent_id, normalized fields)
"""
import logging
from typing import Any, Dict

from supabase import AsyncClient

from app.agents.state import LandscapeState

logger = logging.getLogger(__name__)


async def deduplicator_node(state: LandscapeState, supabase: AsyncClient) -> Dict[str, Any]:
    """Deduplicate patents by patent_id and normalize fields."""
    search_id = state["search_id"]
    raw = state["raw_patents"]
    logger.info("[deduplicator] starting for search_id=%s, %d raw patents", search_id, len(raw))

    await supabase.table("searches").update({"current_step": "deduplicating"}).eq(
        "id", search_id
    ).execute()

    seen: set = set()
    deduped = []
    for patent in raw:
        pid = patent.get("patent_id", "")
        if pid and pid not in seen:
            seen.add(pid)
            deduped.append(patent)

    logger.info("[deduplicator] %d → %d patents after dedup", len(raw), len(deduped))
    return {"deduped_patents": deduped}
