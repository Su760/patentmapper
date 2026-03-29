# 🗺️ PatentMapper

### Know your patent landscape before you spend $10K filing.

[![Python](https://img.shields.io/badge/Python-3.13-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Next.js](https://img.shields.io/badge/Next.js-14-000000?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org)
[![LangGraph](https://img.shields.io/badge/LangGraph-multi--agent-4A90E2?style=flat-square)](https://github.com/langchain-ai/langgraph)
[![Supabase](https://img.shields.io/badge/Supabase-postgres-3ECF8E?style=flat-square&logo=supabase&logoColor=white)](https://supabase.com)
[![Stripe](https://img.shields.io/badge/Stripe-billing-635BFF?style=flat-square&logo=stripe&logoColor=white)](https://stripe.com)

---

PatentMapper is a multi-agent AI pipeline that turns a plain-English invention description into a full patent landscape brief in under 60 seconds. Describe your idea, and six specialized LangGraph agents fan out across USPTO, Lens.org, and Google Patents to fetch, deduplicate, and cluster the prior art — then synthesize a structured report identifying white space opportunities, cluster themes, competitor assignees, and a force-directed relationship graph showing how existing patents connect to each other. Everything enterprise patent tools charge $500/month for, productized into a clean freemium SaaS with a $49/month Pro tier.

---

## Screenshots

```
[Results page screenshot — white space cards + prior art cluster grid]

[Citation graph screenshot — interactive force-directed patent relationship graph]
```

---

## Features

- **Multi-agent AI pipeline** — 6 discrete LangGraph nodes in a strict DAG: query expander, patent fetcher, deduplicator, clusterer, whitespace analyzer, and reporter. Each node writes its `current_step` to Supabase so the frontend stepper reflects real pipeline progress in real time.
- **3-tier patent fetching with automatic fallback** — PatentsView (USPTO, free, primary) → Lens.org (international, secondary) → SerpAPI/Google Patents (tertiary). Queries run in parallel across all search terms with a semaphore cap of 5; each tier falls through only on failure or empty results.
- **Semantic clustering by theme** — passes the top 50 patent abstracts to Groq (Llama 3.3 70B) and asks for 3–5 named thematic clusters with IPC code tagging and competitor assignee breakdowns per cluster — no k-means, no pgvector, no embeddings infrastructure required.
- **White space analysis with viability scores** — Groq identifies gaps in the landscape with citation-format rationale ("Gap X because Cluster A patents only cover Y") and a High/Medium/Low viability score per opportunity.
- **Interactive citation/relationship graph** — after the report is written, a second Groq pass infers conceptual relationships between the top 30 patents and renders them as a force-directed canvas graph (react-force-graph-2d) with per-cluster color coding and a click-through side panel showing patent details.
- **IPC/CPC classification tagging** — CPC subgroup codes from PatentsView and IPC codes from Lens.org are normalized and surfaced per cluster.
- **Assignee/competitor breakdown** — each cluster card shows the top 3 assignees by patent count so you can see who dominates each technical area at a glance.
- **Jurisdiction filtering** — submit searches scoped to US, EP, WO, or All; PatentsView gracefully skips non-US queries and defers to Lens.org.
- **PDF export** — `@media print` CSS with a dedicated print footer; no server-side PDF generation required.
- **Freemium auth + Stripe billing** — anonymous sessions (search ID in localStorage) for unauthenticated users, magic-link auth via Supabase, 3 free analyses/month on the free tier, unlimited on Pro ($49/mo), Stripe Checkout + webhook handler for full subscription lifecycle management.

---

## Architecture

```
User Input (plain-English invention description)
        │
        ▼
  FastAPI POST /jobs  ──►  Supabase  (searches row, status: processing)
        │
        │  returns job_id immediately — never awaits the pipeline
        ▼
  BackgroundTask
  ┌─────────────────────────────────────────────────────────────────┐
  │                      LangGraph DAG                              │
  │                                                                 │
  │  1. Query Expander      invention_idea → 5–10 search queries    │
  │          │              (Groq function calling, forced list)     │
  │          ▼                                                       │
  │  2. Patent Fetcher      queries → raw_patents                   │
  │          │              PatentsView → Lens.org → SerpAPI        │
  │          │              (parallel async HTTP, semaphore=5)      │
  │          ▼                                                       │
  │  3. Deduplicator        raw_patents → deduped_patents           │
  │          │              (dedupe by patent_id, normalize fields)  │
  │          ▼                                                       │
  │  4. Clusterer           deduped_patents → clusters              │
  │          │              (Groq, top 50 abstracts, 3–5 themes,    │
  │          │               IPC codes, top assignees per cluster)  │
  │          ▼                                                       │
  │  5. Whitespace Analyzer clusters → white_space_analysis         │
  │          │              (Groq, citation-format gap analysis,    │
  │          │               viability scores)                      │
  │          ▼                                                       │
  │  6. Reporter            all state → final_report                │
  │                         + citation_links                        │
  │                         (Groq markdown synthesis, then second   │
  │                          Groq pass to infer patent relationships │
  │                          across top 30 patents)                 │
  └─────────────────────────────────────────────────────────────────┘
        │
        ▼
  Supabase  ──►  searches         (status: completed)
                 search_results   (clusters, white_space_analysis,
                                   citation_links JSONB)
                 patents          (individual rows per deduped patent)
        │
        ▼
  Next.js Frontend
        │  polls GET /jobs/{id} every 3s
        │  stepper UI tracks current_step from DB
        ▼
  Results page:
    White Space Opportunity cards (viability-scored)
    Prior Art Cluster grid (IPC codes + assignees + patent links)
    Force-directed Citation Graph (node color = cluster, click for details)
    Full markdown brief
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Frontend** | Next.js 14 App Router, TypeScript (strict), Tailwind CSS |
| **Backend** | FastAPI (fully async), Python 3.13, Pydantic v2 |
| **Agent framework** | LangGraph — strict DAG, 6 nodes, typed `LandscapeState` |
| **LLM** | Groq — Llama 3.3 70B Versatile (fast inference, generous free tier) |
| **Patent data (primary)** | PatentsView API — USPTO open data, free, CPC classification |
| **Patent data (secondary)** | Lens.org free API — international coverage, IPC classification |
| **Patent data (tertiary)** | SerpAPI — Google Patents scraping, last-resort fallback |
| **Database** | Supabase — Postgres, Row Level Security, Auth, Storage |
| **Auth** | Supabase magic link + anonymous sessions via localStorage |
| **Payments** | Stripe Checkout + webhooks, subscriptions table with RLS |
| **Graph visualization** | react-force-graph-2d — canvas, SSR-disabled, WebGL-accelerated |
| **HTTP client** | httpx (async), semaphore-gated parallel fetching |
| **Retry logic** | tenacity — exponential backoff, 2–3 attempts per API call |

---

## Getting Started

### Prerequisites

- Python 3.13+
- Node.js 18+
- A [Supabase](https://supabase.com) project (free tier works)
- At least one LLM key: [Groq](https://console.groq.com) (free tier, fast)
- Patent APIs: PatentsView works without a key at reduced rate limits

### 1. Clone

```bash
git clone https://github.com/yourusername/patentmapper.git
cd patentmapper
```

### 2. Backend setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp ../.env.example ../.env
# Edit .env — at minimum set GROQ_API_KEY + the three SUPABASE vars
```

Run the following SQL in your Supabase project's SQL editor:

```sql
CREATE TABLE searches (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  invention_idea TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'processing',
  current_step TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  error_message TEXT
);

CREATE TABLE search_results (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  search_id UUID REFERENCES searches(id) ON DELETE CASCADE UNIQUE,
  clusters JSONB,
  white_space_analysis TEXT,
  citation_links JSONB DEFAULT '[]',
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
  url TEXT
);

-- Stripe billing (skip if not using payments)
CREATE TABLE subscriptions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL UNIQUE,
  stripe_customer_id TEXT,
  stripe_subscription_id TEXT,
  plan TEXT NOT NULL DEFAULT 'free',
  status TEXT NOT NULL DEFAULT 'active',
  current_period_end TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can read own subscription" ON subscriptions
  FOR SELECT USING (auth.uid() = user_id);
```

### 3. Frontend setup

```bash
cd frontend
npm install

cat > .env.local <<EOF
NEXT_PUBLIC_SUPABASE_URL=your_supabase_url
NEXT_PUBLIC_SUPABASE_ANON_KEY=your_anon_key
NEXT_PUBLIC_API_URL=http://localhost:8000
EOF
```

### 4. Run locally

```bash
# Terminal 1 — backend API
cd backend && source .venv/bin/activate && uvicorn app.main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend && npm run dev

# Terminal 3 — Stripe webhooks (only needed for billing)
stripe listen --forward-to localhost:8000/api/stripe/webhook
```

Open [http://localhost:3000](http://localhost:3000) and submit an invention description.

> **Tip:** Set `MOCK_MODE=true` in `.env` to run the entire pipeline with synthetic patent data — no API keys consumed, full UI flow intact. Useful for frontend development and demos.

---

## Environment Variables

All variables live in `.env` at the project root (one directory above `backend/`).

| Variable | Required | Description |
|---|---|---|
| `GROQ_API_KEY` | ✅ | Groq API key — powers all 6 agent nodes (query expansion, clustering, whitespace, report, citation links) |
| `SUPABASE_URL` | ✅ | Supabase project URL |
| `SUPABASE_ANON_KEY` | ✅ | Supabase anon key — used by backend for JWT verification |
| `SUPABASE_SERVICE_KEY` | ✅ | Supabase service role key — used by Stripe webhook to bypass RLS when writing subscription rows |
| `PATENTSVIEW_KEY` | — | USPTO PatentsView API key — optional, works without it at default rate limits |
| `PATENTSVIEW_ENABLED` | — | Set `false` to skip PatentsView (default: `true`) |
| `LENS_API_KEY` | — | Lens.org API key — optional, basic queries work unauthenticated |
| `SERPAPI_KEY` | — | SerpAPI key for Google Patents — only used if PatentsView and Lens.org both fail |
| `SERPAPI_ENABLED` | — | Set `false` to disable SerpAPI fallback entirely (default: `true`) |
| `STRIPE_SECRET_KEY` | — | Stripe secret key (`sk_...`) — only needed for billing |
| `STRIPE_PRO_PRICE_ID` | — | Stripe Price ID for the $49/month Pro plan |
| `STRIPE_WEBHOOK_SECRET` | — | Stripe webhook signing secret (`whsec_...`) |
| `MOCK_MODE` | — | `true` returns synthetic patent data, burns no API credits (default: `false`) |

---

## Roadmap

- [ ] USPTO Open Data Portal integration for bulk patent downloads and citation graphs
- [ ] Technology trend timeline — patent filing velocity over time per cluster
- [ ] Claim-level analysis agent — parse independent claims and map directly to prior art
- [ ] Team workspaces — share and annotate landscapes across org members
- [ ] API access for Pro users — `POST /v1/analyze` with webhook delivery on completion

---

*Built with ❤️ for startup CTOs and inventors who deserve better than $10K/year enterprise tools.*
