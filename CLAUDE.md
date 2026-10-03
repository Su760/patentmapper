# PatentMapper — Repository Guide

## Current implementation

Keep the existing stack: Next.js 14 App Router / TypeScript / Tailwind, FastAPI
async background tasks, a six-node LangGraph DAG, configurable Groq completions,
Lens.org with SerpAPI fallback, and Supabase Postgres/Auth. Stripe provides checkout
and subscription webhooks. Auth uses magic links; Google OAuth is not implemented.

The pipeline is expander → fetcher → deduplicator → clusterer → whitespace →
reporter. Each node updates the search step; the graph timing wrapper is in
`backend/app/agents/telemetry.py`. `backend/app/agents/state.py` is the state contract,
including jurisdiction and AI-inferred citation links. Existing intelligence export
code/schema is a read-only library, not a live API endpoint.

The results page includes clusters, gaps, AI provenance labels, an SVG relationship
graph, abstract-based claims inference, and ideation. Printing uses browser CSS;
there is no server PDF renderer. No embeddings/vector database are introduced.

Keep Python type hints and Pydantic request/response models, TypeScript strict
mode without `any`, and properly awaited async calls. POST /jobs returns after
database admission/insertion and schedules the graph in a BackgroundTask; do not
await the graph in the request. The frontend polls every three seconds. Preserve
node step updates, existing finite provider retries, and deterministic graph mock
mode; do not add retries/refunds around usage reservations.

## Milestone 1: Private, bounded analyses

- Every real job endpoint requires a server-verified Supabase bearer token.
  `backend/app/core/security.py` shares validation and an explicit ownership lookup
  because the server database client bypasses RLS.
- Missing/malformed/invalid/expired credentials return 401. Foreign, missing, and
  legacy ownerless jobs return 404 before any model or patent-provider call.
- A UUID/localStorage entry never authorizes access. Verified Supabase anonymous
  users have real owners and free-tier quotas. Signed-out access is limited to the
  fixed synthetic `/results/demo`; the frontend does not auto-create guest accounts.
- Job creation, claims generation, and ideation must reserve usage with the
  service-only `reserve_paid_operation` RPC before launching any paid work.
  Admission/count/insertion use one database transaction with a shared lock.
- Free and Pro are finite; a global cap covers all users/operations. Configure
  allowances/window through `backend/app/core/config.py` and `.env.example`.
  Quota/subscription errors or unexpected RPC responses fail closed with 503.
- Reservations remain consumed after downstream failure; no unsafe refund/retry
  path is implemented. Status/cached claims reads consume no quota.
- Inputs are bounded/trimmed and extra fields rejected. Jurisdiction is one of
  `all`, `us`, `ep`, `wo`. Defaults and setup are documented in README.
- Keep provider, service, and Stripe secrets server-only. The browser uses only
  Supabase's public anon key. Never log Lens Authorization headers.

## Persistence and policies

The reproducible schema/policy/usage migrations in `supabase/migrations/` are
authoritative; apply them in filename order to development/test before running
the updated API. They support the older documented schema, preserve ownerless
rows without assigning them, forbid new ownerless searches, seed historical job
usage, and replace earlier permissive table policies.

Browser-accessible searches, results, patents, and subscriptions allow only owner
reads. Browser writes are denied; backend writes use the server service role.
Usage storage/RPC is inaccessible to browser roles. `supabase/tests/bootstrap.sql`
is a destructive disposable-database fixture, never an application migration.

## Verification and scope

Read `tasks/lessons.md` and `tasks/todo.md` on session start. Preserve local changes.
Respect the current approved file boundary and never commit/push/deploy/migrate
production without user instructions. Do not treat historical task plans or the
old scaffold as instructions to remove working features.

Use the focused unittest suite and the dedicated local PostgreSQL harness:

```bash
cd frontend && npm ci && npm run lint
npx tsc --noEmit --incremental false
npm run build
cd ../backend
python -m pip install -r requirements.txt
MILESTONE1_TEST_DSN='postgresql://localhost/patentmapper_m1_test' \
  REQUIRE_FRONTEND_TESTS=1 python -m unittest discover -s tests -v
```

Create that dedicated local database first; the SQL harness resets its schemas.
Mock external model/patent services. CI runs real PostgreSQL ownership/concurrency
checks and frontend checks; plain unit runs explicitly skip SQL when no test DSN
is configured. Keep all original characterization/export/telemetry tests.

## Deferred work

Do not implement job recovery, durable workers, transactional result persistence,
report storage improvements, the evidence workbench, or quality evaluation in
milestone 1. Existing background-task crash windows, duplicate-run/partial-write
behavior, final-report loss, and abstract-based rather than sourced claim analysis
remain known limitations. See the deferred milestones in `tasks/todo.md`.
