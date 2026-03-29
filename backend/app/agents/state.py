from typing import Any, Dict, List, TypedDict


class LandscapeState(TypedDict):
    search_id: str
    invention_idea: str
    jurisdiction: str  # "all" | "us" | "ep" | "wo"
    search_queries: List[str]
    raw_patents: List[Dict[str, Any]]
    deduped_patents: List[Dict[str, Any]]
    clusters: List[Dict[str, Any]]
    white_space_analysis: str
    final_report: str
    citation_links: List[Dict[str, Any]]  # [{"source": "US123", "target": "US456", "strength": 0.8}]
    errors: List[str]
