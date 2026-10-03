# Milestone 1 closure review

Scope: private, bounded analyses only. No deployment, merge, production migration, job recovery, report redesign, or evidence workbench. User approved implementation, independent review, fixes, and a feature-branch commit/push.

## Recovered state and publication boundary

The original checkout was `main` at `92b9580c3b857cccd591f8d6eef2df60a4df4736`, with an empty index and pre-existing local changes. The original **32 tests** are a historical baseline. The previous milestone report recorded **54 post-change tests** (32 original, 13 HTTP/browser-contract, nine real PostgreSQL), frontend checks/build, and signed-out Chromium QA. Supabase Auth/PostgREST was previously unverified.

The original dirty tree and all original tests are preserved. Publication uses the separate worktree `/tmp/patentmapper-m1-review`, branch `milestone-1-private-bounded`. It excludes telemetry/graph instrumentation, intelligence export modules/tests/schema, provenance metadata/UI/styles, unused provider deletion, `.claude/`, `.driftlens/`, local environment files and credentials. A saved pre-milestone snapshot was used for three-way removal of unrelated hunks from the published ResultsClient and patent wrapper.

The configured Groq helper, setting, four node call sites, and original model-selection regression are included as prerequisites: milestone routes use that working configuration. Security tests have independent fixtures so publishing them does not require the unrelated telemetry suite. The npm lockfile adds Playwright and reconciles stale force-graph entries already absent from package.json; the application stack is unchanged.

## Independent findings and fixes

Two read-only reviewers examined backend and frontend. Line references below identify the pre-fix checkout where applicable.

| Finding                                                                                                                                     | Evidence and fix                                                                                                                                                                                                                                                                        |
| ------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Display counted searches, ignored failed reservations, hardcoded 30 days, ignored expired/anonymous Pro rules, and hid outages as Free/zero | `backend/app/api/stripe_routes.py:65–97`. Migration 3 supplies one service-only snapshot definition used inside atomic admission and by authenticated status. Dashboard/pricing display all three operation counts, configured limits and rolling window; failures show retry controls. |
| Every signed-in dashboard user was labeled Pro, and upgrade banner promised unlimited usage                                                 | `frontend/src/app/dashboard/page.tsx:198,244`. Use verified status; remove unlimited and browser-history claims.                                                                                                                                                                        |
| Pricing ignored HTTP errors and allowed stale account responses                                                                             | `frontend/src/app/pricing/page.tsx:37–44`. Shared authenticated API error handling and token-scoped/cancelled usage state prevent fallback or cross-session stale display.                                                                                                              |
| Ideation errors were console-only; one spinner ID could not represent two pending cards                                                     | `frontend/src/app/results/[id]/ResultsClient.tsx:995,1060–1068`. Per-gap pending/error state, duplicate-click guard, visible actionable failures, and independent finally cleanup.                                                                                                      |
| Database failures appeared as empty history                                                                                                 | `frontend/src/app/dashboard/page.tsx:126,370`. Display the failure, clear loading, suppress the false empty-history message.                                                                                                                                                            |
| Malformed JSON returned 422 before invalid credentials could return 401                                                                     | `backend/app/api/routes.py:26` dependency/body decoding order. Parse bounded models after authentication; ideation also checks ownership first. Regression proves foreign malformed/invalid bodies remain 404 with no reservation/provider call.                                        |

Review and tests confirm owner-filtered service-role lookups on every job-specific endpoint, no invalid-token fallback, hidden legacy ownerless rows, service-only quota functions, independent browser RLS, no browser writes, and removal of Lens Authorization-header logging. The two reviewers checked the fixes again; their confirmed follow-ups were corrected.

Regression reproduction before fixes: the new usage tests failed with `KeyError: 'usage'` and `AssertionError: 200 != 503`; invalid-token malformed JSON failed with `AssertionError: 422 != 401`. The corrected tests pass. During closure verification a direct-call fixture exposed changed positional argument order, which was restored; the first Chromium run exposed an ambiguous alert locator, which was scoped to the usage error.

## Reservation policy

- A successfully reserved **landscape job**, **claims generation**, or **ideation request** consumes one unit of its per-user operation allowance and the shared global operation allowance. Internal pipeline model/patent calls and bounded retries belong to that admitted job. This is an admission budget, not a dollar/token meter.
- Limits and rolling days come from server configuration (`FREE_*_LIMIT`, `PRO_*_LIMIT`, `GLOBAL_OPERATION_LIMIT`, `QUOTA_WINDOW_DAYS`). Both display and admission use `paid_usage_snapshot`: the same reservation rows, timestamp cutoff, active/unexpired Pro rule and anonymous-user Free policy. Admission retains its transaction-scoped advisory lock around snapshot and insert. A displayed count is an as-of snapshot; refresh to update it.
- Failed model attempts, malformed model output, failed search insertion/persistence and background failures **remain consumed**. Retry is a new reservation. If a committed reservation response is lost, denial may still consume a unit. No blanket refunds or compensating races were added.
- Missing/invalid/expired credentials, foreign/missing/ownerless jobs, invalid inputs, missing patents for claims, and quota denials do not reserve or start paid work. Quota/subscription-store failures fail closed. Reads of status, cached claims, browser-owned results and usage do not consume units. The fixed browser demo consumes none. Authenticated mock-mode jobs still consume a reservation.
- Verified Supabase anonymous sessions own their data and have Free limits. The UI does not create anonymous accounts; signed-out visitors get only `/results/demo`. UUID possession never authorizes access. Legacy ownerless rows are retained and hidden, never silently assigned.
- Historical searches are seeded as job reservations. Usage survives search deletion; deleting an account retains its contribution to the global budget. Browser callers cannot choose identity, plan, limits, or reservation timestamps.

## Migration and setup order

Install `backend/requirements.txt` (including the already-used Stripe SDK), then apply these files **in order** with an administrative migration role to a development/test Supabase database:

1. `supabase/migrations/202610020001_private_analyses.sql`: schema compatibility, owner-required new rows, replaces existing policies on searches/results/patents/subscriptions; owner-only reads, server-only writes.
2. `supabase/migrations/202610020002_bounded_usage.sql`: reservation ledger, idempotent historical job seeding, atomic service-only reservation RPC.
3. `supabase/migrations/202610020003_usage_snapshot.sql`: authoritative accounting snapshot and reservation function using it; both functions remain service-only.

Review existing policies before migration 1; its replacement is intentional to eliminate permissive OR-policy bypass. Never apply `supabase/tests/bootstrap.sql` to an application database: it resets schemas. No production migrations were applied during this work.

Set finite quotas from `.env.example` before offering plans. Only public Supabase URL/anon key belong in `NEXT_PUBLIC_*`; service, model, patent and Stripe keys stay backend-only. Configure magic-link redirects. Anonymous sign-ins need enabling only if preserving/provisioning verified anonymous sessions; the public demo needs no Auth session.

## Reproducible verification

All model/patent providers were mocked. No paid calls were used for evidence.

### Local worktree and isolated branch

- Original preserved worktree: **65 backend tests passed, no skips**: 32 original + 15 private/browser-contract + 10 PostgreSQL + three usage-status + five Auth/PostgREST.
- Published branch: **34 backend tests passed, no skips**: 19 mocked (including configured-model prerequisite), ten PostgreSQL, five Auth/PostgREST. The 31 unrelated original tests remain in the original checkout.
- Chromium: **three tests passed** covering no-network demo/private-link denial, authoritative counts and outage/history errors, concurrent ideation loading plus 402/401/503 errors and retry cleanup.
- Frontend lint, TypeScript and production build passed. Existing font-placement and Auth-context dependency warnings remain; Browserslist data is stale. npm reports existing dependency vulnerabilities; dependency upgrades are outside this bounded milestone.

Install and run frontend checks with deterministic public test configuration (use the same environment for build and Playwright):

```sh
cd frontend
npm ci
export NEXT_PUBLIC_SUPABASE_URL=https://example.supabase.co
export NEXT_PUBLIC_SUPABASE_ANON_KEY=test-only-public-anon-key
export NEXT_PUBLIC_API_URL=http://localhost:8000/api
npm run lint
npx tsc --noEmit --incremental false
npm run build
npx playwright install chromium
npx playwright test --config playwright.config.cjs
```

For real PostgreSQL only, create a dedicated local database named **patentmapper_m1_test**, then:

```sh
cd backend
python -m pip install -r requirements.txt
export MILESTONE1_TEST_DSN='postgresql://postgres:YOUR_LOCAL_TEST_PASSWORD@127.0.0.1:55432/patentmapper_m1_test'
REQUIRE_FRONTEND_TESTS=1 python -m unittest discover -s tests -p test_milestone1_sql.py -v
```

The harness rejects remote hosts and other database names, resets its disposable public/auth schemas, and applies all migrations. It verifies actual PostgreSQL role/RLS isolation, owner/foreign HTTP behavior via a SQL adapter, last-unit races, global caps, expiry, legacy rows, RPC privileges and store failures. Auth is mocked in this layer.

For real **Auth + PostgREST + Supabase Python SDK**, install Docker, Node/npm, and `psql`; from the repository root choose a new unused temp path:

```sh
python supabase/tests/local_http_setup.py /tmp/patentmapper-m1-http
export MILESTONE1_SUPABASE_CONFIG=/tmp/patentmapper-m1-http/test-config.json
export MILESTONE1_DISPOSABLE_SUPABASE=1
cd backend
python -m unittest discover -s tests -p test_supabase_http.py -v
# With BOTH database variables set, the full branch suite runs without skips:
REQUIRE_FRONTEND_TESTS=1 python -m unittest discover -s tests -v
cd ..
npx --yes supabase@2.119.0 stop --workdir /tmp/patentmapper-m1-http --no-backup
```

The setup starts a separate local CLI stack, enables anonymous Auth only there, applies migrations and stores generated test credentials outside the repo. Do not point it at an existing project. Tests create disposable users; authenticate with actual Auth; send browser-role requests through actual PostgREST; test expired signed tokens, owner/cross-user/anonymous access, denied reads/writes/RPC identity forgery, and eight concurrent HTTP requests per operation admitting exactly one last-unit attempt. Quota-table rename returns 503 without provider work. Failed paid attempts remain visible in actual usage-status responses. Test users/reservations are cleaned up.

CI runs two jobs: PostgreSQL + mocked regressions + frontend/browser checks, and a separate disposable Auth/PostgREST job. The first deliberately skips the Auth class because the second runs it against a real stack. Inspect the branch's **Checks** workflow; no deployment job is included.

## Separate Stop-hook issue

The previous inspection looked at Claude configuration, not the active Codex hook file. `~/.codex/hooks.json:41` contains a Stop command `echo '<session-completion reminder>'`; the next hook invokes `node ~/.codex/hooks/on-stop.js`. A safe standalone execution of **only** the echo returned exit 0, zero stderr, stdout beginning `Session complete.`; parsing those actual bytes as JSON produced `Expecting value: line 1 column 1 (char 0)`. This command emits plain text where the reported runner expects JSON.

Read-only searches of retained session/runtime logs did not recover the exact engine error from the prior report. The echo-output failure is reproduced; correlation to that specific engine event remains uncertain. No memory/dream hook was manually executed; no global hooks or approval rules were changed. This application milestone does not resolve the global hook configuration.

## Remaining limitations and deferred milestones

NOT RUN: live model/patent end-to-end calls, production configuration/policies, deployment and production migration. They were intentionally excluded. Local disposable PostgreSQL and Auth/PostgREST verification are separate from those checks.

Deferred: durable job recovery/idempotency and report persistence/reliability; evidence workbench/provenance/citation fidelity; quality evaluation and labeled benchmarks. Existing billing lifecycle completeness (including hardcoded checkout redirects), exact provider cost accounting, retention guarantees and dependency upgrades remain outside this milestone. Startup migration log reminders in `backend/app/main.py:27` are stale; the checked-in migration order above is authoritative.

## Changed files / diff stat

<!-- diffstat-start -->
```text
.env.example                                       |  24 +-
 .github/workflows/checks.yml                       |  81 ++++
 CLAUDE.md                                          | 253 ++++--------
 README.md                                          | 196 ++++-----
 backend/app/agents/nodes/clusterer.py              |   7 +-
 backend/app/agents/nodes/expander.py               |   7 +-
 backend/app/agents/nodes/reporter.py               |  11 +-
 backend/app/agents/nodes/whitespace.py             |   7 +-
 backend/app/api/routes.py                          | 160 ++++----
 backend/app/api/stripe_routes.py                   |  50 +--
 backend/app/core/config.py                         |  16 +
 backend/app/core/security.py                       |  54 +++
 backend/app/services/llm.py                        |  10 +
 backend/app/services/patent_api.py                 |   1 -
 backend/app/services/usage.py                      |  59 +++
 backend/requirements.txt                           |   1 +
 backend/tests/security_fixtures.py                 |  69 ++++
 backend/tests/test_groq_model_configuration.py     |  50 +++
 backend/tests/test_milestone1_sql.py               | 289 +++++++++++++
 backend/tests/test_private_analyses.py             | 315 ++++++++++++++
 backend/tests/test_supabase_http.py                | 172 ++++++++
 backend/tests/test_usage_status.py                 |  54 +++
 docs/milestone-1-review.md                         | 168 ++++++++
 frontend/.eslintrc.json                            |   3 +
 frontend/.gitignore                                |   6 +
 frontend/package-lock.json                         | 455 +++------------------
 frontend/package.json                              |   1 +
 frontend/playwright.config.cjs                     |  14 +
 frontend/src/app/dashboard/page.tsx                | 124 +++---
 frontend/src/app/page.tsx                          |  31 +-
 frontend/src/app/pricing/page.tsx                  |  30 +-
 frontend/src/app/results/[id]/ResultsClient.tsx    | 125 +++++-
 frontend/src/components/UsageSummary.tsx           |  60 +++
 frontend/src/lib/api.ts                            | 105 +++--
 frontend/src/lib/demo.ts                           |  47 +++
 frontend/src/lib/use-usage.ts                      |  47 +++
 frontend/tests/milestone1-ui.cjs                   | 184 +++++++++
 .../migrations/202610020001_private_analyses.sql   |  89 ++++
 supabase/migrations/202610020002_bounded_usage.sql |  79 ++++
 .../migrations/202610020003_usage_snapshot.sql     |  81 ++++
 supabase/tests/bootstrap.sql                       |  15 +
 supabase/tests/local_http_setup.py                 |  34 ++
 tasks/lessons.md                                   |   2 +
 tasks/todo.md                                      | 125 +++++-
 44 files changed, 2764 insertions(+), 947 deletions(-)
```
<!-- diffstat-end -->
