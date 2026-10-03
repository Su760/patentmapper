# M1 follow-up and M2a review — 2026-10-03

## Scope, base and preservation

The user approved this follow-up, implementation, isolated branches, commits and pushes. Plan and file boundaries are recorded in `tasks/todo.md`. Work began in the clean `/tmp/patentmapper-m1-review` worktree at published M1 `6863af2`, not the dirty main checkout at `92b9580`. Original main's tracked/untracked file hashes were captured outside the repository; no unpublished telemetry/export/provenance work or original tests were copied into these branches. Final comparison matched 85 of 86 snapshotted files, including every code/test file. The sole difference was two added blank lines around the diff-stat fence in original `docs/milestone-1-review.md` (mtime 2.7 seconds after the initial snapshot); its source is unconfirmed. It was left untouched and excluded from this branch, not restored over potentially concurrent work. No deployment commands, production migrations, Vercel settings or global-hook changes.

M1 follow-up: [9431701](https://github.com/Su760/patentmapper/commit/943170138e558e77c2afc757b6cac8a495136bf0) on [milestone-1-private-bounded](https://github.com/Su760/patentmapper/tree/milestone-1-private-bounded). Its [Checks run 37106987775](https://github.com/Su760/patentmapper/actions/runs/37106987775) passed both jobs before M2a branched from that tip.

M2a: [milestone-2a-reliable-saved-results](https://github.com/Su760/patentmapper/tree/milestone-2a-reliable-saved-results). Hosted M2a Checks will be inspected after publication; local evidence is recorded separately below.

## Findings and implemented fixes

- `backend/app/api/stripe_routes.py:41`: verified anonymous identities now receive 403 with permanent-account guidance before Stripe. Registered checkout still creates the mocked session. `frontend/src/lib/api.ts` propagates the guidance and homepage copy no longer promises browser-saved guests or a fixed monthly allowance.
- `backend/app/api/routes.py:115`: the worker formerly omitted `final_report` and made three separate publication writes. It now calls the single service-only `finalize_analysis` transaction, saving exact report text separately from gap analysis, citation links and retrieval coverage. A lost response cannot downgrade a committed job because failure updates match only `processing`.
- `supabase/migrations/202610030001_saved_results.sql:8`: the finalizer locks the owned search row, upserts results, replaces partial patent rows using trusted search ID/allowed columns, and publishes completion last. Duplicate patent IDs within a payload are collapsed. A repeated successful finalization is a no-op, including cached claims. The transaction rolls back all writes if any insert/update fails. Browser roles cannot execute it; existing owner-read RLS protects new fields.
- `backend/app/agents/nodes/fetcher.py:140`: retrieval now distinguishes no generated queries, every attempted provider failing, successful empty, and partial retrieval. Successful empty plus provider failure preserves the coverage warning. Failed/error-shaped responses are not silently accepted as empty; SerpAPI's documented `Success` + empty-results error message is accepted as successful empty.
- `backend/app/agents/nodes/deduplicator.py:36` and `graph.py:42`: usable evidence requires a trimmed nonempty patent ID and title or abstract. No usable patents ends as `insufficient_evidence`, skipping clustering/gap/report/relationship calls. Claims and ideation POSTs reject non-completed searches before reservation/model calls. Partial results remain usable with saved coverage warnings.
- `frontend/src/app/results/[id]/ResultsClient.tsx:1004`: reopening loads cached claims through authenticated GET. Only explicit Generate/Regenerate claims sends a paid POST. Cache errors offer Retry saved claims; every cache read has a deadline. Empty cached arrays differ from no saved analysis. Account/job lifecycle cancellation and an epoch prevent stale responses appearing after account changes.
- `ResultsClient.tsx:1150` and `frontend/src/lib/poll-job.ts:14`: simulated progress was removed. One sequential polling loop displays persisted backend stages, visible transient errors, immediate authorization failures, and a free Retry status action after stopping. Configured bounds: 3-second interval after completion, 15-second read deadline, three consecutive failures, 120 status requests. Navigation/account change aborts I/O and removes timers. A non-abortable SDK wait cannot hold the status UI forever.
- `ResultsClient.tsx:1675`: Full analysis brief renders only `final_report`. A legacy null/missing report states that it is unavailable; gap text is never substituted and no regeneration runs on read. Insufficient-evidence results show their own honest terminal state, including in the dashboard.

Two independent read-only reviewers inspected backend persistence/failure handling and frontend behavior. The backend review found no atomicity, ownership, RLS or function-permission bypass. Its no-query diagnostic and narrow missing tests were addressed. The frontend review found the manual-cache retry deadline and non-abortable session-wait gaps; both were fixed with deterministic and browser regressions. Its previously failing independent probe now passes with zero late fetches/UI callbacks. The backend reviewer reran all eight mocked saved-results regressions successfully. The failed-state policy was clarified: only *successfully published* terminal snapshots are immutable. Service-only finalization can retry a retained payload after failure; this adds no automatic graph execution/retry or recovery API.

## Reservation and failure policy

Admission remains M1's atomic, finite, rolling-window reservation policy for `job`, `claims`, and `ideation`, with a shared global cap. A whole analysis reserves one job unit before its bounded provider/model pipeline. Each explicit claims generation/regeneration and ideation request reserves its own unit. Failed paid attempts, retrieval failure, insufficient evidence, model failure and finalization failure conservatively retain their reservations. There are no blanket refunds. Provider-level finite retries are part of that admitted attempt; no new automatic paid retries were added.

Status, saved results, cached claims, Retry status and Retry saved claims are reads and consume no usage. Missing/invalid/expired/cross-user requests and non-completed-job generation denials make no reservation or paid call. Anonymous checkout denial invokes no Stripe call. Retrying *only* finalization with a retained payload neither calls a provider nor reserves again. There is no UI/automatic facility to retry the entire paid graph.

## Changed files

M1 commit: `backend/app/api/stripe_routes.py`, `backend/tests/test_checkout.py`, `backend/tests/test_private_analyses.py`, `frontend/src/lib/api.ts`, `frontend/src/app/page.tsx`, `tasks/lessons.md`, `tasks/todo.md`.

M2a:

| Area | Files |
| --- | --- |
| Pipeline/publication | `backend/app/api/routes.py`, `backend/app/agents/{graph,state}.py`, `backend/app/agents/nodes/{fetcher,deduplicator}.py`, `backend/app/services/patent_api.py` |
| Database | `supabase/migrations/202610030001_saved_results.sql` |
| Backend verification | `backend/tests/{test_saved_results,test_saved_results_sql,test_supabase_http}.py` |
| Browser | `frontend/src/app/results/[id]/ResultsClient.tsx`, `frontend/src/app/dashboard/page.tsx`, `frontend/src/lib/{api,demo,poll-job,results-config}.ts` |
| Browser/Node tests | `frontend/tests/{milestone2a-ui,polling-unit}.cjs` |
| CI/docs | `.github/workflows/checks.yml`, `README.md`, `CLAUDE.md`, `tasks/todo.md`, this review |

No keys, environment files, local databases, test credentials or browser artifacts belong in either commit.

## Migration order and setup

Use an administrative role on development/test before starting the new API/frontend. Existing installations with M1's first three migrations already applied need only migration 4. New installations apply:

1. `202610020001_private_analyses.sql`
2. `202610020002_bounded_usage.sql`
3. `202610020003_usage_snapshot.sql`
4. `202610030001_saved_results.sql`

Migration 4 adds nullable report/outcome fields and coverage warnings and creates the service-only finalizer. Existing report text is **not** fabricated/backfilled, and ownerless searches remain hidden. Keep the Supabase service key exclusively in backend configuration. Refresh PostgREST schema after migration (`NOTIFY pgrst, 'reload schema'`). No production migration was run. Stage this schema before application rollout; an old running worker cannot save the new report until updated, and a new worker without the RPC will fail closed instead of publishing partial success.

## Local verification results

These are fresh post-change results, **not** the historical 32-test baseline:

- M1 follow-up: 22 mocked backend tests; frontend lint/typecheck/build; 3 Chromium tests passed locally. Database suites were assigned to the hosted M1 jobs, both green.
- M2a backend: **52 passed, zero skipped** — **30 mocked Python/API tests**, **15 actual PostgreSQL tests**, **7 actual Supabase Auth/PostgREST tests**. Models, patent providers and Stripe were mocked throughout.
- Frontend: `npm run lint`, `npx tsc --noEmit --incremental false`, and `npm run build` passed. Existing font/layout and auth-context hook warnings remain; no new lint warnings.
- Playwright runner: **19 passed** — **13 Chromium scenarios** and **6 deterministic Node/TypeScript polling/API tests**. The Node tests use fake timers and are not described as browser evidence.
- Real PostgreSQL: exact Unicode/newline report round trip; legacy null report; injected mid-write rollback; replacement of legacy partial rows; failed-state retry; eight concurrent finalizations yield one `saved` and seven `already_finalized`; cached claims and first terminal snapshot preserved; untrusted provider IDs ignored; browser RPC denial.
- Actual local GoTrue/PostgREST: owner/cross-user/anonymous table isolation; API invalid/expired/cross-user denials; service-only finalizer permission; exact report/warning round trip through Python SDK and owner browser reads; cached reopening with zero reservation/model calls; all three paid-operation last-unit races admit exactly one of eight; quota-store outage invokes no paid work.
- Browser: exact saved report vs distinct gap text; legacy unavailable; refresh/cache GETs with zero paid POSTs; explicit regeneration; missing/initial/polling errors; stored stages without simulated advance; bounded failure pause; navigation and account-switch cancellation; initial/manual cache timeouts; insufficient evidence with no generation controls; existing signed-out demo/usage/ideation scenarios.

Development failures were observed and corrected: initial regressions failed on absent finalization RPC, swallowed provider failures, missing report and cached-claims UI; the disposable old SQL_ASCII database was recreated as UTF8 for the exact-Unicode test; TypeScript required `.abortSignal(signal)` before `.single()` for the installed Supabase builder; three new browser checks initially matched Next.js's route-announcer alert in addition to the product alert, so selectors were scoped. Final results above supersede these failures.

## Exact reproducible commands

Prerequisites: Python 3.13, Node 22, PostgreSQL client/server tools, Docker for the disposable Supabase stack. Run from the repository root. No real provider credentials are required; use a clean checkout without a production `.env`.

```bash
python3 -m venv /tmp/pm-m2a-python
/tmp/pm-m2a-python/bin/pip install -r backend/requirements.txt
cd frontend
npm ci
npx playwright install chromium
cd ..

# New private PostgreSQL cluster, no TCP listener or existing application DB.
export PATH="$(pg_config --bindir):$PATH"
PM_TEST_ROOT="$(mktemp -d /tmp/pm-m2a-pg.XXXXXX)"
mkdir "$PM_TEST_ROOT/socket"
initdb -D "$PM_TEST_ROOT/data" -U postgres --auth=trust --encoding=UTF8
pg_ctl -D "$PM_TEST_ROOT/data" -l "$PM_TEST_ROOT/server.log" \
  -o "-k $PM_TEST_ROOT/socket -p 55439 -c listen_addresses=''" -w start
createdb -h "$PM_TEST_ROOT/socket" -p 55439 -U postgres patentmapper_m1_test
export MILESTONE1_TEST_DSN="postgresql://postgres@/patentmapper_m1_test?host=$PM_TEST_ROOT/socket&port=55439"

# New disposable local Supabase project; never links a hosted project.
PM_HTTP_ROOT="$(mktemp -d /tmp/pm-m2a-http.XXXXXX)/stack"
python3 supabase/tests/local_http_setup.py "$PM_HTTP_ROOT"
export MILESTONE1_SUPABASE_CONFIG="$PM_HTTP_ROOT/test-config.json"
export MILESTONE1_DISPOSABLE_SUPABASE=1
export REQUIRE_FRONTEND_TESTS=1
export MOCK_MODE=true
cd backend
/tmp/pm-m2a-python/bin/python -m unittest discover -s tests -v
# Focused suites, if diagnosing an isolated failure:
/tmp/pm-m2a-python/bin/python -m unittest discover -s tests -p 'test_saved_results*.py' -v
/tmp/pm-m2a-python/bin/python -m unittest discover -s tests -p test_supabase_http.py -v
cd ../frontend
export NEXT_PUBLIC_SUPABASE_URL=https://example.supabase.co
export NEXT_PUBLIC_SUPABASE_ANON_KEY=test-only-public-anon-key
export NEXT_PUBLIC_API_URL=http://localhost:8000/api
npm run lint
npx tsc --noEmit --incremental false
npm run build
npx playwright test --config playwright.config.cjs
cd ..
npx --yes supabase@2.119.0 stop --workdir "$PM_HTTP_ROOT" --no-backup
pg_ctl -D "$PM_TEST_ROOT/data" -m fast -w stop
```

The historical `MILESTONE1_*` fixture variable names also configure M2a tests. The SQL suites intentionally reset schemas **only** in the guarded local database named `patentmapper_m1_test`. The Auth suite temporarily renames quota storage in its separately guarded disposable Supabase database. Generated test credentials stay outside git. CI runs PostgreSQL 17 plus a separate local Supabase job using the same setup script; the local native cluster used PostgreSQL 18.1.

## Limitations and deferred work

- **NOT RUN:** live paid patent/model/Stripe calls, production migration/rollout, Vercel preview diagnosis. Deliberately excluded; no production evidence is claimed. The prior Vercel preview failure and stop-hook uncertainty remain separate, unchanged items.
- In-process background tasks can still be lost on restart. Atomic finalization does not make the entire paid graph idempotent or recover a lost in-memory result. A prolonged processing job pauses browser monitoring rather than launching a replacement.
- Failed finalization normally records `failed`; if the database also rejects that status write, the search can remain processing. It cannot be partially marked completed by the new finalizer. Durable recovery/queues remain deferred.
- Provider coverage and report/claims quality are not established by mocked tests. Available-patent criteria are minimal usability checks, not evidence validation. Citations/claims remain inferred from abstracts; jurisdiction fidelity, sourced evidence workbench and quality evaluation remain deferred.
- Successful empty retrieval may already have consumed query-expansion/provider cost, so its job reservation remains consumed. Paid requests accepted before navigation may finish server-side after the browser cancels; cancellation is not a refund or backend cancellation API.
- Legacy rows with missing reports stay unavailable. Legacy partial rows are repaired only if an explicit service finalization with retained results is performed; there is no bulk migration, implicit adoption or automatic paid regeneration.

SDK behavior was checked against [Supabase AbortSignal docs](https://supabase.com/docs/reference/javascript/using-modifiers-abortsignal), installed TypeScript definitions, [LangGraph conditional edge reference](https://reference.langchain.com/python/langgraph/graph/state/StateGraph/add_conditional_edges), and [SerpAPI status/error documentation](https://serpapi.com/api-status-and-error-codes).
