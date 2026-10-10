"use client";

import { useState } from "react";
import type { EvidenceResponse, EvidencePatent } from "@/lib/api";

export function safeSource(url?: string | null): string | undefined {
  if (!url) return undefined;
  try {
    const parsed = new URL(url);
    return ["https:", "http:"].includes(parsed.protocol) && !parsed.username && !parsed.password ? url : undefined;
  } catch { return undefined; }
}
export function patentSource(patent?: EvidencePatent): string | undefined {
  if (!patent || patent.evidence_status !== "available") return undefined;
  return patent.evidence?.observations.map(o => safeSource(o.source_url)).find(Boolean);
}
const labels = { abstract: "Abstract", search_snippet: "Search snippet", title_only: "Title only", synthetic: "Synthetic demo text" };

export default function EvidenceWorkbench({ data, error, onRetry }: {
  data: EvidenceResponse | null; error: string | null; onRetry: () => void;
}) {
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const patents = data?.patents ?? [];
  const needle = query.toLocaleLowerCase();
  const matches = patents.filter(p => [p.patent_id, p.title, p.evidence_status !== "available" ? p.abstract ?? "" : "", ...(p.evidence?.observations.flatMap(o =>
    [o.provider_record_id, o.publication_id ?? "", o.text, ...o.matching_queries]) ?? [])]
    .join(" ").toLocaleLowerCase().includes(needle));
  const patent = patents.find(p => p.patent_id === selected);
  return (
    <section className="pm-section" aria-labelledby="evidence-heading" id="saved-evidence">
      <div className="pm-section-header"><h2 id="evidence-heading">Retrieved evidence</h2></div>
      <p className="mb-4 text-sm" style={{ color: "var(--text-2)" }}>
        Saved source text and provenance. Search, selection and reopening use no paid calls.
        Requested jurisdiction: {data?.requested_jurisdiction?.toUpperCase() ?? "Unknown"}.
        Filing trends are unavailable for this limited evidence set.
      </p>
      {error && <div role="alert"><p>{error}</p><button className="pm-btn sm" onClick={onRetry}>Retry saved evidence</button></div>}
      {!data && !error && <p role="status">Loading saved evidence...</p>}
      {data && <>
        {data.evidence_version === null && <p className="mb-3">Legacy analysis: historical provenance may be unknown. Nothing is regenerated on read.</p>}
        {data.warnings.map((warning, index) => <p role="status" className="mb-2 text-sm" key={index}>{warning}</p>)}
        <label htmlFor="evidence-query" className="block text-sm mb-2">Search saved evidence</label>
        <input id="evidence-query" type="search" value={query} onChange={e => setQuery(e.target.value)}
          placeholder="Title, provider ID, publication ID or text" className="w-full p-3 mb-4 rounded-md"
          style={{ background: "var(--surface-2)", border: "1px solid var(--border)", color: "var(--text)" }} />
        <div className="grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_minmax(0,2fr)] gap-4">
          <div className="min-w-0">
            <p className="text-sm mb-2">{matches.length} saved records</p>
            <ul className="max-h-80 overflow-auto space-y-2" aria-label="Saved evidence records">
              {matches.map(p => <li key={p.patent_id}><button type="button" aria-pressed={selected === p.patent_id}
                className="text-left w-full rounded-md p-3 break-words" onClick={() => setSelected(p.patent_id)}
                style={{ background: selected === p.patent_id ? "var(--surface-2)" : "var(--surface)", border: "1px solid var(--border)" }}>
                <span className="block font-medium">{p.title || "Untitled record"}</span>
                <span className="block text-xs mt-1 break-all">{p.patent_id}</span>
              </button></li>)}
            </ul>
            {matches.length === 0 && <p>No saved records match this search.</p>}
          </div>
          <div className="min-w-0 rounded-md p-4" style={{ border: "1px solid var(--border)" }}>
            {!patent ? <p>Select a record to inspect its saved text and provenance.</p> : <>
              <h3 className="font-semibold mb-2">{patent.title || patent.patent_id}</h3>
              {patent.evidence_status !== "available" ? <>
                <p className="mb-3">{patent.evidence_status === "legacy_unknown"
                  ? "Historical provenance is unknown. Provider, retrieval time, queries, text type and date semantics were not saved."
                  : "Unsupported evidence version. This reader cannot interpret its provenance."}</p>
                <p className="text-sm mb-2">Historical saved text — type unknown</p>
                <pre data-testid="legacy-evidence-text" className="whitespace-pre-wrap break-words text-sm font-sans">{patent.abstract || "No historical text saved."}</pre>
              </> : patent.evidence?.observations.map((o, index) => <article key={index} className="mb-6 text-sm space-y-2">
                <h4 className="font-medium">Observation {index + 1} · <span>{labels[o.text_type]}</span></h4>
                <p>Provider: {o.provider} · Provider record ID: <span className="break-all">{o.provider_record_id}</span></p>
                <p>Publication identifier: {o.publication_id ?? "Unknown"}</p>
                <p>Retrieved at: {o.retrieved_at ?? "Unknown / not retrieved"}</p>
                <p>Matching queries: {o.matching_queries.join("; ") || "None recorded"}</p>
                <p>Language: {o.language ?? "Unknown"}</p>
                <p>Priority date: {o.dates.priority ?? "Unknown"}</p>
                <p>Filing date: {o.dates.filing ?? "Unknown"}</p>
                <p>Publication date: {o.dates.publication ?? "Unknown"}</p>
                <p>Requested jurisdiction: {o.requested_jurisdiction.toUpperCase()}</p>
                <p>Provider filter submitted: {o.jurisdiction_filter ? `country=${o.jurisdiction_filter.country}` : "None"}</p>
                {o.coverage_limitations.map((w, i) => <p key={i}>{w}</p>)}
                <p className="font-medium pt-2">Exact saved text</p>
                <pre data-testid="evidence-text" className="whitespace-pre-wrap break-words font-sans p-3 rounded-md" style={{ background: "var(--surface-2)" }}>{o.text}</pre>
                {safeSource(o.source_url) ? <a className="underline" href={safeSource(o.source_url)} target="_blank" rel="noopener noreferrer">Open saved source</a> : <p>Source URL unavailable.</p>}
              </article>)}
            </>}
          </div>
        </div>
      </>}
    </section>
  );
}
