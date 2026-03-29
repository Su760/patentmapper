"""
Patent API wrappers — PatentsView (USPTO), Lens.org, and SerpAPI (Google Patents).
Caller is responsible for fallback logic; these functions just call the APIs.
"""
import logging
from typing import Any, Dict, List

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

PATENTSVIEW_URL = "https://api.patentsview.org/patents/query"
SERPAPI_URL = "https://serpapi.com/search"
LENS_URL = "https://api.lens.org/patent/search"

logger = logging.getLogger(__name__)

_COUNTRY_MAP: Dict[str, str] = {"us": "US", "ep": "EP", "wo": "WO"}


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=8))
async def fetch_patentsview_patents(
    query: str,
    client: httpx.AsyncClient,
    api_key: str,
    jurisdiction: str = "all",
) -> List[Dict[str, Any]]:
    """Fetch patents from USPTO PatentsView API (US patents only)."""
    if jurisdiction not in ("us", "all"):
        return []

    headers = {"X-Api-Key": api_key} if api_key else {}
    payload = {
        "q": {"_or": [
            {"_text_any": {"patent_abstract": query}},
            {"_text_any": {"patent_title": query}},
        ]},
        "f": ["patent_id", "patent_title", "patent_abstract", "patent_date", "app_date", "assignees", "cpcs"],
        "o": {"per_page": 10},
    }
    try:
        resp = await client.post(PATENTSVIEW_URL, json=payload, headers=headers, timeout=30.0)
        if resp.status_code == 429:
            resp.raise_for_status()  # let tenacity / caller catch it
        resp.raise_for_status()

        patents = resp.json().get("patents") or []
        results = []
        for p in patents:
            assignee = next(
                (a.get("assignee_organization", "") for a in (p.get("assignees") or [])),
                "",
            )
            classifications: List[str] = []
            for c in (p.get("cpcs") or []):
                if len(classifications) >= 3:
                    break
                if c.get("cpc_subgroup_id"):
                    classifications.append(c["cpc_subgroup_id"])
            raw_date = p.get("app_date") or p.get("patent_date")
            filing_year = int(str(raw_date)[:4]) if raw_date and str(raw_date)[:4].isdigit() else None
            results.append({
                "patent_id": p.get("patent_id", ""),
                "title": p.get("patent_title", ""),
                "abstract": p.get("patent_abstract", ""),
                "assignee": assignee,
                "url": f"https://patents.google.com/patent/US{p.get('patent_id', '')}/en",
                "source": "patentsview",
                "classifications": classifications,
                "filing_year": filing_year,
            })
        return results
    except httpx.HTTPStatusError:
        raise
    except Exception as e:
        logger.warning("[patent_api] PatentsView error for query '%s': %s", query, e)
        return []


async def fetch_serpapi_patents(
    query: str, client: httpx.AsyncClient, api_key: str, jurisdiction: str = "all"
) -> List[Dict[str, Any]]:
    """Fetch patents from Google Patents via SerpAPI.

    No retry — 429 and other errors must propagate immediately so the caller
    can fall back to Lens.org without wasting quota on retries.
    """
    params: Dict[str, Any] = {
        "engine": "google_patents",
        "q": query,
        "api_key": api_key,
        "num": 10,
    }
    country = _COUNTRY_MAP.get(jurisdiction)
    if country:
        params["country"] = country
    resp = await client.get(
        SERPAPI_URL,
        params=params,
        timeout=30.0,
    )
    resp.raise_for_status()

    results = []
    for r in resp.json().get("organic_results", []):
        pub_info = r.get("publication_info", {})
        summary = pub_info.get("summary", "")
        assignee = summary.split(" · ")[0] if " · " in summary else summary
        pid = r.get("patent_id") or r.get("result_id", "")
        if pid.startswith("patent/"):
            pid = pid.split("/")[1]
        url = r.get("link") or (f"https://patents.google.com/patent/{pid}" if pid else "")
        codes = []
        for c in (r.get("patent_classifications") or r.get("classifications") or []):
            if len(codes) >= 3:
                break
            if isinstance(c, dict):
                code = c.get("code") or c.get("symbol") or c.get("value") or ""
                if code:
                    codes.append(code)
            elif isinstance(c, str) and c:
                codes.append(c)
        raw_date = r.get("priority_date") or r.get("filing_date") or r.get("publication_date")
        filing_year = int(str(raw_date)[:4]) if raw_date and str(raw_date)[:4].isdigit() else None
        results.append({
            "patent_id": pid,
            "title": r.get("title", ""),
            "abstract": r.get("snippet", ""),
            "assignee": assignee,
            "url": url,
            "source": "serpapi",
            "classifications": codes,
            "filing_year": filing_year,
        })
    return results


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def fetch_lens_patents(
    query: str, client: httpx.AsyncClient
) -> List[Dict[str, Any]]:
    """Fetch patents from Lens.org free API (no auth required for basic queries)."""
    payload = {
        "query": {"match": {"title": query}},
        "size": 10,
        "include": ["patent_id", "title", "abstract", "applicant", "lens_id", "classification_ipc"],
    }
    resp = await client.post(LENS_URL, json=payload, timeout=30.0)
    resp.raise_for_status()

    results = []
    for r in resp.json().get("data", []):
        applicants = r.get("applicant") or []
        assignee = applicants[0].get("name", "") if applicants else ""
        lens_id = r.get("lens_id", "")
        url = f"https://lens.org/lens/patent/{lens_id}" if lens_id else ""
        ipc_codes = []
        for item in (r.get("classification_ipc") or []):
            if len(ipc_codes) >= 3:
                break
            if isinstance(item, dict) and item.get("symbol"):
                ipc_codes.append(item["symbol"])
        raw_date = r.get("priority_date") or r.get("filing_date") or r.get("date_published")
        filing_year = int(str(raw_date)[:4]) if raw_date and str(raw_date)[:4].isdigit() else None
        results.append({
            "patent_id": r.get("patent_id", ""),
            "title": r.get("title", ""),
            "abstract": r.get("abstract", ""),
            "assignee": assignee,
            "url": url,
            "source": "lens",
            "classifications": ipc_codes,
            "filing_year": filing_year,
        })
    return results
