# M2b1 — durable admission and safe restart handling

Base: published `milestone-2a-reliable-saved-results` at `668b628` (remote verified; no newer tip). Branch: `milestone-2b-durable-jobs`. Work was isolated in `../patentmapper-worktrees/milestone-2b-durable-jobs`; all 86 snapshotted files in the original dirty main checkout remain byte-for-byte unchanged. No production migration, merge, deployment, paid provider call, Vercel setting change or global-hook change was performed.

## Implemented behavior

- `POST /api/jobs` requires a UUID `submission_key`. Verified owner, normalized invention and jurisdiction enter one service-only transaction: quota reservation, owned search, durable queue input. Any insertion/quota-store failure rolls back all three. The API launches no graph/provider work.
- `(owner, submission_key)` is unique. An identical payload returns the same job regardless of changed allowance/settings; a different payload conflicts with 409. A commit followed by a lost response is recovered by retrying the same key. A 503 reports an unconfirmed outcome rather than claiming no work was admitted.
- Browser retries retain an account-scoped key before sending, including after timeout/reload. No automatic paid resubmission occurs. Definite success clears it; changed input creates a new submission. Account changes/navigation cancel outstanding requests. Signed-out demo and M1 ownership/credential policy remain intact.
- The separate worker atomically claims jobs, with per-process/global concurrency limits, an expiring UUID token, heartbeat, RPC timeout and execution timeout. Inputs persist invention/jurisdiction, pipeline version, configured model, mock mode and fallback flag. Secrets are runtime-only. The six nodes write fenced stages; each Groq/Lens/SerpAPI request boundary checks its live lease. Existing provider concurrency/retry limits remain.
- Queued work survives API/worker restarts. Expired running work becomes `interrupted`, never requeued. Status reads verify ownership before expiring a dead worker using database time, so an offline worker cannot leave the UI claiming active execution indefinitely.
- Only valid complete output is checkpointed. `finalizing` jobs recover by publishing the saved output, without building the graph or calling providers. Results, patents and successful status publish atomically; retries cannot duplicate rows, replace terminal reports or erase cached claims. Failed writes retain the checkpoint.
- Running/finalizing tokens fence heartbeats, stages, failure, checkpoint and publication. Stale tokens cannot renew or write. Browser roles cannot access queue/checkpoints or invoke admission/worker RPCs. Legacy finalizer execution and direct service-role mutation/`TRUNCATE` bypasses are closed; separately authorized claims-cache updates still work.
- Results/dashboard distinguish queued, running, saving output, interrupted and terminal states. Active status monitoring remains sequential, bounded and cancellable; status retries are free. Interrupted-state guidance explains that a fresh analysis consumes new usage.

## Independent review and fixes

A fresh read-only reviewer inspected persistence, authorization, failure handling and browser retries. Primary made all fixes. Reviewer re-read them and reported no remaining confirmed in-scope defects; reviewer did not independently execute tests.

| Finding | Fix and evidence |
| --- | --- |
| `supabase/migrations/202610040001_durable_jobs.sql:24`: Legacy ownerless `processing` rows violate the existing NOT VALID owner constraint on UPDATE. | Migration 5 only interrupts **owned** legacy jobs; upgrade regression seeds both owned and ownerless M2a rows and confirms hidden ownerless rows remain untouched. |
| `supabase/migrations/202610040001_durable_jobs.sql:133`: Empty/invalid reports could become permanently unpublishable checkpoints and monopolize worker capacity. | Checkpoint and publication share validation. Fair oldest-claim ordering replaces permanent recovery priority. Real SQL tests reject bad snapshots and show a later queued job wins after a failed publication retry. |
| `backend/app/api/routes.py:228`: A dead worker could leave stored status `running` forever without a replacement worker. | Free owner-authorized status RPC expires its lease using database time; dashboard uses the bounded status poller. Real Auth/PostgREST and browser tests cover this. |
| `supabase/migrations/202610040001_durable_jobs.sql:249`: Direct service mutations could bypass fencing by deleting/moving rows or truncating tables. | Row guards cover insert/update/delete and moved parent IDs; service TRUNCATE privileges revoked. SQL and actual PostgREST checks deny bypasses, while claims cache remains writable. |

## Migration and startup

Apply only to the intended development/test database during setup. Stop old API/background-task processes and workers first; old code cannot safely run alongside this schema. Existing installations with migrations 1–4 need **only migration 5**. Do not replay earlier usage-seeding migrations against newer durable jobs.

1. `202610020001_private_analyses.sql`
2. `202610020002_bounded_usage.sql`
3. `202610020003_usage_snapshot.sql`
4. `202610030001_saved_results.sql`
5. `202610040001_durable_jobs.sql`

Use an administrative migration owner (tested with PostgreSQL and Supabase `postgres`), not `service_role`. Preserve function ownership: audited SECURITY DEFINER RPCs write as that trusted owner. Migration 5 is a forward migration, not a repeatedly executable bootstrap. It issues the PostgREST schema-reload notification. Keep browser credentials limited to the public Supabase URL/anon key; API and worker receive server-only service/provider keys.

From separate terminals/processes, after installing `backend/requirements.txt` and configuring the repository-root `.env`:

```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

```bash
cd backend
python -m app.worker
```

The worker requires a long-running process; an API-only installation will retain accepted jobs as queued. Default settings are in `.env.example`: two tasks per worker, global maximum two live leases, 60-second lease, 10-second heartbeat, five-second RPC timeout, two-second queue poll and 600-second graph timeout. **All workers must use the same `WORKER_MAX_ACTIVE`.** Heartbeat plus RPC timeout must fit inside the lease. Pipeline-version 1 semantics must remain compatible with saved inputs; a future incompatible graph/config change needs a version/migration strategy.

## Reservation and recovery policy

| Durable state / event | Action | Usage |
| --- | --- | --- |
| Admission transaction aborts | No job/queue/reservation commits | None |
| Same owner/key/payload submitted again | Return existing job | No additional reservation |
| Queued | Any worker may claim after restart | Original reservation retained |
| Running with live token | Execute once within this claimed attempt; heartbeat | Original reservation retained |
| Running lease expires / process dies before checkpoint | Mark interrupted; never replay graph | Retained, even if no provider call can be confirmed |
| Complete output checkpoint committed | Recover publication only after lease expiry | No extra reservation or provider calls |
| Publication rollback/lost response | Keep checkpoint; idempotent fenced retry | No extra reservation or provider calls |
| Failed/interrupted job | User may explicitly submit a fresh key | New reservation for fresh analysis |
| Status, saved report or cached claims reads | Read saved data only | Free |
| Claims generation/regeneration or ideation | Existing M1 authorization/reservation | One operation reservation; failures remain consumed |

Publication retries are database-only, throttled by lease expiry and global capacity, and fairly ordered against queued jobs. Persistent schema/storage problems need operator repair; output stays private and unpublished until publication succeeds. There is no partial-stage replay, automatic replay of an interrupted paid graph or blanket refund. Existing bounded provider retries within one live execution remain unchanged. A crash after a provider response but before its checkpoint remains interrupted. Network requests already in flight may have been charged after cancellation; **exactly-once external execution is not claimed**.

Rollback is not a blind application revert: the old API omits keys, creates unqueued processing rows and calls an RPC whose service execution is now revoked. Prefer a coordinated forward fix. Do not drop the queue, checkpoint or usage ledger, reset expired jobs to queued, or bypass fencing to make old code run. Owner/key deduplication lasts while the job exists; administrative deletion removes its key and does not refund the reservation.

## Verification — actual post-change results

Fresh pre-change baseline: **45 passed**, one class skipped (real Auth/PostgREST not yet configured). Earlier 32-test and M2a summaries were historical, not post-change evidence.

Final local run: **72 passed, zero skips** on Python 3.11, disposable PostgreSQL 18 and local Supabase Auth/PostgREST. Breakdown: **34 mocked/contract tests**, **29 real PostgreSQL tests** (including five worker/process integration tests), and **9 actual Auth/PostgREST tests**. Paid model/patent/Stripe services were mocked or synthetic throughout.

Coverage includes transaction rollback; eight simultaneous duplicates and last-unit admissions; committed-but-lost responses; changed-payload conflict; owner/guest/cross-user/anonymous policies; service function/table permissions; two competing worker processes; SIGKILL/restart during execution and after checkpoint; stale token writes/renewal; heartbeat failure cancellation; persisted execution options through all six real graph nodes; checkpoint validation, publication rollback/retry/no duplication and fairness; quota-store outage without launched work; all M1/M2a regressions.

Frontend: **24 passed** (**17 Chromium**, **7 deterministic Node tests**), lint and TypeScript passed, production build passed. Browser regressions include uncertain POST/reload key reuse, account switch cancellation/new key, queued/running/finalizing/interrupted states and dashboard cleanup, plus previous report/claims/guest/error tests. Existing lint warnings remain in `layout.tsx:26` (font placement) and `auth-context.tsx:35` (dependency); they are outside this milestone. Browserslist data warning is unchanged.

Exact commands used (from repository root unless `cd` is shown):

```bash
python3.11 -m venv /tmp/pm-m2b-py311
/tmp/pm-m2b-py311/bin/pip install -r backend/requirements.txt
cd frontend
npm ci
npm run lint
npx tsc --noEmit --incremental false
NEXT_PUBLIC_SUPABASE_URL=https://example.supabase.co \
NEXT_PUBLIC_SUPABASE_ANON_KEY=test-only-public-anon-key \
NEXT_PUBLIC_API_URL=http://localhost:8000/api npm run build
npx playwright test --config playwright.config.cjs
cd ..
```

Disposable PostgreSQL setup used only a local Unix socket:

```bash
export PATH=/opt/homebrew/opt/postgresql@18/bin:$PATH
mkdir -p /tmp/pm-m2b-pg-socket
initdb -D /tmp/pm-m2b-pg -A trust --encoding=UTF8
pg_ctl -D /tmp/pm-m2b-pg -l /tmp/pm-m2b-pg.log \
  -o '-k /tmp/pm-m2b-pg-socket -p 55438 -h ""' start
createdb -h /tmp/pm-m2b-pg-socket -p 55438 patentmapper_m1_test
```

Disposable local Supabase setup requires Docker, Node and `psql`; use a new empty temporary directory:

```bash
/tmp/pm-m2b-py311/bin/python supabase/tests/local_http_setup.py /tmp/pm-m2b-http
PYTHONPATH=backend \
MILESTONE1_TEST_DSN='postgresql:///patentmapper_m1_test?host=/tmp/pm-m2b-pg-socket&port=55438' \
MILESTONE1_DISPOSABLE_SUPABASE=1 \
MILESTONE1_SUPABASE_CONFIG=/tmp/pm-m2b-http/test-config.json \
MOCK_MODE=true REQUIRE_FRONTEND_TESTS=1 \
/tmp/pm-m2b-py311/bin/python -m unittest discover -s backend/tests -v
```

The SQL harness deliberately resets `public`/`auth` only in a local database named `patentmapper_m1_test`. Actual Supabase tests use real GoTrue/PostgREST and their separate disposable database. Generated test credentials stay outside git. On Linux, use the installed PostgreSQL tools and a local test DSN instead of the Homebrew path. CI uses Python 3.13/PostgreSQL 17 and runs Auth/PostgREST separately; `.github/workflows/checks.yml` discovers all new tests.

Development failures resolved before the final run:

- Python 3.14 dependency installation: `configured Python interpreter version (3.14) is newer than PyO3's maximum supported version (3.13)`; used supported Python 3.11 locally, retaining Python 3.13 CI.
- Initial new-test command from the wrong directory: `ModuleNotFoundError: No module named 'app'`; corrected import path/cwd as shown above.
- Expected pre-implementation SQL failures: `function public.admit_analysis(...) does not exist`; implemented migration/RPCs.
- SQL fixture initially parsed PostgreSQL `t/f` as JSON; corrected boolean decoding.
- A DELETE-fence assertion targeted no result row (`AssertionError: RuntimeError not raised`); seeded a real durable result and reran successfully.

No required local check remains NOT RUN. Live paid-provider integration, production migration/deployment, Windows worker support, Vercel preview diagnosis and global-hook diagnosis were intentionally NOT RUN and are not claimed verified. Hosted application CI passed both jobs at `cbb1ea1`: [Checks run 37187110777](https://github.com/Su760/patentmapper/actions/runs/37187110777) (63 backend/SQL tests in the main job, 9 Auth/PostgREST tests separately, 24 frontend tests and lint/typecheck/build). The source is unchanged by the final handoff documentation commit; its CI is checked separately and linked in the final handoff. The GitHub-connected Vercel preview check failed; its cause is unverified and diagnosis remains a separate task. No Vercel commands/settings were used to change it.

## Changed files and deferred work

- Database: new migration 5.
- Backend: job admission/status route, worker settings, new `services/jobs.py`, `services/execution.py`, `worker.py`, typed lease state, six fenced nodes and paid-call guards in `llm.py`/`patent_api.py`.
- Frontend: API submission key, new `submission.ts`, bounded poller active states, homepage retry/account handling, results and dashboard status UX.
- Tests: new durable SQL/worker/process fixtures, retained/adapted M1/M2a/real Auth regressions, new submission and Chromium M2b tests.
- Handoff/config: `.env.example`, CI workflow, README, CLAUDE, task plan and this review. No credentials, local databases, `.env`, unrelated work or generated build cache are committed.

Deferred: full stage replay, automatic paid retries/refunds, new providers, evidence workbench and quality evaluation. Queue/checkpoint retention and operator observability remain basic; an operator must keep the worker process alive and repair persistent database failures. Browser session storage can be cleared or unavailable (in-memory retry then survives only the current page); check the dashboard before deliberately creating a new submission after losing retry identity. Existing claims/citation relationships are inferred rather than verified source evidence.
