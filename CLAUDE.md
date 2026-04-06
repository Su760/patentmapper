# Patent Landscape Mapper — Claude Code Build Guide

## What this project is

A multi-agent web app that takes a plain-english invention description and outputs a
patent landscape brief: prior art clusters, white space opportunities, and a rendered
markdown report. Built as a startup-grade portfolio project.

## Tech stack (do not deviate without asking)

- **Frontend:** Next.js 14 App Router, TypeScript, Tailwind CSS
- **Backend:** FastAPI (Python), async, background tasks
- **Agents:** LangGraph (strict DAG, 6 nodes)
- **LLM:** Gemini 2.0 Flash via google-generativeai SDK
- **Data:** Supabase (Postgres DB + Storage + Auth)
- **Patent APIs:** SerpAPI (Google Patents) + Lens.org free API
- **Retry logic:** tenacity (exponential backoff)
- **Validation:** Pydantic v2

## Monorepo structure

```
patent-mapper/
├── CLAUDE.md
├── .env                          # never commit this
├── frontend/                     # Next.js 14
│   ├── src/
│   │   ├── app/
│   │   │   ├── page.tsx          # landing + search input
│   │   │   ├── dashboard/page.tsx
│   │   │   └── results/[id]/page.tsx
│   │   ├── components/
│   │   └── lib/
│   │       ├── supabase.ts
│   │       └── api.ts
│   ├── package.json
│   └── tailwind.config.ts
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/routes.py         # POST /jobs, GET /jobs/{id}
│   │   ├── agents/
│   │   │   ├── state.py          # LandscapeState TypedDict
│   │   │   ├── graph.py          # compiled LangGraph graph
│   │   │   └── nodes/
│   │   │       ├── expander.py
│   │   │       ├── fetcher.py
│   │   │       ├── deduplicator.py
│   │   │       ├── clusterer.py
│   │   │       ├── whitespace.py
│   │   │       └── reporter.py
│   │   ├── core/config.py
│   │   └── services/patent_api.py
│   └── requirements.txt
└── README.md
```

## LangGraph state (source of truth)

```python
class LandscapeState(TypedDict):
    search_id: str
    invention_idea: str
    search_queries: List[str]
    raw_patents: List[Dict[str, Any]]
    deduped_patents: List[Dict[str, Any]]
    clusters: List[Dict[str, Any]]
    white_space_analysis: str
    final_report: str
    errors: List[str]
```

## Agent graph (6 nodes, strict DAG)

1. **expander** — invention_idea → search_queries (Gemini function calling, force list of 5-10 queries)
2. **fetcher** — search_queries → raw_patents (parallel async HTTP, SerpAPI + Lens.org)
3. **deduplicator** — raw_patents → deduped_patents (dedupe by patent_number, normalize fields)
4. **clusterer** — deduped_patents → clusters (pass top 50 abstracts to Gemini, ask for 3-5 thematic clusters, NO k-means/embeddings in v1)
5. **whitespace** — invention_idea + clusters → white_space_analysis (Gemini, force citation format: "Gap X because Cluster A patents [US123] only covers Y")
6. **reporter** — all state → final_report (Gemini, markdown synthesis)

## Supabase DB schema

```sql
CREATE TABLE searches (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  invention_idea TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'processing', -- 'processing' | 'completed' | 'failed'
  current_step TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  error_message TEXT
);

CREATE TABLE search_results (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  search_id UUID REFERENCES searches(id) ON DELETE CASCADE UNIQUE,
  clusters JSONB,
  white_space_analysis TEXT,
  pdf_url TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE patents (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  search_id UUID REFERENCES searches(id) ON DELETE CASCADE,
  patent_id TEXT,
  title TEXT,
  abstract TEXT,
  assignee TEXT,
  similarity_score FLOAT,
  url TEXT
);
```

## Critical architectural rules (never break these)

- **FastAPI must NEVER block.** POST /jobs → insert row → trigger BackgroundTask → return job_id immediately
- **Frontend polls GET /jobs/{id} every 3 seconds.** Never await the full LangGraph run
- **No k-means, no pgvector, no Pinecone in v1.** Gemini handles clustering natively
- **No PDF generation in v1.** Use @media print CSS + browser print
- **No Google OAuth in v1.** Use anonymous sessions, store search_id in localStorage
- **All API calls use tenacity** with exponential backoff (max 3 retries)
- **Mock mode required** — MOCK_MODE=true in .env returns fake patent data, burns no API credits

## MVP definition (what v1 ships)

Input box → POST /jobs → job_id → polling stepper UI → LangGraph runs in background → results page with clusters + white space cards + markdown brief

Cut for v1: auth, PDF export, embeddings, k-means, vector DB

## Results page layout

1. Header: invention idea snippet + badges (date, N patents analyzed)
2. White Space cards (2-3, visually distinct, dark cards) — gap title, rationale, viability score
3. Prior Art Clusters grid — theme name, 1-sentence summary, top 3-4 patents with Google Patents links
4. Full markdown brief (bottom)
5. Loading stepper during generation: "Generating queries..." → "Fetching patents..." → "Clustering..." → "Analyzing gaps..." → "Writing brief..."

## Code style rules

- Python: type hints everywhere, Pydantic v2 models for all API request/response shapes
- TypeScript: strict mode, no `any`
- All async functions in backend must be properly awaited
- Never hardcode API keys — always from environment variables via config.py
- Every LangGraph node must update `current_step` in Supabase at the start of execution
- Errors go into `state["errors"]` list, never crash the graph silently

## Environment variables needed

```
GEMINI_API_KEY=
SERPAPI_KEY=
LENS_API_KEY=          # optional, Lens.org is partially free
SUPABASE_URL=
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_KEY=
MOCK_MODE=false
```

## What to build first (suggested order)

1. Backend skeleton: FastAPI + /jobs routes + Supabase connection
2. LangGraph graph wired up with mock node outputs
3. Frontend: input page + polling logic + stepper UI
4. Replace mock nodes with real implementations one by one
5. Results page UI
6. End-to-end test with real patent idea
