# PatentMapper — Repository Guide

## Current implementation

Keep the existing stack: Next.js 16 App Router / TypeScript / Tailwind, FastAPI
plus a separate durable-job worker, a six-node LangGraph DAG, configurable Groq completions,
Lens.org with SerpAPI fallback, and Supabase Postgres/Auth. Stripe provides checkout
and subscription webhooks. Auth uses magic links; Google OAuth is not implemented.

The pipeline is expander → fetcher → deduplicator → clusterer → whitespace →
reporter, with an early exit after deduplication when evidence is insufficient.
Each node updates the saved search step. `backend/app/agents/state.py` is the state
contract, including jurisdiction, retrieval outcome, coverage warnings and inferred links.
Telemetry/export/provenance work in the original dirty main checkout is unpublished
and is not part of this branch. Preserve it; do not copy it into this milestone.

The results page includes clusters, gaps, a saved report, an SVG relationship
graph, abstract-based claims inference, and ideation. Printing uses browser CSS;
there is no server PDF renderer. No embeddings/vector database are introduced.

Keep Python type hints and Pydantic request/response models, TypeScript strict
mode without `any`, and properly awaited async calls. POST /jobs returns after
transactional quota/search/queue admission; it never executes the graph. Run
`python -m app.worker` separately. The frontend polls sequentially with bounded read-only retries and cancellation. Preserve
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

## M2a saved results and deferred work

Apply migration `202610030001_saved_results.sql` after the three M1 migrations.
After migration 5, only fenced `publish_analysis` publishes successful completion
using the queue checkpoint; `finalize_analysis` is internal-only. Terminal retries
are no-ops. A failed publication retains saved output for provider-free recovery. There are no automatic paid retries or blanket refunds.
Keep `final_report` separate from gap text; legacy missing reports stay unavailable.
Reopening claims is authenticated GET only, with explicit paid generation actions.
All-provider failure is distinct from successful empty retrieval; insufficient usable
evidence bypasses conclusion-generating nodes. Partial coverage warnings persist.

M2b1 adds owner-scoped submission keys, atomic quota/search/queue admission,
leased worker claims, heartbeats and fenced stage/checkpoint/publication writes.
Apply `202610040001_durable_jobs.sql` after M2a; stop old API/background processes first.
Queued inputs snapshot pipeline version/model/mock/fallback settings; credentials
remain runtime-only. Never change version-1 execution semantics incompatibly without
a migration/version strategy. Expired running jobs become interrupted and retain usage;
never replay the paid graph automatically. Only checkpointed final output can recover
publication without providers. Service direct mutation bypasses are denied, except
authorized cached claims updates. See `docs/milestone-2b1-review.md`.

Full stage replay, automatic paid retries/refunds, new providers, claim-to-quote matrices,
and quality evaluation remain deferred. Existing
claims/citation relationships are inferred, not verified source evidence. See
`docs/milestone-2a-review.md` and `tasks/todo.md`.

## M3a persisted evidence

Evidence v1 lives in `patents.evidence` as exact per-provider observations. Preserve provider
record IDs separately from supplied publication identifiers; internal IDs are provider-qualified.
Dedup merges observations only for the same provider record, never infers cross-provider identity.
Search snippets, abstracts, title-only text and synthetic text have distinct types. Priority,
filing and publication dates remain separate; no fallback filing years or unsupported trend charts.
Lens jurisdiction filters are not applied; record that limitation. SerpAPI submits country filters.

Migration 6 (`202610040002_evidence_workbench.sql`) preserves RLS/fences and atomically publishes
saved evidence. Coordinate a stop of API/workers before applying it: queued execution v1 upgrades
to v2, running v1 interrupts, finalizing v1 remains publishable as legacy output. New worker
execution requires v2; unknown execution versions fail without graph/provider calls. Missing
historical evidence stays NULL. Never backfill or regenerate it during a read. Future evidence
versions are opaque to this reader. Keep v2 checkpoints evidence-versioned and validated.

The owner-authorized GET `/api/jobs/{id}/evidence` and cached overlap reads are free and provider-free.
Only validated saved record IDs may populate clusters/graph/overlap references. Exclusions must be
visible and deterministic. Conceptual relationships and overlap wording are AI inference from
limited available text, never retrieved patent claims. New overlap caches use a v1 envelope with
claims and exclusion warnings; historical list caches remain readable. See the M3a review.


## Release hardening

Overlap rows require string IDs/title/explanation/differentiators, a string array
of inferred aspects and a high/medium/low/none enum. Malformed rows and cache warning
envelopes are excluded with visible warnings; valid legacy lists stay free/read-only.
The client also validates response JSON before rendering. Never auto-regenerate.

Use Node 22 LTS, `npm ci` and an explicit `npm run lint`; Next 16 does not lint during
build. Async page params and React 19 ref initialization are required. Account-keyed
home/dashboard state must retain unmount cancellation, owner-scoped idempotency and
private data clearing; usage results remain token/attempt-scoped. No cache opt-in
for private reads. Keep the cookie override scoped to the existing SSR package to
preserve its session format, and retain raw/chunked-cookie/sign-out regressions.
See `docs/release-hardening-review.md` for dependency limitations and verification.
