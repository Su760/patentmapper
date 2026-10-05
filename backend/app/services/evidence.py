"""Evidence v1: saved observations, never reconstructed provenance or paid reads."""
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

EVIDENCE_VERSION = 1
COVERAGE_LIMIT = 'Limited search results; coverage is not exhaustive. No full patent claims were retrieved.'


def string(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def observation(*, provider: str, record_id: str, publication_id: str | None,
                url: str | None, query: str, text: str, text_type: str,
                jurisdiction: str, dates: dict[str, Any], language: str | None = None,
                retrieved_at: str | None = None) -> dict[str, Any]:
    limitations = [COVERAGE_LIMIT]
    provider_filter = None
    if provider == 'serpapi' and jurisdiction in ('us', 'ep', 'wo'):
        provider_filter = {'country': jurisdiction.upper()}
    elif provider == 'lens' and jurisdiction != 'all':
        limitations.append('Requested jurisdiction filter was not applied by the Lens adapter.')
    elif provider == 'synthetic':
        limitations = ['Synthetic demo text; no patent retrieval or jurisdiction filtering was performed.']
    return dict(provider=provider, provider_record_id=record_id, publication_id=publication_id,
                source_url=url, retrieved_at=retrieved_at or datetime.now(timezone.utc).isoformat(),
                matching_queries=[query] if query else [], text=text, text_type=text_type,
                language=language, dates={k: string(dates.get(k)) for k in ('priority','filing','publication')},
                requested_jurisdiction=jurisdiction, jurisdiction_filter=provider_filter,
                coverage_limitations=limitations)


def with_evidence(patent: dict[str, Any], observations: list[dict[str, Any]]) -> dict[str, Any]:
    first = observations[0]
    return {**patent, 'patent_id': f"{first['provider']}:{first['provider_record_id']}",
            'evidence': {'version': EVIDENCE_VERSION, 'observations': observations}}


def deduplicate(patents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge only identical internal provider record identities, never publication guesses."""
    grouped: dict[str, dict[str, Any]] = {}
    for patent in patents:
        pid = string(patent.get('patent_id'))
        if not pid or not any(string(patent.get(k)) for k in ('title', 'abstract')):
            continue
        if pid not in grouped:
            grouped[pid] = deepcopy(patent)
        elif patent.get('evidence', {}).get('version') == EVIDENCE_VERSION:
            target = grouped[pid].get('evidence')
            if target and target.get('version') == EVIDENCE_VERSION:
                for item in patent['evidence']['observations']:
                    if item not in target['observations']:
                        target['observations'].append(deepcopy(item))
    return list(grouped.values())


def validate_references(clusters: Any, links: Any, patents: list[dict[str, Any]]) -> tuple[list, list, list[str]]:
    """Only retrieved IDs may be structured members/endpoints; prose remains inference."""
    allowed = {p['patent_id'] for p in patents}
    warnings: list[str] = []
    clean_clusters, clean_links = [], []
    if not isinstance(clusters, list):
        clusters = []
        warnings.append('Excluded malformed cluster list.')
    for index, cluster in enumerate(clusters, 1):
        if not isinstance(cluster, dict):
            warnings.append(f'Excluded malformed cluster {index}.')
            continue
        members = cluster.get('patent_ids')
        if not isinstance(members, list):
            warnings.append(f'Cluster {index}: excluded malformed patent member list.')
            members = []
        valid = list(dict.fromkeys(pid for pid in members if isinstance(pid, str) and pid in allowed))
        excluded = len(members) - len(valid)
        if excluded:
            warnings.append(f'Cluster {index}: excluded {excluded} unknown, duplicate or malformed patent references.')
        # This bounded retrieval cannot establish population-level filing trends.
        counts: dict[str, int] = {}
        for patent in patents:
            if patent['patent_id'] in valid and string(patent.get('assignee')):
                name = patent['assignee']
                counts[name] = counts.get(name, 0) + 1
        ipc = cluster.get('ipc_codes')
        clean_clusters.append({'theme_name': string(cluster.get('theme_name')) or 'Unnamed cluster',
            'description': string(cluster.get('description')) or '', 'patent_ids': valid,
            'ipc_codes': [code for code in ipc if string(code)] if isinstance(ipc, list) else [],
            'top_assignees': [{'name': name, 'count': count} for name, count in
                              sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:3]],
            'filing_trend': []})
    if not isinstance(links, list):
        links = []
        warnings.append('Excluded malformed relationship list.')
    seen = set()
    for index, link in enumerate(links, 1):
        source = link.get('source') if isinstance(link, dict) else None
        target = link.get('target') if isinstance(link, dict) else None
        if (not isinstance(source, str) or not isinstance(target, str) or source not in allowed
                or target not in allowed or source == target):
            warnings.append(f'Relationship {index}: excluded unknown or malformed endpoints.')
            continue
        if (source, target) in seen:
            warnings.append(f'Relationship {index}: excluded duplicate.')
            continue
        seen.add((source, target))
        strength = link.get('strength', 0.5)
        if type(strength) not in (float, int) or not 0 <= strength <= 1:
            strength = 0.5
        clean_links.append(dict(source=source, target=target, strength=strength, is_ai_inferred=True))
    return clean_clusters, clean_links, warnings


def saved_evidence(patent: dict[str, Any]) -> dict[str, Any]:
    """Unknown versions are opaque. Historical text is shown with unknown origin/type."""
    value = patent.get('evidence')
    status = 'available' if isinstance(value, dict) and value.get('version') == EVIDENCE_VERSION else 'legacy_unknown' if value is None else 'unsupported_version'
    return {**patent, 'evidence_status': status,
            'evidence': value if status == 'available' else None}


def filter_claims(claims: Any, patents: list[dict[str, Any]]) -> tuple[list, list[str]]:
    allowed = {p['patent_id']: p for p in patents}
    clean, seen = [], set()
    if not isinstance(claims, list):
        return [], ['Excluded malformed overlap reference list.']
    rows = claims
    for claim in rows:
        pid = claim.get('patent_id') if isinstance(claim, dict) else None
        if not isinstance(pid, str) or pid not in allowed or pid in seen:
            continue
        seen.add(pid)
        clean.append({**claim, 'title': allowed[pid].get('title') or pid})
    count = len(rows) - len(clean)
    return clean, ([f'Excluded {count} unknown, duplicate or malformed overlap references.'] if count else [])
