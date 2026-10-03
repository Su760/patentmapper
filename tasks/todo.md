# Patent Landscape Mapper — Task Tracker

## Milestone 1 closure review and review branch (2026-10-02)

**Approval:** The user explicitly approved this bounded review/fix/handoff, including a feature-branch commit/push and hosted CI inspection. This supersedes the earlier no-commit/no-push instruction for relevant milestone-1 work only. No merge, deployment, production migration, hook changes, or milestone 2.
**Plan / file boundary:** Preserve the dirty-tree baseline and its existing tests. Review backend and frontend with two read-only reviewers; the primary fixes confirmed milestone-1 defects only. Authorized edit paths: the milestone-1 boundary below, `tasks/lessons.md`, `docs/milestone-1-review.md`, new usage-status migration and database/security test files under `supabase/` and `backend/tests/`, browser regression tests under `frontend/tests/`, and frontend quota/error consumers (`src/components/Navbar.tsx`, `src/components/NavBar.tsx`, `src/lib/auth-context.tsx`) only where confirmed necessary. Use an isolated publish worktree if needed to exclude unrelated prior telemetry/export/UI changes. Record any necessary dependency inclusion before staging.

- [x] Reconcile branch, index, dirty files, prior snapshot and 54-test post-change evidence (32 is historical baseline).
- [x] Obtain independent backend/frontend findings with file/line evidence. Confirmed accounting/plan/failure-state defects, ideation concurrency indicators, and malformed JSON preceding credential validation.

**Publication dependency boundary:** The isolated branch includes the existing configured-Groq helper/configuration and helper call sites in four nodes, plus its regression test: these are required to preserve the working model configuration used by milestone routes. It excludes telemetry/graph instrumentation, intelligence exports, provenance metadata/UI/styles, unused provider deletion, local settings and driftlens data. Existing local tests stay intact; milestone tests use independent `backend/tests/security_fixtures.py`. Include `supabase/tests/local_http_setup.py` for reproducible disposable Auth/PostgREST CI.

**Closure boundary amendment:** Add `frontend/src/lib/use-usage.ts` and `frontend/src/components/UsageSummary.tsx` to share verified accounting and scoped error handling; add `frontend/tests/milestone1-ui.cjs` and `backend/tests/test_usage_status.py` / `test_supabase_http.py` plus test fixtures for reproducible checks. Also include `frontend/playwright.config.cjs`, `frontend/package.json`, `frontend/package-lock.json`, and frontend test-artifact ignores for reproducible browser tests and CI. All are within the approved closure scope.

- [x] Fix authoritative rolling reservation usage display and visible ideation failures/loading; add regressions and fix confirmed security defects.
- [x] Run mocked tests, real PostgreSQL checks, disposable Supabase Auth/PostgREST checks, frontend checks/build; distinguish evidence and unavailable checks.
- [x] Inspect safe redacted hook runtime evidence separately; leave global hooks unchanged. Codex Stop echo emits plain text: safe standalone execution exits 0 but JSON parsing fails at line 1 column 1. The engine event from the prior turn was not retained in inspected logs; no full hooks executed.
- [x] Complete `docs/milestone-1-review.md` with migration order, accounting policy, results and deferred milestones.
- [ ] Inspect a relevant-only staged diff and credentials exclusions, commit/push a feature branch, inspect hosted CI and address caused failures.

**Closure verification:** Original worktree: 65 backend tests passed, including all original tests. Isolated review branch: 34 tests passed with no skips (19 mocked, 10 actual PostgreSQL, five actual Auth/PostgREST). Both frontend production builds passed; branch lint/typecheck and three Chromium regressions passed. Migration 3 and the new tests fix the two previously deferred accounting/ideation gaps. Full findings, setup commands, failures during development, reservation policy and hook evidence are in `docs/milestone-1-review.md`. Hosted CI/push remains the final checklist item.

## Milestone 1: Private, bounded analyses (2026-10-02)

**Goal:** Implement only the user's requested private, bounded analyses milestone on the current dirty checkout. Preserve the existing stack and local changes. No commit, push, deployment, or production migration.
**Approval:** User explicitly approved implementation of this plan on 2026-10-02; includes local/test database integration checks with mocked external providers. No further approval needed for this scope.
**Architecture:** Validate every supplied credential with Supabase Auth; share an owner-filtered job lookup across status, cached claims, claims generation, and ideation. Verified anonymous users own their jobs and receive free-tier limits; signed-out visitors can view only a fixed synthetic demo. Never adopt legacy ownerless records. Reserve usage before any paid work through a service-only Postgres RPC with transaction locking, finite per-user operation limits (free and Pro), and a finite global budget across operations. Fail closed on storage/subscription errors. Reservations are consumed even if later work fails, avoiding retry/refund races.
**File boundary:** `tasks/todo.md`, `CLAUDE.md`, `README.md`, `.env.example`; `backend/app/api/routes.py`, `backend/app/api/stripe_routes.py`, `backend/app/core/config.py`, `backend/app/core/security.py` (new), `backend/app/services/usage.py` (new), `backend/app/services/patent_api.py`, `backend/requirements.txt`; `backend/tests/test_private_analyses.py` (new), `backend/tests/test_milestone1_sql.py` (new), `backend/tests/test_pipeline_baseline.py`; `supabase/migrations/202610020001_private_analyses.sql` (new), `supabase/migrations/202610020002_bounded_usage.sql` (new), `supabase/tests/bootstrap.sql` (new); `.github/workflows/checks.yml` (new); `frontend/src/lib/api.ts`, `frontend/src/lib/demo.ts` (new), `frontend/src/app/page.tsx`, `frontend/src/app/dashboard/page.tsx`, `frontend/src/app/pricing/page.tsx`, `frontend/src/app/results/[id]/ResultsClient.tsx`. Changes elsewhere require a scope amendment.

- [x] Inspect repository instructions, HEAD/branch/status, local changes, full authorization/provider/persistence/browser paths, and current vendor docs. Confirm root causes and stale docs against checkout.
- [x] Add failing offline HTTP regression tests for owner access, missing/malformed/invalid/expired/cross-user credentials, ownerless jobs, verified anonymous owners, validation, provider non-invocation, quota failure, and concurrent admission.
- [x] Implement shared credential/ownership validation, fail-closed atomic usage reservations for jobs/claims/ideation, configured finite quotas and input limits, and remove Lens header logging. Keep service credentials server-only.
- [x] Add reproducible schema/ownership/quota migrations and isolated local Postgres tests exercising real concurrent transactions, service-only RPC privileges, owner/anonymous RLS reads, and denied browser writes. Do not use production databases.
- [x] Wire browser credentials into all private operations, expose deterministic signed-out demo behavior, stop treating localStorage UUIDs as guest access, and correct unlimited pricing language.
- [x] Add CI for backend regressions, isolated SQL tests, frontend lint/typecheck/build; run checks locally and inspect the final changes against the original dirty tree.
- [x] Update docs/setup instructions and this checklist with results, limitations, and deferred milestones.

**Post-change validation (separate from the original 32-test baseline):** 54 tests passed with no skips, including all original tests, 13 HTTP/browser-contract security regressions, and 9 real PostgreSQL integration tests. Ran both in the original virtual environment (52 tests before the last two hardening regressions) and a fresh Python 3.13 environment installed from `backend/requirements.txt` (final 54 tests). Fresh-environment `app.main` import passed. Frontend lint/typecheck/production build passed with the existing font/auth-hook warnings and outdated Browserslist data; CI YAML parsed. Chromium verified signed-out home → demo, fixed claims/ideation, dashboard ignoring legacy localStorage IDs, and private-link denial, with zero private API/database requests.

**Real database evidence:** Applied migrations only to a new temporary PostgreSQL 18.1 cluster listening on a private Unix socket and a disposable `patentmapper_m1_test` database. Browser roles could read their own rows but not another user's or legacy ownerless rows, and could not insert/update/delete searches/results/patents. API owner reads/claims generation succeeded; foreign/ownerless status/claims/ideation returned 404 with no providers invoked. For each paid operation, eight concurrent HTTP requests using separate real SQL transactions with one unit left admitted exactly one and rejected seven. Renaming the quota or subscription table caused 503 with no model/patent/background work. Also verified service-only RPC access, global admission across users/operations, budget retention after account deletion, finite Pro/anonymous limits, expired Pro behavior, replacement of permissive old policies, and idempotent historical usage seeding without ownership adoption.

**Preservation:** HEAD remains `92b9580` on `main`. Compared hashes against a snapshot taken before implementation; existing files outside the approved boundary are byte-for-byte preserved, including earlier graph/provider refactors, telemetry/export work, all other tests, and existing UI changes. The original 32 tests remain; two job-submission fixtures now supply an authenticated identity and a valid-length invention. No commit, push, deployment, production migration, or approval/hook changes.

**Required setup:** Install updated backend requirements (adds the already-used Stripe SDK), apply the two checked-in migrations in filename order to development/test using an administrative migration role, configure the server-only service/provider keys and finite usage settings from `.env.example`, and use `NEXT_PUBLIC_API_URL=http://localhost:8000/api` plus only the public Supabase URL/anon key in the browser. Configure magic-link callback allowlisting. Review existing policies before applying migration 1 because it replaces policies on the four protected tables. Do not apply `supabase/tests/bootstrap.sql` to an application database. Exact commands are in README.

**Unverified / remaining limitations:** Hosted GitHub CI has not run (local equivalent passed); real Supabase Auth/PostgREST and live-provider end-to-end validation remain unrun. Auth and external providers are mocked in the SQL harness; the actual authorization queries, quota function, locks, tables, and database roles are real. Operation allowances bound admissions rather than exact dollar cost; failed work conservatively consumes reservations. The frontend does not provision new anonymous accounts; verified existing anonymous sessions are accepted. Legacy ownerless data stays hidden. Job recovery/report/evidence/evaluation limitations remain deferred. `backend/app/api/stripe_routes.py:84` still displays searches-based usage rather than consumed reservations, and `frontend/src/app/results/[id]/ResultsClient.tsx:1066` still logs ideation errors without displaying them; these adjacent issues are reported, not fixed.

**Separate stop-hook JSON issue:** Not reproduced in this runtime. Read-only inspection found valid global settings JSON and a Stop hook emitting syntactically valid JSON (`~/.claude/settings.json:373`); the other Stop script parses input and silently catches errors (`~/.claude/hooks/on-stop.js:18`). No hooks were executed manually, disabled, or edited, and no approval rules were changed. The reported hook/runtime mismatch remains unverified and outside this milestone.

**Verified discrepancies:** `CLAUDE.md` describes Gemini, auth excluded from v1, and a state/schema missing current jurisdiction/citation/claims fields; implementation uses configurable Groq plus magic-link auth and billing/claims/ideation. Google OAuth is not implemented in this checkout. README incorrectly promises anonymous UUID access, unlimited Pro, unauthenticated Lens access, and react-force-graph-2d (current graph uses SVG). Historical task sections describe an earlier audit/export scope; they remain historical, not the current implementation boundary.
**Instruction availability:** The session-referenced `~/.Codex/rules/ui-ux-pro-max/AGENTS.md` is absent. Preserve the current visual design; frontend changes are limited to security, credentials, error states, and explicit demo/quota text.

### Deferred milestones (out of scope)

- [ ] Job/report reliability: durable execution/recovery, idempotency, transactional persistence, final-report storage, failure semantics.
- [ ] Evidence workbench: sourced claims/citations, provenance and jurisdiction fidelity, evidence review/export workflows.
- [ ] Quality evaluation: retrieval/analysis benchmarks, labeled evaluation sets, hallucination/citation checks.

## Infrastructure Audit and Phase 1 Plan (2026-09-05)

**Goal:** Measure the existing pipeline and establish offline regression evidence without changing research, billing, mock-mode, or provider-disable behavior.
**Architecture:** Keep the six-node graph, FastAPI background tasks, and Supabase. Add a structured timing wrapper at graph registration and deterministic offline characterization tests.
**Tech stack:** Existing Python, unittest, LangGraph, standard-library clocks/logging; no new runtime dependency.
**Spec:** `docs/INFRASTRUCTURE_REVIEW.md` (findings, phase boundaries, acceptance criteria, manual release checks).
**Approval:** User approved Phase 1 and explicitly expanded it to job-reliability audit, structured export schema, and tests. Existing Trust/Provenance live validation remains open.

**Approved scope amendment:** Add `backend/app/services/intelligence_export.py`, `backend/tests/test_intelligence_export.py`, and `docs/intelligence-export-v1.schema.json`. Implement a pure read-only library builder over caller-supplied search/result/patent rows, typed versioned output, JSON Schema, deterministic serialization, explicit unknowns for legacy provenance/dates, and evidence-only metrics. No new endpoint, live integration, queue, DB migration, provider call, or trading logic. Document the callable and connector design in the infrastructure review.

**Ruling:** Continue in the approved current local working tree, preserving dirty files; a clean checkout would omit the source-of-truth uncommitted fixes. Execute independent export work with a subagent as directed by the execution skill; review its result before completion. Approval of this amended Phase 1 is supplied by the user's request itself.

- [x] Inspect local git status/branch/history, documentation/tasks, application data flow, tests, and CI configuration.
- [x] Run baseline backend test and frontend lint/build; record warnings and mock latency/correctness/failure probes in the review.
- [x] Produce `docs/INFRASTRUCTURE_REVIEW.md` before implementation.
- [x] Obtain approval for this concrete Phase 1 scope as required by the session-supplied AGENTS.md planning rule.
- [x] Extend reliability audit with crash windows, duplicate delivery, retry/failure behavior, status transitions, observability, and a future durable-worker design (no migration).
- [x] Implement and test versioned read-only intelligence export; generate JSON Schema; document Researcher consumption and timestamp/provenance limitations.
- [x] Add `backend/tests/test_pipeline_telemetry.py` with deterministic success/error/cancellation, timing, return identity, and secret-omission cases; run to demonstrate missing instrumentation.
- [x] Add `backend/app/agents/telemetry.py` and update only node registration in `backend/app/agents/graph.py`; retain exact graph order, state, exceptions, and provider/DB behavior.
- [x] Add `backend/tests/test_pipeline_baseline.py` covering six mock stages, output fixture, fallback and SerpAPI disable, and current empty-on-outage behavior; prohibit external calls.
- [x] Run all backend tests and at least 20 paired mock timing samples; rerun frontend lint/build; record exact results and overhead in the review.
- [x] Inspect final diff against the initial dirty tree; report Phase 1 changes, unresolved findings, and unrun live checks. Do not commit, push, migrate, deploy, or implement later phases.

**Validation:** 32 backend tests passed; frontend lint/build passed with existing warnings. Mock paired medians 1.052 ms without wrapper / 1.158 ms with wrapper; all paired outputs equal. Actual mock pipeline persistence exported as 10 patents/3 clusters with unknown historical times preserved. Independent final review found no introduced defects. Live Supabase/browser validation and process-death recovery remain unverified; Phase 1 does not implement durable jobs.

**Implementation file boundary:** Only the four originally planned Python paths, the three export paths in the amendment, `docs/INFRASTRUCTURE_REVIEW.md`, and `tasks/todo.md`. Adjacent issues in the review require separate scope/approval; do not fix them within Phase 1.

## Current Sprint: Trust/Provenance Validation (2026-09-02)

- [x] Run frontend build and lint
- [x] Run backend import and compile validation
- [x] Replace the unavailable Groq model with a configurable, live-compatible model
- [x] Add and run a regression test for configured Groq model selection
- [x] Exercise the real external pipeline without persistence
- [ ] Exercise one HTTP patent-landscape job end to end — blocked: configured Supabase host does not resolve
- [x] Verify AI provenance labels and Lens.org → SerpAPI behavior
- [x] Remove generated TypeScript build metadata from the change set
- [x] Reconcile the stale scaffold checklist with the implemented product

### Operational Follow-ups

- [ ] Restore or replace the configured Supabase project, then rerun the HTTP end-to-end test
- [ ] Replace the Lens.org token; the current token returns HTTP 401 and forces every query to SerpAPI

## Current Research Spike: Product Direction (2026-09-01)

- [x] Map the current product, architecture, and existing capabilities
- [x] Audit the retrieval, analysis, trust, and operational risks in code
- [x] Research current official patent-search tools, data access, and competitor positioning
- [x] Recommend the product wedge, next milestone, and sequenced roadmap
- [x] Report findings with evidence, risks, and exact validation tests

## Historical Sprint: Initial Product Build

### In Progress

- [x] Read CLAUDE.md and spec file
- [x] Plan monorepo structure
- [x] Scaffold the backend and frontend applications
- [x] Implement FastAPI `/jobs` routes
- [x] Implement the LangGraph pipeline
- [x] Wire the Supabase client into routes and nodes

### Up Next

- [x] Frontend: input page + polling stepper UI
- [x] Replace mock nodes with real implementations
- [x] Results page UI
- [ ] End-to-end test with real patent idea

### Done

- [x] CLAUDE.md written
- [x] patent_mapper_spec.md written
