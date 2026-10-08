# M1–M3a release hardening handoff

Reviewed 2026-10-08. This branch makes malformed overlap data safe to open, upgrades
the frontend to supported Next.js, and keeps the complete results page usable on
small screens. It includes the cumulative M1–M3a implementation when compared with
`main`; it is not a standalone patch suitable for the old schema.

## Baseline and boundaries

Local and remote `milestone-3a-evidence-workbench` matched
`6ca6e0a41e969ef485dfa65db2bbac6404c221b4`. Work is isolated on
`release-hardening-m3a` in `/private/tmp/patentmapper-release-hardening`.
The original dirty `main` remains at `92b9580`; work and tests ran in the isolated
worktree. An outside-git SHA-256 snapshot covers 87 original tracked/untracked files.
The final comparison found 86 byte-identical files and no new files; the original
generated `frontend/tsconfig.tsbuildinfo` is now missing. Its removal is unattributed;
it was left untouched, not reconstructed over
concurrent work. The existing M3a worktree was not changed.
The approved plan and amended file boundary are in `tasks/todo.md`.

No production migration, manual deployment, merge, paid provider request, Vercel
setting change, global hook change or M3b implementation was performed. The supplied
`~/.Codex/rules/ui-ux-pro-max/AGENTS.md` was unavailable; the existing design was
preserved. Credentials, database files and generated browser artifacts stay outside
git. Hosted checks and their exact final commit are recorded on the draft PR.

## Cumulative behavior relative to main

- **M1:** verified owner access, private RLS, bounded transactional usage admission,
  fail-closed storage errors, permanent-account checkout and an explicit demo.
- **M2a:** saved final reports and overlap caches, free reopening/read retries,
  bounded cancellable status polling, explicit retrieval failures and insufficient
  evidence, and atomic publication.
- **M2b1:** owner-scoped submission idempotency; durable queue admission; separate
  workers with leases/fences, bounded concurrency and durable output checkpoints.
  Interrupted paid work is not replayed. Finalizing snapshots recover without
  provider calls. Failed paid attempts retain their reservations.
- **M3a:** persisted exact retrieval observations and provenance, provider-qualified
  identities, owner-only searchable evidence reopening, conservative legacy states,
  and visible separation of saved source text from model inference.
- **This pass:** complete overlap shape validation, supported Next/React upgrade,
  responsive results layout, and a reproducible browser-to-worker integration check.

The inherited commits are `99f5163`, `6863af2`, `9431701`, `5a4ffd0`, `668b628`,
`cbb1ea1`, `85fc0f1`, `831420c`, and `6ca6e0a`. Historical milestone reviews retain
their original verification context; this document supersedes their unresolved
mobile and integrated-flow items only where explicitly verified below.

## Changes and causal evidence

At the baseline, `backend/app/services/evidence.py:121-136` checked overlap IDs but
not the other fields. A known ID with `likely_claims: null` survived and reached
`ResultsClient.tsx:955`, which called `.map()`. The new regression failed before
the fix (34 subtest failures and four errors across malformed shapes).

Generated results and saved legacy/versioned caches now require a known unique
string ID, string title/explanation/differentiators, an array of strings for
`likely_claims`, and a `high|medium|low|none` enum. Invalid records and malformed
collections/warnings are excluded with deterministic visible warnings. Unsupported
cache versions are not reinterpreted; booleans/floats are not integer version 1.
Valid legacy list caches remain readable without rewriting them or consuming usage.
The client independently validates response fields before rendering. Invalid data
never causes automatic generation or fabricated replacement claims. The saved
patent title remains authoritative, as it was before this pass.

The original fixed toolbar row and intrinsic grid widths overflowed at 320/390px;
unbroken identifiers also forced cards beyond desktop bounds. Wrapping controls,
zero-minimum grid tracks and breakable text now let the layout grow. The graph
header participates in normal flow, badges retain a readable width, and the results
toolbar is the only sticky bar on this page, avoiding collision with the site nav.
No overflow clipping was added to hide the defect. The duplicate overlap inference
notice in loading/error states was removed.

New React lint rules exposed effect-driven owner resets and render-time ref writes.
Keyed owner/loading components and attempt-scoped usage state preserve cancellation,
account separation and submission-key recovery. Independent review then identified
a history error that survived a successful same-owner token refresh. Clearing the
error after that successful fetch is covered by a failing-then-passing browser test.

## Supported frontend and dependency review

The committed versions are Next.js/eslint-config-next **16.4.0**, React/react-dom
**19.3.0**, React types **19.3.0**, and Node **22.x** (minimum 22.14.0). Local checks
used Node 22.20.0 and npm 11.7.0; CI selects Node 22. Next's
[support policy](https://nextjs.org/support-policy) identifies 16 as Active LTS and
14 as unsupported. Version 16.4.0 is the stable release checked on the review date.
The [Next 16 upgrade guide](https://nextjs.org/docs/app/guides/upgrading/version-16)
requires async route params and separate lint execution; both are implemented.
Flat ESLint configuration uses the current Next presets without disabling rules.
Existing private no-store requests, bearer credentials, cancellation and idempotency
are retained and regression-tested.

The installed Next version was checked against the official
[16.3.8 security release](https://github.com/vercel/next.js/releases/tag/v16.3.8),
[next/og advisory](https://github.com/vercel/next.js/security/advisories/GHSA-vcvr-r3jv-pc5j),
[image advisory](https://github.com/vercel/next.js/security/advisories/GHSA-2xp9-vwfh-vxw4)
and [RSC advisory](https://github.com/vercel/next.js/security/advisories/GHSA-q4gf-8mx6-v5v3).
16.4.0 is later than their fixed releases. The image optimizer's DNS pinning is
also present in the installed release source. Audit output alone was not treated
as proof that every advisory had a complete registry range.

`npm audit --omit=dev` reports **zero vulnerabilities**. A narrow override pins
`@supabase/ssr`'s `cookie` dependency to **0.7.2**, fixing the
[cookie advisory](https://github.com/jshttp/cookie/security/advisories/GHSA-pxg6-pf52-xh8x).
The existing SSR version/cookie format remains intact; upgrading that library would
also change session writes to base64 and introduce a separate old-tab migration.
Legacy raw/chunked session reading and sign-out are tested against this override.
`npm ls --all` exits 0: no invalid peer dependency tree.

The full audit retains **9 affected development packages (7 high, 2 moderate)**,
from [braces](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm) and
[postcss-selector-parser](https://github.com/advisories/GHSA-rj75-hqrm-r3gf) through
Tailwind/Next lint tooling. These paths process repository-controlled build inputs,
not submitted runtime inventions. There is no patched compatible braces release;
Tailwind's nested selector dependency remains on 6.x. Replacing the CSS toolchain
is deferred. ESLint **9.39.5** emits an upstream support/deprecation warning; the
current React ESLint plugin's peer range excludes ESLint 10. This is a retained
tooling limitation, not a fully supported toolchain claim. No forced audit fix,
peer bypass, Next downgrade or warning suppression was used.

## Verification on the final code

| Check | Local result |
| --- | --- |
| Complete backend suite with real SQL and Auth/PostgREST enabled | **94 passed, zero skips** |
| Existing and new frontend regressions | **42 passed: 35 Chromium + 7 Node** |
| Separate integrated synthetic browser/API/worker/database flow | **1 passed** |
| Clean `npm ci`, lint, TypeScript, production build, dependency tree | Passed; lint retains one existing font warning |
| Long-content full page at 320, 390 and 1280px | Every visible HTML element and document width fit; screenshots inspected |

Backend coverage includes existing authorization/quota/RLS, concurrent admission,
idempotency, atomic publication, worker process recovery/fences, evidence provenance
and cache validation regressions. The final command used Python 3.11 and PostgreSQL
18 locally; CI uses Python 3.13 and PostgreSQL 17 for the SQL job.

```bash
# Local final backend run, from the isolated repository root:
PATH=/opt/homebrew/opt/postgresql@18/bin:$PATH PYTHONPATH=backend MOCK_MODE=true \
  REQUIRE_FRONTEND_TESTS=1 \
  MILESTONE1_TEST_DSN='postgresql:///patentmapper_m1_test?host=/tmp/pm-release-pg-socket&port=55449' \
  MILESTONE1_DISPOSABLE_SUPABASE=1 \
  MILESTONE1_SUPABASE_CONFIG=/tmp/pm-release-http/test-config.json \
  /tmp/pm-m2b-py311/bin/python -m unittest discover -s backend/tests -v

# Frontend checks, from frontend/ with test public configuration:
npm ci
npm run lint
npx tsc --noEmit --incremental false
npm run build
npx playwright test --config playwright.config.cjs

# Real integrated run, from the repository root:
PATH=/opt/homebrew/opt/postgresql@18/bin:$PATH MILESTONE1_DISPOSABLE_SUPABASE=1 \
  /tmp/pm-m2b-py311/bin/python backend/tests/run_integrated.py \
  /tmp/pm-release-http/test-config.json /tmp/pm-release-integrated-final
```

The disposable stack was created with
`python supabase/tests/local_http_setup.py /tmp/pm-release-http`. That helper applies
all six real migrations and creates only test infrastructure. The integrated runner
requires an explicit disposable flag, refuses remote service URLs, and keeps its
private artifacts outside git. It starts the actual API and `app.worker` in distinct
processes, with `MOCK_MODE=true`, blank paid keys and a test-only network guard.
Browser traffic reaches real Auth, PostgREST and API endpoints; no route mocking is
used in this integrated test. Model/retrieval output remains synthetic.

Final integrated evidence: job `305221d9-a067-405a-a6aa-0dc4debbcee5`, ten saved
patents, queue `finished`, exactly `job:1` usage, two refreshes, unchanged saved-row
fingerprint `ebdafa6b0fb335b5555b73a07a213795`, exact evidence reopening through the
dashboard, zero page errors. A second account receives API 404 and empty PostgREST
rows for the first account; switching accounts removes the old private DOM. The
only paid-operation endpoint requested was the single synthetic `/api/jobs` admission.
No non-loopback API/worker connection was attempted; Google Fonts browser requests
were intercepted and blocked. This verifies persistence and isolation, not live
patent coverage, model quality or hosted deployment behavior.

The long-content browser fixtures additionally exercise malformed generated/saved
overlap, valid legacy cookies, sign-out, loading/error notice counts, graph details,
evidence selection, actual clipboard copying, print invocation and claims navigation
without paid replacement. The existing tests cover cancellation and lost-response
submission-key recovery. Export verification invokes `window.print`; it does not
claim to inspect an operating-system print dialog or a generated PDF.

Local logs: `/tmp/pm-release-backend-final.log`, `/tmp/pm-release-browser-final.log`,
`/tmp/pm-release-lint-final.log`, `/tmp/pm-release-build-final.log`,
`/tmp/pm-release-integrated-final.log`. Integrated screenshots/evidence are in
`/tmp/pm-release-integrated-final/`; adversarial long-text screenshots are
`/tmp/pm-release-{320,390,1280}.png` and corresponding `-viewport.png` files.
Generated session configuration is private and must not be attached to the PR.

Earlier attempts exposed the intended red regressions, new Next lint/type errors,
missing clipboard test permission and genuine long-text/badge/sticky layout
failures. Those were corrected and the complete suites rerun. Sandbox socket/port
restrictions and a temporary ENOSPC interrupted initial attempts; permitted reruns
succeeded. These failed attempts are not counted as passing verification. No checks
in the final local backend/browser suites were skipped. Live paid calls, production
migrations, hosted UI and a manual deployment were intentionally not run.

Independent read-only review examined the implementation, dependency compatibility
and test evidence. Its confirmed dashboard recovery defect and overly broad network
claim were corrected. Final implementation re-review found no further blocking
issues; retained limitations are listed here rather than silently treated as fixed.

## Vercel diagnostics: access blocked, cause unknown

Baseline GitHub Checks passed in
[run 37265962405](https://github.com/Su760/patentmapper/actions/runs/37265962405).
The baseline Vercel status failed for deployment
`dpl_GrbfdKVGxUHV8XP1LGq698yqgKEi` (GitHub deployment 6851707989,
2026-10-05T05:01:32Z), linked to
[the deployment](https://vercel.com/su2976/patentmapper/GrbfdKVGxUHV8XP1LGq698yqgKEi).

Read-only Vercel CLI 59.11.2 diagnostics returned:

```text
vercel inspect dpl_GrbfdKVGxUHV8XP1LGq698yqgKEi --logs
Can't find the deployment ... under the context code-8ed4

vercel inspect dpl_GrbfdKVGxUHV8XP1LGq698yqgKEi --logs --scope su2976
Error: The specified scope does not exist
https://err.sh/vercel/scope-not-existent
```

Build logs were unavailable under the authenticated account/scope. There is no
confirmed repository cause for this deployment failure. No root-directory, account,
project, billing or deployment settings were guessed or changed. Access to the
owning Vercel scope or exported build logs is needed to diagnose it. Local build
success is not evidence that this hosted failure is resolved.

The release implementation commit `c864002` was pushed and
[draft PR #1](https://github.com/Su760/patentmapper/pull/1) targets `main`. Its Vercel
deployment `dpl_nMUyJXZwhAaobcCCFsYvNiYRtufY` also failed. Both read-only inspection
commands were repeated for that exact deployment and returned the same default
context/not-found and explicit-scope/nonexistent errors. The blocker therefore
also applies to the new branch, with no accessible build log or confirmed cause.
Final-commit GitHub Actions and deployment status are linked in the PR body so they
can identify the actual final documentation commit without a self-referential hash.

Both GitHub jobs (`milestone1`, `auth-postgrest`) passed at implementation commit
`c864002ecd57717bb13945945b219706d302289c` in
[run 37828185542](https://github.com/Su760/patentmapper/actions/runs/37828185542).
This includes the new integrated browser/API/separate-worker check. The final
documentation commit is checked again before handoff; its exact SHA, run links and
Vercel status are recorded in PR #1 rather than inferred from this earlier success.

## Migration and runtime handoff

This hardening adds **no migration**. For a new installation, apply these existing
files in order using the administrative migration role:

1. `202610020001_private_analyses.sql`
2. `202610020002_bounded_usage.sql`
3. `202610020003_usage_snapshot.sql`
4. `202610030001_saved_results.sql`
5. `202610040001_durable_jobs.sql`
6. `202610040002_evidence_workbench.sql`

An existing M2b database needs only migration 6; an existing M3a database needs none.
Stop all API and worker processes before applying migrations 5/6 and restart only
matching updated versions afterward. Migration 6 upgrades queued v1 inputs to v2,
interrupts running v1 work, and retains finalizing v1 snapshots for provider-free
legacy publication. Historical evidence remains unknown. Do not run mixed old/new
workers, delete durable inputs/output, blindly downgrade, replay paid work or refund
reservations as a migration shortcut. Migration 1 replaces policies on protected
tables; inspect existing policy compatibility before an authorized rollout. Never
apply the test bootstrap to an application database.

The runtime requires a separately hosted, long-running API and durable worker with
matching server-only configuration and database privileges:

```bash
# From backend/, separate processes with the same server configuration:
uvicorn app.main:app --host 0.0.0.0 --port 8000
python -m app.worker
```

The frontend build needs only the public Supabase URL/anon key and API URL. Keep
service/provider keys server-only. A frontend-only Vercel deployment cannot process
queued jobs. Use the existing finite usage and worker settings in `.env.example`;
all workers must share the global active-work limit. This document describes rollout
requirements; it does not authorize or claim a production rollout.

## Remaining limitations and adjacent findings

- Vercel deployment failure remains undiagnosed because build-log access is blocked.
- Nine development audit entries and the ESLint 9 support warning remain; production
  dependency audit is clean as of the review date.
- `frontend/src/app/layout.tsx:26`: the pre-existing Next custom-font lint warning
  remains; no warning was disabled to pass checks.
- `frontend/src/app/results/[id]/ResultsClient.tsx:1683`: existing graph +/−/expand
  buttons have no handlers; this layout pass keeps them visible but does not invent
  new graph interactions. Graph node details and the working toolbar actions passed.
- Synthetic integration cannot establish live provider coverage, paid model output
  quality, billing/webhook correctness or production infrastructure behavior.
- Full claims retrieval, generated claim-to-quote matrices, automatic paid replay,
  broader jurisdiction support and quality evaluation remain deferred, including M3b.
