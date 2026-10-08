# M3a — persisted evidence provenance and read-only workbench

Historical M3a handoff at `6ca6e0a`. The subsequent [release-hardening review](release-hardening-review.md) records overlap shape validation, the framework upgrade, full-page mobile fixes, integrated synthetic execution and deployment diagnostics. The original evidence below is retained as historical evidence.

Base/remote verified at `85fc0f1df64efe3a2bc008e7362ddf94aa38e8e5` on `milestone-2b-durable-jobs`. Isolated branch: `milestone-3a-evidence-workbench`, worktree `/tmp/patentmapper-m3a`. All 86 files in the original dirty main SHA-256 preservation snapshot remain unchanged; that checkout is excluded from this branch. The approved plan/file boundary is recorded at the top of `tasks/todo.md`.

## Behavior and evidence contract

Owners can search saved records, select one, inspect exact text and every provenance observation, then follow a saved source URL. Search/select are local UI operations. Initial load, reopen and explicit read retry use authenticated GETs only. There is no quota reservation, model call, retrieval or provenance regeneration on these reads. Fixed public demo evidence stays local; private mock-mode evidence is explicitly synthetic and has no invented publication identity or live source URL.

`patents.evidence` is nullable JSON:

```json
{
  "version": 1,
  "observations": [{
    "provider": "serpapi",
    "provider_record_id": "patent/US123/en",
    "publication_id": "US123A1",
    "source_url": "https://patents.google.com/patent/US123/en",
    "retrieved_at": "2026-10-04T12:00:00+00:00",
    "matching_queries": ["fixture query"],
    "text": "  Exact retrieved text\nincluding whitespace and entities  ",
    "text_type": "search_snippet",
    "language": "en",
    "dates": {"priority": "2018-01-01", "filing": null, "publication": "2022-01-01"},
    "requested_jurisdiction": "us",
    "jurisdiction_filter": {"country": "US"},
    "coverage_limitations": ["Limited search results; coverage is not exhaustive. No full patent claims were retrieved."]
  }]
}
```

This is a synthetic schema example, not an actual patent assertion. Provider IDs remain raw; the internal analysis ID is `provider:provider_record_id`. Publication IDs are only taken from SerpAPI `publication_number`, or formatted from all supplied Lens publication-reference components (jurisdiction, document number, kind). Provider IDs, URLs or model output never supply missing publication IDs. Missing source URLs stay unavailable, except the documented Lens record URL built from its Lens ID. External links permit HTTP(S) only.

Text types are `abstract`, `search_snippet`, `title_only`, `synthetic`. Lens abstract arrays preserve every returned text/language variant; string abstracts remain supported. Title-only Lens variants preserve their text/language. SerpAPI snippets retain exact entity strings and whitespace without claiming to be abstracts or claims. The existing `abstract` database column remains a compatibility field for model excerpts and historical text; its name is never used to establish provenance. Models may use truncated excerpts, not every saved observation.

Deduplication only combines identical provider record identities; it appends distinct observations, including different matching queries, timestamps or text. Exact duplicate observations may collapse. No title similarity, publication matching or family inference joins providers. Multiple providers can therefore represent the same publication; counts are record counts, not verified unique patent/family counts.

Priority, filing and publication values remain separate nullable provider strings under typed keys. No priority/publication fallback becomes a filing year. Filing trend charts are suppressed for new and legacy data because limited retrieval cannot establish population-level trends. Requested jurisdiction is saved on the result and each observation. Lens has no jurisdiction filter in this adapter; the UI records that limitation. SerpAPI records the country parameter actually submitted, without guaranteeing provider completeness. This milestone adds no provider or filtering expansion.

## Model inference and saved reads

Cluster members and relationship endpoints are validated against the retrieved set before downstream use and again before checkpointing. Unknown, malformed and duplicate references are excluded with deterministic warnings. Conceptual links always carry `is_ai_inferred=true`. The evidence endpoint also filters legacy structured references in memory, without changing saved rows or inventing patents. The result UI consumes the sanitized cluster/link view, so a historical malformed member list cannot crash rendering or create a retrieved graph node.

Overlap generation retains the existing explicit paid action and allowance. Its prompt and UI describe conceptual inference from available text, never retrieved claims or verified legal scope. Unknown/duplicate structured overlap IDs are excluded; warnings persist in a version-1 claims-cache envelope. Old list caches remain readable and are filtered on free GET. Unknown future cache versions display a warning rather than reinterpretation. Free-form model prose remains unverified inference; this is not citation verification, claim construction, novelty evaluation or a claim-to-quote matrix.

Missing historical evidence returns `legacy_unknown`; saved historical text remains inspectable/searchable with unknown type, date semantics and provenance. Future evidence versions return `unsupported_version` with opaque provenance. Reopening never manufactures source metadata or spends usage.

## Migration, compatibility and recovery

Apply migrations 1–6 in filename order only to a new development/test database. An existing M2b installation needs **only** `202610040002_evidence_workbench.sql`, using the administrative migration owner, not `service_role`. Earlier migrations and their grants are unchanged. Stop API/workers before migrating; start the updated API and worker together afterward. The migration notifies PostgREST to reload its schema.

| Saved state | M3a behavior |
| --- | --- |
| Existing completed/insufficient result | Evidence remains NULL; no backfill, ownership adoption or paid read |
| Queued execution v1 | Upgrade to v2, recording `upgraded_from_version: 1`; original reservation retained |
| Running execution v1 | Interrupt during coordinated migration; no replay/refund |
| Finalizing execution v1 | Preserve immutable checkpoint; publish existing output with unknown historical evidence, without graph/providers |
| New execution | API snapshots v2; checkpoint requires evidence v1 |
| Unknown execution version | Worker fails explicitly before graph construction |
| Unknown new evidence version | Checkpoint validation rejects it; saved future-version reads remain opaque |
| New finalizing checkpoint | Recover existing atomic publication only; no paid calls or new reservation |

Evidence/result metadata pass through the fenced checkpoint and existing `publish_analysis` transaction. Publication writes result, patent evidence and terminal status together. Rollback retains the checkpoint. Stale tokens cannot publish; retries preserve terminal rows and cached overlap. Browser RLS still protects the existing results/patents tables. The API uses the existing server-verified owner lookup before its service-role reads. No new queue access or direct service write bypass was granted; the existing claims-cache exception remains limited to `claims_analysis`.

Do not revert only the application, run v1 workers alongside v2, reset interrupted work to queued, discard checkpoints, or replay old usage-seeding migrations. Use a coordinated forward fix. A stale old API can still submit an old execution envelope, but the new worker rejects it without paid work; mixed-version operation is unsupported. Recovery of a valid old finalizer is tested. Persistent schema/store errors still require operator repair.

## Independent review

One fresh-context reviewer inspected the complete branch read-only. They ran focused deterministic tests, not database/browser checks. Confirmed findings and fixes:

- Raw legacy clusters could bypass the sanitized evidence view and throw on `.filter`: consume sanitized saved clusters/links; malformed legacy browser regression passes.
- Malformed member/overlap collections were silently excluded: add deterministic visible warnings; parser/reference fixtures pass.
- Lens title-only observations lost supplied language: preserve title variants and their language; the French/English fixture failed before the fix and passes afterward.
- Historical saved text was displayed but unsearchable: include historical text in local search; the browser test using a query appearing only in that text failed before the fix and passes afterward.

Additional verification found and fixed a malformed evidence-response client crash and missing provider IDs becoming unusable `lens:` identities. Regression fixtures cover both. No confirmed in-scope review finding is deferred.

## Exact verification

Final local backend: **89 passed, zero skips** (47 mocked/contract, 32 real PostgreSQL including worker-process checks, 10 real Supabase Auth/PostgREST). All original M1/M2 regressions remain; fixture changes reflect provider-qualified IDs, v2 execution, jurisdiction consistency and a forward-migration test selecting its historical cutoff explicitly.

Final frontend: **30 passed** (23 Chromium + 7 deterministic Node checks), lint/typecheck/build passed. New browser coverage includes desktop 1280 px and mobile 390 px evidence search/select/reload, exact DOM text preservation, snippet/date labels, source href, legacy text search, malformed legacy data, public synthetic evidence, free failure/retry, account-switch cancellation and zero paid requests. Desktop/mobile screenshots were generated and visually inspected at `/tmp/pm-m3a-desktop.png` and `/tmp/pm-m3a-mobile.png`.

Commands from repository root unless stated otherwise (all external paid services mocked):

```bash
# Existing supported Python 3.11 environment from M2b; requirements unchanged.
/tmp/pm-m2b-py311/bin/python --version
export PATH=/opt/homebrew/opt/postgresql@18/bin:$PATH
initdb -D /tmp/pm-m3a-pg -A trust --encoding=UTF8
mkdir -p /tmp/pm-m3a-pg-socket
pg_ctl -D /tmp/pm-m3a-pg -l /tmp/pm-m3a-pg.log \
  -o '-k /tmp/pm-m3a-pg-socket -p 55439 -h ""' start
createdb -h /tmp/pm-m3a-pg-socket -p 55439 patentmapper_m1_test
/tmp/pm-m2b-py311/bin/python supabase/tests/local_http_setup.py /tmp/pm-m3a-http
PYTHONPATH=backend MOCK_MODE=true REQUIRE_FRONTEND_TESTS=1 \
MILESTONE1_TEST_DSN='postgresql:///patentmapper_m1_test?host=/tmp/pm-m3a-pg-socket&port=55439' \
MILESTONE1_DISPOSABLE_SUPABASE=1 \
MILESTONE1_SUPABASE_CONFIG=/tmp/pm-m3a-http/test-config.json \
/tmp/pm-m2b-py311/bin/python -m unittest discover -s backend/tests -v
cd frontend
npm ci --prefer-offline --no-audit --no-fund
npm run lint
npx tsc --noEmit --incremental false
NEXT_PUBLIC_SUPABASE_URL=https://example.supabase.co \
NEXT_PUBLIC_SUPABASE_ANON_KEY=test-only-public-anon-key \
NEXT_PUBLIC_API_URL=http://localhost:8000/api npm run build
npx playwright test --config playwright.config.cjs
```

PostgreSQL 18 used a disposable local socket; Supabase used separate local Docker services with real Auth/PostgREST. Generated credentials remain outside git. The test harness resets only a guarded local database named `patentmapper_m1_test`. Existing CI discovers all new tests: main job uses Python 3.13/PostgreSQL 17; the separate Auth/PostgREST job runs 10 tests. Hosted [Checks run 37265506951](https://github.com/Su760/patentmapper/actions/runs/37265506951) passed both jobs (79 backend/SQL tests, 10 Auth/PostgREST tests, 30 frontend tests and lint/typecheck/build) at implementation commit `831420c`. The final documentation-only commit is checked separately; its exact run/status is linked in the final handoff.

Observed development failures, not hidden:

- Initial baseline invocation omitted `PYTHONPATH`: `ModuleNotFoundError: No module named 'app'`; corrected invocation passed 34 tests with five database classes explicitly skipped before services existed.
- Sandbox PostgreSQL startup/socket and frontend server attempts returned `Operation not permitted`; reran with approved local-service access. No production service was used.
- Pre-implementation evidence fixtures failed on missing evidence/API/validator/migration, as expected.
- Initial migration validation used an ambiguous variable/column `p`: `It could refer to either a PL/pgSQL variable or a table column.` Renamed the loop variable and reran real SQL successfully.
- One command used the frontend cwd with root-relative fixture paths: `FileNotFoundError`; reran from root.
- Frontend integration caught a duplicate `gaps` declaration and missing effect dependency; corrected before the passing checks.
- Original fixture expectations failed as `synthetic:US1 != US1` and `running != completed` (synthetic observation jurisdiction differed from the submitted job); corrected only these fixture contracts.
- Whole-page mobile width assertion failed (`false` versus `true`): only the existing nonwrapping toolbar overflowed to 514 px at a 390 px viewport. The final test explicitly checks the new workbench and every child fits; it does not claim the existing toolbar is fixed.

## Limitations and adjacent findings

- `frontend/src/app/globals.css:605`: existing `.pm-sticky-meta` has `flex-shrink: 0` without wrapping and overflows small screens; unchanged under the no-adjacent-fix rule.
- `frontend/package.json:14`: pinned Next.js 14.2.3 emits an installation security warning; dependency upgrade is outside this milestone and was not performed.
- Existing lint warnings remain at `frontend/src/app/layout.tsx:26` and `frontend/src/lib/auth-context.tsx:35`; no new lint warning remains. Dependency deprecation/Browserslist and Playwright color-environment warnings remain.
- The GitHub-connected Vercel automatic preview check reports failure at `831420c`; cause is unverified, as in M2b. No Vercel settings or deployment commands were used.
- Live Lens/Groq/SerpAPI integration, paid claims/ideation, production migration, deployment and Vercel/global-hook diagnostics were intentionally **NOT RUN**. Fixtures verify contracts, not provider uptime or retrieval quality. Known Lens coverage/filter limits remain explicit.
- Old free-form reports and overlap prose remain unverified model inference; this change does not repair historical factual claims. It blocks unknown structured references from appearing as retrieved records.
- No new providers, full-text claims scraping, generated claim-to-quote matrix, automatic paid retries/refunds, full stage replay, broad redesign or quality benchmark was added.

Provider/API field references checked without paid requests: [Lens response schema](https://docs.api.lens.org/response-patent.html), [SerpAPI Google Patents](https://serpapi.com/google-patents-api), [PostgreSQL function semantics](https://www.postgresql.org/docs/current/sql-createfunction.html), [Supabase RLS](https://supabase.com/docs/guides/database/postgres/row-level-security).
