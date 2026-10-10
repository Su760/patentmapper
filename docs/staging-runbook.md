# PatentMapper staging launch runbook

Prepared 2026-10-09 for draft PR #1 on `release-hardening-m3a`, based on verified
`6db6050456fefd514ac08b47c68e0062056ced2b`. Use the final reviewed PR head for all
three processes. This is a launch procedure, not evidence of a hosted launch.
No deployment, hosted migration, resource creation or paid request was performed
while preparing it. The [release handoff](release-hardening-review.md) records
existing synthetic verification and remaining development advisories.

## Targets: verified facts and missing decisions

| Component | Verified configuration | Launch gap |
| --- | --- | --- |
| Frontend | Vercel project `patentmapper`, ID `prj_tuIqJdi6FeMUNPv870p5yrTZxAVN`, owner/team `su2976` / `team_4iAvucq5oMB84DAFG0Un4BIb`. Original `frontend/.vercel/project.json` and PR's Vercel bot agree. | Latest baseline preview failed (`dpl_GpyBB9XcuobtKikvMncVZ8Hakq4y`). No working staging URL or effective dashboard build settings verified. |
| API | Original local frontend config points to a loopback API. `backend/Dockerfile` runs Uvicorn on port 8000. | No existing hosted staging service, HTTPS origin, host/platform or service ID found in verified configuration. |
| Worker | `backend/app/worker.py` is a separate long-running process; same backend source/image can run it with a command override. | No existing staging worker service, supervisor or restart policy verified. Vercel frontend hosting cannot run this queue worker. |
| Database/Auth | Local config names Supabase project `poldwmkfuokuvepqftzl`; read-only account inventory identifies it as `PatentMapper`, `us-east-1`, **INACTIVE**. | Its purpose is not verified as non-production. No separate active staging project was identified. Do not restore, migrate or reuse it without owner confirmation. |
| Prior test stack | Disposable loopback Supabase and PostgreSQL were used for release verification, then stopped. | These are test fixtures, not durable staging targets. |

Before launch, the owner must record an existing non-production Supabase project
reference, frontend staging origin, API service/origin, worker service, supervisor,
and the same commit/image digest for all three processes. Missing entries above
are blocking launch inputs, not suggested new paid resources. Do not copy the
original checkout's environment files: that checkout has live-mode configuration.

## Vercel access and build diagnosis

On 2026-10-09, read-only `vercel teams ls --format json` exposes only
`code-8ed4` (`team_ulCA7sMBBRv2jU4xRQSjASGe`), not the owning team above.
`vercel whoami --format json` returns `Error: Not authorized`. PR comments expose
the project/deployment identity but no build log or fatal build error. The known
deployment-inspect failures were **not repeated**. There is no confirmed repository
cause and no speculative `vercel.json`, project-link or root-directory change.

**Exact access action:** an existing authorized member of `su2976` must open the
[failed deployment](https://vercel.com/su2976/patentmapper/GpyBB9XcuobtKikvMncVZ8Hakq4y),
open **Build Logs**, and supply the install/build output through the first fatal
error, with secrets redacted. Also supply the effective project Root Directory,
framework preset, Node version, install/build/output commands and commit SHA.
Alternatively, authenticate the CLI using an existing account with read access to
this project and its build logs; do that deliberately outside this task. No paid
seat/resource or account/project setting change is authorized by this runbook.
See Vercel's [build log instructions](https://vercel.com/docs/deployments/logs) and
[access roles](https://vercel.com/docs/rbac/access-roles).

Only after access changes or logs arrive should inspection resume, against the
exact failed deployment. Compare the first fatal error with the repository facts:

- The Next app and lockfile are under `frontend/`; no root package manifest or
  checked-in `vercel.json` exists. `frontend/next.config.mjs` exports an empty config.
- Package scripts are `next build`, `next start`, and separate `eslint src`.
  `frontend/package.json` requires Node 22 (minimum 22.14), Next 16.4 and React 19.3.
- CI installs from the frontend lockfile and runs lint, typecheck and build there.
  Local/CI success does not establish that Vercel used equivalent settings.

Treat those as comparison facts, not proof of a root-directory or Node error.
Fix only a repository cause demonstrated by logs. A later successful Vercel build
and browser smoke are required before calling the hosted frontend ready.

## Migration state: inspect before applying anything

Use only the owner-confirmed non-production project's administrative SQL console
or approved migration connection. Match its project reference to the frontend,
API and worker configuration before any write. Do not use production credentials,
the inactive project above by assumption, or `supabase/tests/bootstrap.sql`.

Run these read-only checks first:

```sql
SELECT current_database(), current_user,
       to_regclass('supabase_migrations.schema_migrations') AS migration_history;
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public' AND (
  (table_name = 'searches' AND column_name IN ('user_id','lease_expires_at')) OR
  (table_name = 'search_results' AND column_name IN
    ('final_report','claims_analysis','evidence_version','requested_jurisdiction','analysis_warnings')) OR
  (table_name = 'patents' AND column_name = 'evidence') OR
  table_name IN ('analysis_queue','usage_reservations'))
ORDER BY table_name, ordinal_position;
SELECT c.relname, c.relrowsecurity
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='public' AND c.relname IN
  ('searches','search_results','patents','subscriptions','usage_reservations','analysis_queue');
SELECT tablename, policyname, roles, cmd, qual
FROM pg_policies WHERE schemaname='public'
AND tablename IN ('searches','search_results','patents','subscriptions');
SELECT p.proname, pg_get_function_identity_arguments(p.oid) AS arguments,
       has_function_privilege('service_role',p.oid,'EXECUTE') AS service_execute,
       has_function_privilege('anon',p.oid,'EXECUTE') AS anon_execute,
       has_function_privilege('authenticated',p.oid,'EXECUTE') AS browser_execute
FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
WHERE n.nspname='public' AND p.proname IN
  ('reserve_paid_operation','paid_usage_snapshot','admit_analysis','claim_analysis',
   'read_analysis_status','heartbeat_analysis','checkpoint_analysis','publish_analysis','finalize_analysis');
```

If the migration history relation exists, inspect
`SELECT version FROM supabase_migrations.schema_migrations ORDER BY version;`.
Otherwise require the operator's applied-migration ledger and compare actual schema,
policies and function definitions with the SQL files. An absent history table does
not mean the migrations were never applied. A column list alone cannot certify RPC
definitions; inspect `pg_get_functiondef` for mismatches. Do not blindly rerun the
non-idempotent durable/evidence migrations.

Expected complete state: six ordered migrations below; all six listed application
tables have RLS enabled; browser policies permit only owner reads; usage/queue
storage is not browser-accessible. Listed public API/worker RPCs are executable by
service_role, not anon/authenticated. `finalize_analysis` is internal-only and is
also denied to service_role; publication uses `publish_analysis`.

1. `202610020001_private_analyses.sql`
2. `202610020002_bounded_usage.sql`
3. `202610020003_usage_snapshot.sql`
4. `202610030001_saved_results.sql`
5. `202610040001_durable_jobs.sql`
6. `202610040002_evidence_workbench.sql`

This staging preparation introduces no migration. An M3a database needs none; an
M2b database needs only 6. A fresh database needs all six. Apply only a confirmed
missing suffix, in order, through the chosen staging migration mechanism. Stop
API and workers before migrations 5/6. Migration 1 replaces protected-table policies;
compare existing policies before an authorized application. Migration 6 upgrades
queued v1 inputs, interrupts running v1 work without replay/refund, and preserves
finalizing v1 snapshots for provider-free legacy publication. No provenance backfill,
mixed-version workers or blind application downgrade.

After applying a confirmed suffix, rerun the checks and inspect queue state:

```sql
SELECT state, execution_inputs->>'version' AS version,
       execution_inputs->>'mock_mode' AS mock_mode, count(*)
FROM public.analysis_queue GROUP BY 1,2,3 ORDER BY 1,2,3;
```

For synthetic acceptance, use a clean staging queue with no pre-existing live jobs.
Changing current environment settings does **not** rewrite saved execution inputs.
Do not start a worker on unknown queued work. Record and resolve it with the owner;
do not delete, replay or refund it as a shortcut.

## Environment inventory (names only)

Configure values through the existing host's secret/config mechanism; do not put
them in git, the PR or captured logs. API and worker must use the same staging
Supabase project and compatible execution settings. This table intentionally
contains names and purposes only, not environment values.

| Process/purpose | Variable names |
| --- | --- |
| Frontend public build-time settings | `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_API_URL` |
| API and worker database/auth | `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY` |
| Synthetic/live mode and provider selection | `MOCK_MODE`, `SERPAPI_ENABLED`, `GROQ_MODEL` |
| Live providers, withheld during synthetic acceptance | `GROQ_API_KEY`, `LENS_API_KEY`, `SERPAPI_KEY` |
| Worker capacity and timing | `WORKER_CONCURRENCY`, `WORKER_MAX_ACTIVE`, `WORKER_LEASE_SECONDS`, `WORKER_HEARTBEAT_SECONDS`, `WORKER_RPC_TIMEOUT_SECONDS`, `WORKER_POLL_SECONDS`, `WORKER_EXECUTION_TIMEOUT_SECONDS` |
| Finite rolling operation limits | `FREE_JOB_LIMIT`, `PRO_JOB_LIMIT`, `FREE_CLAIMS_LIMIT`, `PRO_CLAIMS_LIMIT`, `FREE_IDEATION_LIMIT`, `PRO_IDEATION_LIMIT`, `GLOBAL_OPERATION_LIMIT`, `QUOTA_WINDOW_DAYS` |
| Input bounds | `INVENTION_MIN_CHARS`, `INVENTION_MAX_CHARS`, `IDEATION_TITLE_MAX_CHARS`, `IDEATION_DESCRIPTION_MAX_CHARS` |
| Billing, excluded from this smoke and left unconfigured | `STRIPE_SECRET_KEY`, `STRIPE_PRO_PRICE_ID`, `STRIPE_WEBHOOK_SECRET` |

Frontend public variables are embedded at build time. Use an HTTPS API origin with
the `/api` suffix and the confirmed staging Supabase project's public key. Rebuild
after changing them. Never expose the service key or provider/Stripe credentials
through `NEXT_PUBLIC_` names. Source settings/defaults: `backend/app/core/config.py`,
`.env.example`, `frontend/src/lib/supabase.ts`, `frontend/src/lib/api.ts`.

For synthetic acceptance: enable mock execution on both API and worker; withhold
all provider and Stripe credentials; disable SerpAPI; permit only the small agreed
number of job admissions and disable claims/ideation allowances for both plans.
Mock mode covers the analysis graph; it does **not** make the separate claims and
ideation POST endpoints synthetic. Do not click Generate/Regenerate claims,
Generate idea or checkout. Free saved-result/evidence/cache GETs are in scope.
Use host egress restrictions allowing only staging Supabase when available; the
local test harness already rejects non-loopback API/worker connections.

Keep the shared global worker-active cap identical across every worker. Heartbeat
interval plus RPC timeout must fit inside the lease. Select finite limits from the
existing documented settings; synthetic and later live budgets must be agreed
separately. Billing validation requires a separate task.

## Startup and supervision

An authorized operator performs these steps after target/access gaps are resolved.
No commands below were used to launch a hosted service in this preparation pass.

1. Confirm the non-production Supabase project is active and migration checks pass.
   Create/use two dedicated test accounts. Verify magic-link delivery and the exact
   frontend `/auth/callback` URL is allowed in that project's Auth configuration.
   The current sign-in page uses magic links, not a password form.
2. Pin the API and worker to the same reviewed commit/backend image. Build from
   `backend/Dockerfile` or install `backend/requirements.txt` into an isolated
   environment. The image uses Python 3.11; CI also verifies Python 3.13.
3. Start the API service and verify `/openapi.json` returns 200. Verify an
   authenticated `GET /api/stripe/subscription-status` succeeds against staging;
   this is a free usage read and does not call Stripe. OpenAPI alone is liveness,
   not database readiness. API startup logs warn rather than fail on database errors.
4. Start the separate worker service after checking queued execution modes. Supervise
   it independently of the API, with restart-on-failure, bounded restart backoff,
   captured logs and alerts for crash loops or repeated `Queue unavailable`.
5. Build/start the frontend with the three staging public settings and Node 22.
   For Vercel, first resolve the build-log blocker and use the existing approved
   rollout process; do not change dashboard settings based on this runbook alone.
   Verify the exact deployed commit and run the synthetic acceptance below.

Commands configured on the respective services:

```bash
# API, working directory backend/ (or /app in the existing backend image):
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Worker, separate service/process, same working directory and backend image:
python -m app.worker

# Frontend, working directory frontend/:
npm ci
npm run lint
npx tsc --noEmit --incremental false
npm run build
npm run start
```

Choose the frontend listen port through the host's usual configuration. Route the
API's configured port through its HTTPS service endpoint. No verified host-specific
service manifest exists in this repository, so the operator must supply actual
service IDs and supervisor settings; the table above is not a deployment manifest.

Worker signals are consequential: SIGTERM/SIGINT stops claiming and cancels active
tasks; it is **not** a drain-to-completion shutdown. Stop admission and wait for
active work to finish before planned restarts. Unexpected termination leaves queued
work durable; expired running work becomes interrupted and retains usage. A complete
finalizing snapshot can publish without providers. Do not add an external supervisor
policy that re-POSTs jobs or replays interrupted paid graphs. Monitor queue age,
running lease expiry, finalizing backlog and failed/interrupted outcomes as well as
process liveness. The worker has no HTTP health endpoint.

## Synthetic acceptance: exact operator script

Use two separate browser profiles, Account A and Account B. Capture only sanitized
results, timestamps, commit/deployment IDs and the synthetic job ID; do not export
session cookies, bearer tokens or service keys.

1. Verify provider credentials are absent, mock mode is enabled and existing queued
   inputs are synthetic. Open the staging frontend at 320, 390 and desktop widths.
   Sign in as A; the invention form becomes editable only after session loading.
2. Submit one clearly synthetic invention longer than the configured minimum,
   e.g. “Synthetic staging irrigation controller with humidity sensors and adaptive
   scheduling.” Capture the browser request/response: one `POST /api/jobs`, a UUID
   submission key, response 202 with job ID and queued status. Do not resubmit on
   uncertainty with a new key; use the same inputs/key for idempotent recovery.
3. Wait for completion within the configured execution/polling bounds. Expect ten
   synthetic saved records, a saved report, synthetic evidence labels and a finished
   queue row. A paused browser poll is not proof the job failed: use **Retry status**
   (free GET) after inspecting worker logs. No provider request is acceptable.
4. In the staging administrative SQL console, filter `analysis_queue` by this job
   ID: state is `finished`, execution input version is 2, mock mode is true. Confirm
   exactly one new `usage_reservations` row for A with operation `job`, and no claims
   or ideation reservations. Record the report/evidence fields or their hashes.
5. Select an evidence record and record exact text/provenance. Refresh twice; open
   Dashboard and reopen the result. The same text/report and patent count remain;
   usage does not increase. Network activity contains saved-data GETs and no new
   job/claims/ideation POST. Cached-overlap absence must not auto-generate results.
6. Inspect all results sections at 320/390/desktop widths. If saved relationships
   exist, exercise graph +/− until each bound disables its button; rendered nodes
   grow/shrink. Expand increases height and Collapse restores it. Use keyboard and
   mouse node details. The current synthetic reporter/demo may have no relationships;
   then expect the graph to be absent and record hosted graph interactions as not
   exercised. The automated graph fixture tests cover those interactions without
   adding invented relationship data to a saved staging result.
7. In profile B, sign in as B and open A's exact result URL. Expect the unavailable
   state and no A evidence/report. With B's browser session, owner API status,
   evidence and saved-claims GETs must return 404. The equivalent PostgREST filters
   on `searches.id`, `search_results.search_id` and `patents.search_id` return empty
   arrays. Use only public anon key + B token for this RLS check, never service_role.
8. Sign A out in its original profile and sign B in there. Old private content must
   disappear; reopening A's URL remains unavailable. Confirm A's usage is unchanged,
   the saved report/evidence is unchanged, and browser/worker logs contain no errors
   or paid-provider requests. Preserve the sanitized acceptance record.

Failure means stop acceptance and diagnose the first failed step. Do not infer
hosted success from local tests, unblock a quota by refunding reservations, or turn
on live mode as a troubleshooting step.

The reusable local automated equivalent is `backend/tests/run_integrated.py` with
the disposable setup helper. It intentionally refuses remote URLs and must **not**
be pointed at staging/production or modified to bypass that guard. Existing evidence
at baseline: 94 backend tests, 43 frontend checks, and the real separate-process
integrated flow passed; final PR CI reruns the integrated check on the new head.
Local graph/layout checks for this pass supplement that evidence.

## Later bounded live-provider validation (not authorized or executed)

Synthetic acceptance proves transport, ownership, persistence and UI behavior. It
does not verify live provider access, jurisdiction coverage, model quality, billing
or spend. After synthetic staging acceptance, obtain separate approval for exact
providers, one bounded test corpus/job count, monetary cap and stop conditions.
Use staging-only credentials, finite admission limits and provider-side spend caps;
admission counts are not an exact dollar ceiling. Ensure the queue is quiescent
before changing mode, and use new submission keys only for explicitly approved new
analyses. Never replay or relabel existing synthetic rows as real evidence.
Inspect source fidelity, provenance, exclusions and final inference manually.
Claims/ideation and Stripe require their own explicit validation scope.

## Known constraints outside this pass

- Nine development dependency advisory entries (7 high/2 moderate), ESLint 9's
  support warning and the existing custom-font lint warning remain documented in
  the release handoff. No forced upgrades; production audit was clean at baseline.
- `backend/app/main.py:73`: CORS currently uses a wildcard and has no configurable
  origin allowlist. Restrict staging access at the existing host boundary; broader
  deployment/security configuration is not silently implemented here.
- `backend/app/main.py:28`: startup prints historical SQL snippets; use the six
  versioned migrations above, never those log snippets as a migration plan.
- `backend/app/api/stripe_routes.py:50`: checkout redirects target localhost; billing
  is excluded from this staging acceptance and needs a separately scoped fix/test.

Launch remains blocked until the owner supplies/authorizes the missing targets and
Vercel log access, the confirmed preview failure is resolved, a staging operator
performs the coordinated rollout, and the hosted synthetic script passes.
