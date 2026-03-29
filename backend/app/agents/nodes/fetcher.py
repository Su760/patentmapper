"""
Patent Fetcher Node
In:  search_queries
Out: raw_patents (list of patent dicts)
Real impl: parallel async HTTP to SerpAPI + Lens.org
"""
import asyncio
import logging
from typing import Any, Dict, List

import httpx

from supabase import AsyncClient

from app.agents.state import LandscapeState
from app.core.config import settings
from app.services.patent_api import fetch_lens_patents, fetch_patentsview_patents, fetch_serpapi_patents

logger = logging.getLogger(__name__)

_SEMAPHORE = asyncio.Semaphore(5)

MOCK_PATENTS: List[Dict[str, Any]] = [
    {
        "patent_id": "US10234567B2",
        "title": "System and method for automated patent prior art search using neural networks",
        "abstract": "A system for searching prior art using neural network embeddings to identify semantically similar patent documents across large corpora.",
        "assignee": "TechCorp Inc.",
        "url": "https://patents.google.com/patent/US10234567B2",
        "source": "serpapi",
        "filing_year": 2019,
    },
    {
        "patent_id": "US10987654B1",
        "title": "Natural language processing pipeline for patent claim analysis",
        "abstract": "Methods and apparatus for parsing and analyzing patent claims using transformer-based NLP models to extract structured semantic information.",
        "assignee": "AI Research Labs",
        "url": "https://patents.google.com/patent/US10987654B1",
        "source": "serpapi",
        "filing_year": 2020,
    },
    {
        "patent_id": "US11345678A1",
        "title": "Machine learning based patent classification and clustering",
        "abstract": "A classification system that applies deep learning techniques to categorize patents into technical domains and identify thematic clusters within patent landscapes.",
        "assignee": "PatentTech Solutions",
        "url": "https://patents.google.com/patent/US11345678A1",
        "source": "lens",
        "filing_year": 2020,
    },
    {
        "patent_id": "US11234500B2",
        "title": "Automated invention novelty scoring system",
        "abstract": "A scoring system for evaluating the novelty of invention disclosures by comparing semantic embeddings against a corpus of existing patents.",
        "assignee": "InnovateCo",
        "url": "https://patents.google.com/patent/US11234500B2",
        "source": "lens",
        "filing_year": 2021,
    },
    {
        "patent_id": "US10876543B2",
        "title": "Distributed patent search architecture with real-time indexing",
        "abstract": "An architecture for indexing and searching patent documents in real time using distributed computing techniques and inverted index structures.",
        "assignee": "SearchSystems Corp",
        "url": "https://patents.google.com/patent/US10876543B2",
        "source": "serpapi",
        "filing_year": 2019,
    },
    {
        "patent_id": "US11567890A1",
        "title": "Knowledge graph construction from patent literature",
        "abstract": "Methods for constructing knowledge graphs from patent documents by extracting entities, relationships, and technical concepts using information extraction pipelines.",
        "assignee": "Graph Analytics Ltd",
        "url": "https://patents.google.com/patent/US11567890A1",
        "source": "serpapi",
        "filing_year": 2021,
    },
    {
        "patent_id": "US10543210B1",
        "title": "Patent whitespace identification via competitive landscape analysis",
        "abstract": "A system for identifying whitespace opportunities in patent landscapes by analyzing cluster distributions and detecting underrepresented technical areas.",
        "assignee": "IP Strategy Group",
        "url": "https://patents.google.com/patent/US10543210B1",
        "source": "lens",
        "filing_year": 2022,
    },
    {
        "patent_id": "US11098765B2",
        "title": "Retrieval-augmented generation for patent drafting assistance",
        "abstract": "A patent drafting assistant that uses retrieval-augmented generation to suggest claim language based on similar existing patents and technical specifications.",
        "assignee": "LegalAI Inc.",
        "url": "https://patents.google.com/patent/US11098765B2",
        "source": "lens",
        "filing_year": 2022,
    },
    {
        "patent_id": "US10654321A1",
        "title": "Semantic patent similarity for invalidation search",
        "abstract": "A semantic similarity engine for patent invalidation search that surfaces prior art candidates ranked by conceptual overlap with challenged claims.",
        "assignee": "DefenseIP LLC",
        "url": "https://patents.google.com/patent/US10654321A1",
        "source": "serpapi",
        "filing_year": 2023,
    },
    {
        "patent_id": "US11223344B1",
        "title": "Cross-jurisdictional patent family detection and normalization",
        "abstract": "A system for detecting patent families across multiple jurisdictions by normalizing patent identifiers and mapping equivalent filings in USPTO, EPO, and WIPO databases.",
        "assignee": "GlobalIP Solutions",
        "url": "https://patents.google.com/patent/US11223344B1",
        "source": "lens",
        "filing_year": 2023,
    },
]


async def fetcher_node(state: LandscapeState, supabase: AsyncClient) -> Dict[str, Any]:
    """Fetch raw patents for each search query."""
    search_id = state["search_id"]
    logger.info(
        "[fetcher] starting for search_id=%s, %d queries",
        search_id,
        len(state["search_queries"]),
    )

    await supabase.table("searches").update({"current_step": "fetching_patents"}).eq(
        "id", search_id
    ).execute()

    if settings.mock_mode:
        logger.info("[fetcher] mock mode — returning %d patents", len(MOCK_PATENTS))
        return {"raw_patents": MOCK_PATENTS}

    queries = state["search_queries"]

    jurisdiction = state.get("jurisdiction", "all")

    async def _fetch_with_fallback(
        client: httpx.AsyncClient, query: str
    ) -> List[Dict[str, Any]]:
        async with _SEMAPHORE:
            # Priority 1: PatentsView (US patents, no quota cost)
            if settings.patentsview_enabled and jurisdiction in ("us", "all"):
                logger.info("[fetcher] trying PatentsView for query: %s", query)
                try:
                    results: List[Dict[str, Any]] = await fetch_patentsview_patents(
                        query, client, settings.patentsview_key, jurisdiction
                    )
                    logger.info("[fetcher] PatentsView returned %d results", len(results))
                    if results:
                        return results
                    logger.info("[fetcher] PatentsView empty/failed, trying Lens.org")
                except Exception as e:
                    logger.warning(
                        "[fetcher] PatentsView empty/failed, trying Lens.org: %s", e
                    )
            # Priority 2: Lens.org
            try:
                return await fetch_lens_patents(query, client)
            except Exception as e:
                logger.warning(
                    "[fetcher] Lens.org failed for query '%s': %s — falling back to SerpAPI", query, e
                )
            # Priority 3: SerpAPI (last resort)
            if settings.serpapi_enabled:
                logger.info("[fetcher] falling back to SerpAPI for query: %s", query)
                try:
                    return await fetch_serpapi_patents(
                        query, client, settings.serpapi_key, jurisdiction
                    )
                except Exception as e:
                    logger.warning("[fetcher] SerpAPI also failed for query '%s': %s", query, e)
            return []

    async with httpx.AsyncClient() as client:
        tasks = [_fetch_with_fallback(client, q) for q in queries]
        results_per_query = await asyncio.gather(*tasks)

    raw_patents: List[Dict[str, Any]] = []
    for result in results_per_query:
        raw_patents.extend(result)

    logger.info("[fetcher] real mode — fetched %d patents", len(raw_patents))
    return {"raw_patents": raw_patents}
