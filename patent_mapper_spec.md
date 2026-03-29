# Patent Landscape Mapper: Architecture & Build Spec

This document serves as the architectural blueprint and build specification for the **Patent Landscape Mapper**, outlining the system design, database schemas, agent workflows, and MVP scope.

---

## 1. Architecture Critique

**What's great:**
* **LangGraph for sequentially complex workflows:** This is the perfect use case for LangGraph. A strict DAG (Directed Acyclic Graph) provides predictable state management and observability.
* **Component stack:** Next.js 14 + FastAPI + Supabase is an industry-standard modern stack that balances rapid development with scale. 

**What's missing:**
* **Async Task Execution (Crucial):** An AI flow hitting Google Patents, Lens.org, embedding APIs, and LLMs sequentially will take *minutes*. If your Next.js app waits for a synchronous HTTP response from FastAPI, the request *will* timeout. You need an architecture where FastAPI immediately returns a `job_id`, and the Next.js frontend polls (or uses Server-Sent Events / WebSockets) to check the status.
* **State Persistence for graph debugging:** LangGraph has built-in state persistence (`checkpointer`). You should save the intermediate graph states in a Postgres table so you can debug *where* a search failed and resume it.

**What's over-engineered:**
* **K-means Clustering Node:** Using embeddings + k-means for ~50-100 patents is slightly over-engineered when using Gemini 2.0 Flash, which has a 1-million token context window. You can pass the JSON of 100 patent abstracts directly into Gemini and ask it to natively output semantic clusters. This reduces pipeline fragility (no need to manage k, tune embeddings, or write custom clustering heuristics).

---

## 2. Folder & File Structure

A simple Monorepo using folder-based separation is best. It reduces friction for AI coding agents (like Claude Code) that can read the whole context in one workspace.

```text
patent-mapper/
├── .env                  # Shared environment variables
├── frontend/             # Next.js 14 App Router
│   ├── src/
│   │   ├── app/
│   │   │   ├── page.tsx            # Landing page + Search input
│   │   │   ├── dashboard/page.tsx  # User's history of searches
│   │   │   └── results/[id]/page.tsx # Polling UI & Final Report display
│   │   ├── components/             # UI: Cards, Steppers, Loaders
│   │   └── lib/
│   │       ├── supabase.ts         # Supabase client
│   │       └── api.ts              # API calls to backend
│   ├── package.json
│   └── tailwind.config.ts
├── backend/              # FastAPI
│   ├── app/
│   │   ├── main.py                 # FastAPI application & entrypoint
│   │   ├── api/
│   │   │   └── routes.py           # POST /jobs, GET /jobs/{id}
│   │   ├── agents/
│   │   │   ├── state.py            # LangGraph state TypedDict
│   │   │   ├── graph.py            # LangGraph node routing & compilation
│   │   │   └── nodes/              # Individual agent logic
│   │   │       ├── expander.py
│   │   │       ├── fetcher.py
│   │   │       └── ...
│   │   ├── core/
│   │   │   └── config.py           # ENV loaders
│   │   └── services/
│   │       └── patent_api.py       # SerpAPI / Lens API wrappers
│   └── requirements.txt
└── README.md
```

---

## 3. Supabase Database Schema

Kept normalized but optimized for JSON storage where graph flexibility is needed.

```sql
-- Searches (Jobs)
CREATE TABLE searches (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  invention_idea TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'processing', -- 'processing', 'completed', 'failed'
  current_step TEXT, -- 'fetching_patents', 'analyzing', etc. for UI feedback
  created_at TIMESTAMPTZ DEFAULT NOW(),
  error_message TEXT
);

-- Search Results (The populated landscape)
CREATE TABLE search_results (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  search_id UUID REFERENCES searches(id) ON DELETE CASCADE UNIQUE,
  clusters JSONB,            -- [{ "theme_name": "...", "description": "...", "patent_ids": [...] }]
  white_space_analysis TEXT, -- Markdown output
  pdf_url TEXT,              -- URL to Supabase Storage bucket
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Patents (Deduplicated cache for the search)
CREATE TABLE patents (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  search_id UUID REFERENCES searches(id) ON DELETE CASCADE,
  patent_id TEXT,            -- e.g., 'US10234567B2'
  title TEXT,
  abstract TEXT,
  assignee TEXT,
  similarity_score FLOAT,    -- Optional: relevance to original idea
  url TEXT
);
```

---

## 4. LangGraph Agent Design

### State Definition (`state.py`)
```python
from typing import TypedDict, List, Dict, Any

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

### The Nodes (Input -> Output)
1. **Query Expander Node**: 
   - *In:* `invention_idea`
   - *Out:* `search_queries` (via Gemini 2.0 Flash function calling to force a List).
2. **Patent Fetcher Node**: 
   - *In:* `search_queries`
   - *Out:* `raw_patents` (Parallel async HTTP requests to Google Patents/Lens).
3. **Deduplicator Node**: 
   - *In:* `raw_patents`
   - *Out:* `deduped_patents` (Filter out shared `patent_number`s, normalize JSON fields).
4. **Clusterer Node**: 
   - *In:* `deduped_patents`
   - *Out:* `clusters` (Pass top ~50 patents into Gemini, ask to categorize into 3-5 distinct thematic clusters with titles and assigned `patent_number` lists).
5. **White Space Analyzer Node**: 
   - *In:* `invention_idea`, `clusters`
   - *Out:* `white_space_analysis` (Prompt: "Compare the invention idea to the existing clusters. Identify 2 severe technical gaps not addressed by current prior art").
6. **Report Writer Node**: 
   - *In:* `invention_idea`, `clusters`, `white_space_analysis`
   - *Out:* `final_report` (Markdown synthesis).

---

## 5. Top 3 Technical Risks & Mitigations

1. **Risk: Brittle external scraping/APIs failing.** Free API tiers (Lens, SerpAPI) have strict rate limits and occasionally change JSON formats or timeout.
   - *Mitigation:* Implement strict schema validation (Pydantic) for API responses. Use `tenacity` in Python for exponential backoff and retries. Build a "mock" mode for local development to avoid burning API credits.
2. **Risk: Next.js Vercel Timeout (504 Error).** Vercel serverless functions time out after 10-60 seconds. This workflow will take multiple minutes.
   - *Mitigation:* The FastAPI endpoint must just insert a row into the `searches` table, trigger a FastApi `BackgroundTasks` (or Celery queue), and return `{"status": "processing"}` instantly. The React frontend should poll `GET /api/searches/{id}` every 3 seconds for updates.
3. **Risk: LLM Hallucinated "Empty" White Spaces.** The LLM might claim a whitespace exists simply because it missed a detail in a patent abstract.
   - *Mitigation:* Force the LLM to use heavy citation mechanics (e.g., "Gap X is viable because Cluster A (Patents [US123, US456]) only covers Y, and Cluster B..."). Use system prompts that heavily penalize unsupported claims.

---

## 6. MVP Scope (What to cut for v1)

To ship fast, cut the following for V1:
- **Cut PDF Generation:** Generating clean PDFs in Python/Node is notoriously frustrating. Instead, render beautiful Markdown in the React UI and add a "Print Page" button utilizing `@media print` CSS rules.
- **Cut Vector Database / k-means Embeddings:** Do not bother setting up Pinecone/pgvector yet. Pass up to 50 deduplicated patent abstracts directly in one prompt to Gemini 2.0 Flash to do the clustering organically.
- **Cut Google Auth:** Start with local magic links (via Supabase) or anonymous sessions storing `search_id` in local storage, just to prove the workflow works.
- **MVP Definition:** A Next.js input box -> FastAPI kicks off LangGraph (Gemini query expansion -> Google Patents via SerpAPI -> Gemini Clustering -> Gemini Whitespace) -> Next.js displays a beautiful loading stepper -> renders Markdown results.

---

## 7. Results Page UI Design

A dense, high-signal, Dashboard-style layout.

**Hero / Header:**
- Title: `Landscape Brief: {Invention Idea snippet}`
- Badges: `Generated on {Date}` | `X Patents Analyzed`

**Section 1: White Space Opportunities (The "Aha!" Moment)**
- Visually distinct (e.g., dark mode cards on a light page).
- 2-3 prominent cards.
- *Card contents:* 
  - **Gap Title** (e.g., "Real-time edge processing absent")
  - **Description** (1-2 sentences on why it represents an opportunity)
  - **Confidence Score:** e.g., "High Viability" (generated by the LLM).

**Section 2: Prior Art Clusters**
- A masonry or CSS Grid of cards.
- *Card contents (Per Theme):*
  - **Cluster Theme:** e.g., "Database indexing methods"
  - **Summary:** 1 sentence wrap-up of what this group does.
  - **Top Patents:** A mini unstyled list of 3-5 patents formatted as `[US12345] Dynamic DB...` (clickable to Google Patents).

**Section 3: Full Synthesis**
- A beautiful standard markdown render of the full `final_report`.

**Sticky Action Bar (Bottom right or Top Right):**
- [ Share ] [ Print to PDF / Save ]
- During generation, this is replaced by the **State Stepper** (`Fetching patents...` etc).
