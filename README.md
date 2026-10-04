# 🗺️ PatentMapper

### Know your patent landscape before you spend $10K filing.

[![Python](https://img.shields.io/badge/Python-3.13-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Next.js](https://img.shields.io/badge/Next.js-14-000000?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org)
[![LangGraph](https://img.shields.io/badge/LangGraph-multi--agent-4A90E2?style=flat-square)](https://github.com/langchain-ai/langgraph)
[![Supabase](https://img.shields.io/badge/Supabase-postgres-3ECF8E?style=flat-square&logo=supabase&logoColor=white)](https://supabase.com)
[![Stripe](https://img.shields.io/badge/Stripe-billing-635BFF?style=flat-square&logo=stripe&logoColor=white)](https://stripe.com)

---

PatentMapper is a multi-agent AI pipeline that turns a plain-English invention description into a full patent landscape brief in under 60 seconds. Describe your idea, and six specialized LangGraph agents fan out across Lens.org and Google Patents to fetch, deduplicate, and cluster the prior art — then synthesize a structured report identifying white space opportunities, cluster themes, competitor assignees, and a force-directed relationship graph showing how existing patents connect to each other. Everything enterprise patent tools charge $500/month for, productized into a clean freemium SaaS with a $49/month Pro tier.

---

## Screenshots

```
[Results page screenshot — white space cards + prior art cluster grid]

[Citation graph screenshot — interactive force-directed patent relationship graph]
```

---

## Features

- **Multi-agent AI pipeline** — 6 discrete LangGraph nodes in a strict DAG: query expander, patent fetcher, deduplicator, clusterer, whitespace analyzer, and reporter. Each node writes its `current_step` to Supabase so the frontend stepper reflects real pipeline progress in real time.
- **2-tier patent fetching with automatic fallback** — Lens.org (international, primary) → SerpAPI/Google Patents (fallback). Queries run in parallel across all search terms with a semaphore cap of 5; the fallback tier only fires on failure or empty results.
- **Semantic clustering by theme** — passes the top 50 patent abstracts to Groq (GPT-OSS 120B by default) and asks for 3–5 named thematic clusters with IPC code tagging and competitor assignee breakdowns per cluster — no k-means, no pgvector, no embeddings infrastructure required.
- **White space analysis with viability scores** — Groq identifies gaps in the landscape with citation-format rationale ("Gap X because Cluster A patents only cover Y") and a High/Medium/Low viability score per opportunity.
- **Interactive citation/relationship graph** — after the report is written, a second Groq pass infers conceptual relationships between the top 30 patents and renders them as an interactive SVG relationship graph with per-cluster color coding and a click-through side panel showing patent details.
- **IPC classification tagging** — IPC codes from Lens.org are normalized and surfaced per cluster.
- **Assignee/competitor breakdown** — each cluster card shows the top 3 assignees by patent count so you can see who dominates each technical area at a glance.
- **Jurisdiction filtering** — submit searches scoped to US, EP, WO, or All.
- **PDF export** — `@media print` CSS with a dedicated print footer; no server-side PDF generation required.
- **Private analyses + Stripe billing** — Supabase magic-link auth, owner-only access, atomic usage reservations for jobs/claims/ideation, and finite free/Pro allowances. Verified Supabase anonymous sessions can own private jobs; signed-out visitors see only a fixed synthetic demo. A job UUID or localStorage entry never grants access.

---

## Architecture

```
User Input (plain-English invention description)
        │
        ▼
  FastAPI POST /jobs  ──►  Supabase  (quota + owned job + durable queued inputs)
        │
        │  returns job_id immediately — never awaits the pipeline
        ▼
  Separate worker (atomic claim, lease, heartbeat, fencing)
  ┌─────────────────────────────────────────────────────────────────┐
  │                      LangGraph DAG                              │
  │                                                                 │
  │  1. Query Expander      invention_idea → 5–10 search queries    │
  │          │              (Groq function calling, forced list)     │
  │          ▼                                                       │
  │  2. Patent Fetcher      queries → raw_patents                   │
  │          │              Lens.org → SerpAPI                      │
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
  durable output checkpoint → fenced publish_analysis transaction ──► searches (completed / insufficient_evidence)
                 search_results   (clusters, white_space_analysis,
                                   final_report, citation_links, coverage warnings)
                 patents          (individual rows per deduped patent)
        │
        ▼
  Next.js Frontend
        │  bounded sequential GET /jobs/{id}, 3s between requests
        │  stepper UI tracks current_step from DB
        ▼
  Results page:
    White Space Opportunity cards (viability-scored)
    Prior Art Cluster grid (IPC codes + assignees + patent links)
    Force-directed Citation Graph (node color = cluster, click for details)
    Saved full markdown brief + cached claims (GET only on reopen)
```

---

## Tech Stack

| Layer                      | Technology                                                       |
| -------------------------- | ---------------------------------------------------------------- |
| **Frontend**               | Next.js 14 App Router, TypeScript (strict), Tailwind CSS         |
| **Backend**                | FastAPI (fully async), Python 3.13, Pydantic v2                  |
| **Agent framework**        | LangGraph — strict DAG, 6 nodes, typed `LandscapeState`          |
| **LLM**                    | Groq — GPT-OSS 120B by default (configurable via `GROQ_MODEL`)   |
| **Patent data (primary)**  | Lens.org free API — international coverage, IPC classification   |
| **Patent data (fallback)** | SerpAPI — Google Patents scraping                                |
| **Database**               | Supabase — Postgres, Row Level Security, Auth, Storage           |
| **Auth**                   | Supabase magic link; verified anonymous users; fixed public demo |
| **Payments**               | Stripe Checkout + webhooks, subscriptions table with RLS         |
| **Graph visualization**    | Interactive SVG graph with AI-inferred relationships             |
| **HTTP client**            | httpx (async), semaphore-gated parallel fetching                 |
| **Retry logic**            | tenacity — exponential backoff, 2–3 attempts per API call        |

---

## Getting Started

### Prerequisites

- Python 3.11–3.13 (pinned dependencies do not currently support Python 3.14)
- Node.js 18+
- A [Supabase](https://supabase.com) project (free tier works)
- At least one LLM key: [Groq](https://console.groq.com) (free tier, fast)
- Patent APIs: a valid Lens.org bearer token; SerpAPI fallback if enabled

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

Stop old API/background processes before applying migration 5. Apply the checked-in migrations to a **development/test Supabase project** before starting the updated API and separate worker. Review existing policies first: migration 1 replaces policies on searches, results, patents, and subscriptions with owner-only reads and server-only writes.

```bash
# Run from the repository root, with a development database URL set externally.
psql "$PATENTMAPPER_DEV_DATABASE_URL" -v ON_ERROR_STOP=1 -f supabase/migrations/202610020001_private_analyses.sql
psql "$PATENTMAPPER_DEV_DATABASE_URL" -v ON_ERROR_STOP=1 -f supabase/migrations/202610020002_bounded_usage.sql
psql "$PATENTMAPPER_DEV_DATABASE_URL" -v ON_ERROR_STOP=1 -f supabase/migrations/202610020003_usage_snapshot.sql
psql "$PATENTMAPPER_DEV_DATABASE_URL" -v ON_ERROR_STOP=1 -f supabase/migrations/202610030001_saved_results.sql
psql "$PATENTMAPPER_DEV_DATABASE_URL" -v ON_ERROR_STOP=1 -f supabase/migrations/202610040001_durable_jobs.sql
psql "$PATENTMAPPER_DEV_DATABASE_URL" -v ON_ERROR_STOP=1 -c "NOTIFY pgrst, 'reload schema'"
```

Alternatively, execute those five files in order in that project's SQL editor. The migrations support the older documented schema, add citation/claims fields, retain legacy ownerless rows without assigning ownership, and seed historical job usage. New ownerless searches are forbidden. Do not run `supabase/tests/bootstrap.sql` against an application database; it resets schemas and is only for the disposable test harness.

### 3. Frontend setup

```bash
cd frontend
npm install

cat > .env.local <<EOF
NEXT_PUBLIC_SUPABASE_URL=your_supabase_url
NEXT_PUBLIC_SUPABASE_ANON_KEY=your_anon_key
NEXT_PUBLIC_API_URL=http://localhost:8000/api
EOF
```

### 4. Run locally

```bash
# Terminal 1 — backend API
cd backend && source .venv/bin/activate && uvicorn app.main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend && npm run dev

# Terminal 3 — durable worker (required for private analyses)
cd backend && source .venv/bin/activate && python -m app.worker

# Terminal 4 — Stripe webhooks (only needed for billing)
stripe listen --forward-to localhost:8000/api/stripe/webhook
```

Open [http://localhost:3000](http://localhost:3000). Signed-out users can view the synthetic demo; sign in with a Supabase magic link to submit a private invention description. Configure the Auth redirect allowlist for `/auth/callback`. The frontend does not automatically create anonymous accounts. Existing verified anonymous sessions work with the same owner policies and free limits; if you enable anonymous sign-ins in Supabase, configure its abuse controls as well.

> **Tip:** Set `MOCK_MODE=true` in `.env` to run the landscape pipeline with synthetic patent data. Authentication and quotas still apply; claims and ideation remain model-backed and quota-gated. The signed-out demo runs entirely in the browser and consumes no database or provider usage. Useful for frontend development and demos.

---

## Environment Variables

All variables live in `.env` at the project root (one directory above `backend/`).

| Variable                | Required | Description                                                                                                                       |
| ----------------------- | -------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `GROQ_API_KEY`          | ✅       | Groq key — powers query expansion, clustering, whitespace, report/links, claims, and ideation                                     |
| `GROQ_MODEL`            | —        | Groq model identifier (default: `openai/gpt-oss-120b`)                                                                            |
| `SUPABASE_URL`          | ✅       | Supabase project URL                                                                                                              |
| `SUPABASE_ANON_KEY`     | ✅       | Supabase public anon key; frontend also needs NEXT_PUBLIC_SUPABASE_ANON_KEY                                                       |
| `SUPABASE_SERVICE_KEY`  | ✅       | Server-only service key — backend persistence, owner-filtered reads, usage RPC, and billing writes; never expose as NEXT_PUBLIC_* |
| `LENS_API_KEY`          | —        | Lens.org bearer token; needed for Lens requests                                                                                   |
| `SERPAPI_KEY`           | —        | SerpAPI key for Google Patents — only used if Lens.org fails                                                                      |
| `SERPAPI_ENABLED`       | —        | Set `false` to disable SerpAPI fallback entirely (default: `true`)                                                                |
| `STRIPE_SECRET_KEY`     | —        | Stripe secret key (`sk_...`) — only needed for billing                                                                            |
| `STRIPE_PRO_PRICE_ID`   | —        | Stripe Price ID for the $49/month Pro plan                                                                                        |
| `STRIPE_WEBHOOK_SECRET` | —        | Stripe webhook signing secret (`whsec_...`)                                                                                       |
| `MOCK_MODE`             | —        | `true` makes the landscape graph synthetic; claims/ideation still use the model (default: `false`)                                |

---

## Milestone 1: Private, bounded analyses

Every real job endpoint validates the access token with Supabase Auth. Missing, malformed, invalid, or expired credentials return 401; another user's, nonexistent, or legacy ownerless job returns 404 before model/patent calls. Browser table reads use ownership RLS; browser writes are denied even for the owner. Only the backend can write, and its service key remains server-only. The public `/results/demo` route uses fixed synthetic data and never accesses private rows.

Dashboard and pricing read `paid_usage_snapshot` through the authenticated API: the same plan, reservation ledger, and configured rolling window used by enforcement. Claims and ideation have their own allowances. Status outages display a retryable error, never a fabricated Free/zero allowance.

The service-only `reserve_paid_operation` RPC locks admission, checks subscription status and rolling usage, and inserts a consumed reservation in one transaction. This works across concurrent workers and users. Quota/subscription-store failure returns 503 and starts no paid work; malformed admission responses also fail closed. Reservations are not refunded after provider, insert, or background-task failures. A service-wide cap also bounds account cycling; these are operation allowances, not an exact dollar-cost meter.

Default allowances in `.env.example` / `backend/app/core/config.py`:

| Operation         | Free / verified anonymous | Pro |
| ----------------- | ------------------------: | --: |
| Landscape job     |                         3 | 100 |
| Claims generation |                         3 | 100 |
| Ideation          |                         6 | 200 |

`GLOBAL_OPERATION_LIMIT=1000` applies across all users and operations in a rolling `QUOTA_WINDOW_DAYS=30` window. `FREE_*_LIMIT` and `PRO_*_LIMIT` configure individual allowances. Setting a limit to zero disables its operation. Cached claims/status reads do not consume usage. Historical jobs count toward usage; ownership is never inferred from their IDs. Configure the caps before offering paid plans. Startup SQL log messages are historical reminders, not automatic migrations; the checked-in migration files are authoritative.

Invention input is trimmed and limited to 20–2000 characters. Ideation titles/descriptions are trimmed, nonempty, and limited to 200/4000 characters. Those limits are configurable through the corresponding variables in `.env.example`; keep the frontend's existing 20–2000 character UI consistent if changing the server limits. Jurisdiction must be `all`, `us`, `ep`, or `wo`. Unsupported fields/inputs return 422 before paid work.

## Reliable saved results (M2a)

`final_report` is saved separately from `white_space_analysis` and displayed in Full analysis brief. Older rows without it show an unavailable state; opening a result never regenerates a report or claims. Claims are loaded through the authenticated cached GET; generation/regeneration requires an explicit action and consumes one claims reservation, including failed paid attempts. Anonymous sessions must sign in/create a permanent account before Stripe checkout.

The browser displays persisted stages, uses one sequential status request at a time, times out reads after 15 seconds, pauses after three consecutive failures or 120 status requests, and cancels requests/timers on navigation or account changes. Retry status and Retry saved claims perform free reads only. Limits are in `frontend/src/lib/results-config.ts`.

If all provider attempts fail, the search fails explicitly. Successful retrieval with no usable patents (nonempty ID plus title or abstract) finishes as `insufficient_evidence` without clustering/gap/report/claims generation. Partial retrieval retains available evidence with saved coverage warnings. The original semaphore of five and finite provider retries remain.

The service-only `publish_analysis` RPC atomically saves result/patent rows and completion using a fenced durable output checkpoint. The legacy `finalize_analysis` RPC is internal-only; service callers cannot execute it. Successful publication retries are no-ops and preserve cached claims. Browser RLS covers saved reports.

## Durable jobs (M2b1)

POST `/api/jobs` requires a UUID `submission_key`, invention text and jurisdiction. Server-verified owner + key + identical normalized payload returns the original job, including after a lost response, without another reservation. Changed payload with the same key returns 409. The browser saves unconfirmed keys per account in session storage, restores inputs after reload and reuses the key when you retry. It never automatically resubmits a paid request. Changing inputs creates a separate paid analysis; clearing browser storage or changing tabs can lose retry identity, so check the dashboard before starting over.

Admission reserves quota, creates the owned search and queues its inputs in one transaction. Quota or insert failures roll everything back; a response timeout can still mean admission committed, so retry with the same key. The API never runs the graph. Start a **separate long-running worker** with the same server configuration (from `backend/`):

```bash
python -m app.worker
# Separate terminal/process:
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Queued work survives API/worker restarts. A worker claims with an expiring token and checks ownership before stages/provider calls. Expired running jobs become `interrupted`, including on free owner status reads when workers are offline. They are never automatically rerun. Paid attempts retain their reservation; a fresh analysis consumes new usage. A crash after the last provider response but before its durable checkpoint is still interrupted.

Valid complete output is checkpointed before publication. `finalizing` jobs can recover from that snapshot without provider calls. Publication attempts are bounded by worker concurrency and lease cadence; fair claim ordering prevents a persistently failing publication from monopolizing the queue. Persistent database/schema errors require operator attention; there is no automatic paid replay or exactly-once external-call guarantee. In-flight provider requests may already have been charged when a worker loses its lease.

`WORKER_CONCURRENCY` bounds each process; all workers must share `WORKER_MAX_ACTIVE` for the global database claim cap. Configure timings in `.env.example`. Lease tokens fence stage/status/output writes; old RPC/direct service mutation bypasses are denied. Legacy owned `processing` jobs become interrupted during migration; ownerless legacy records remain untouched and hidden. Downgrading to the old background-task API is incompatible with these fences; roll forward without deleting queued inputs or saved output. See [M2b1 review](docs/milestone-2b1-review.md) for exact verification and migration/rollback details.

## Checks and local database regressions

```bash
cd frontend && npm ci
npm run lint
npx tsc --noEmit --incremental false
npm run build
cd ../backend
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

The last command skips SQL integration unless `MILESTONE1_TEST_DSN` is set and skips Auth/PostgREST unless a disposable local Supabase config is provided. To include the PostgreSQL checks locally, create a disposable PostgreSQL database named exactly `patentmapper_m1_test` on a local cluster:

```bash
createdb patentmapper_m1_test
cd backend
MILESTONE1_TEST_DSN='postgresql://localhost/patentmapper_m1_test' \
  REQUIRE_FRONTEND_TESTS=1 python -m unittest discover -s tests -v
```

Use your local administrative PostgreSQL user/credentials in the DSN when needed. The SQL harness refuses remote hosts or any other database name, then resets the `public`/`auth` schemas in that disposable database, applies the real migrations, and tests role-based browser access, API ownership, concurrent last-unit admission, fail-closed storage errors, Pro/anonymous bounds, policy upgrades, and legacy seeding. Supabase Auth and model/patent providers are mocked. This verifies real PostgreSQL transactions/RLS, not a live Supabase Auth/PostgREST deployment. CI runs the same tests with PostgreSQL 17 plus frontend lint/typecheck/build, and requires the browser API contract test instead of silently skipping it.

## Deferred milestones

- Further execution reliability: full stage replay, automatic paid retries/refunds and any broader recovery design. M2b1 admits durable jobs and recovers publication only; interrupted paid graphs remain interrupted.
- Evidence workbench: sourced claim/citation evidence, provenance review, jurisdiction fidelity, and research workflows.
- Quality evaluation: labeled retrieval/analysis benchmarks and hallucination/citation checks.

_Built with ❤️ for startup CTOs and inventors who deserve better than $10K/year enterprise tools._

Closure review, exact local Auth/PostgREST setup, browser checks, accounting policy, and publication evidence: [Milestone 1 review](docs/milestone-1-review.md).

M2a behavior, exact disposable database/browser commands, test evidence, and remaining limits: [Milestone 2a review](docs/milestone-2a-review.md).
