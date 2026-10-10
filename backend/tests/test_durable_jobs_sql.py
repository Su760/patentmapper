"""M2b1 real transaction/fence tests; external execution is tested separately."""

import json
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
import test_milestone1_sql as m1
from test_milestone1_sql import literal
from test_private_analyses import OWNER, OTHER, IDEA


class DurableJobsSQLTest(unittest.TestCase):
    setUpClass = classmethod(m1.Milestone1SQLTest.setUpClass.__func__)

    def setUp(self):
        self.sql.run(
            f"TRUNCATE public.usage_reservations, public.searches, auth.users CASCADE; INSERT INTO auth.users(id) VALUES ('{OWNER}'),('{OTHER}')"
        )
        self.key = str(uuid.uuid4())

    def rpc(self, name, **params):
        args = ",".join(
            f"{k}=>{literal(json.dumps(v) if isinstance(v,(dict,list)) else v)}"
            for k, v in params.items()
        )
        out = self.sql.run(f"SET ROLE service_role; SELECT public.{name}({args})")
        return (out == "t") if out in ("t", "f") else json.loads(out) if out else None

    def admit(self, owner=OWNER, key=None, idea=IDEA, limit=10, version=1):
        return self.rpc(
            "admit_analysis",
            p_user_id=owner,
            p_submission_key=key or self.key,
            p_payload=dict(invention_idea=idea, jurisdiction="us"),
            p_execution_inputs=dict(
                version=version, mock_mode=True, groq_model="fixture", serpapi_enabled=False
            ),
            p_free_limit=limit,
            p_pro_limit=limit,
            p_global_limit=100,
            p_window_seconds=2592000,
        )

    def claim(self):
        return self.rpc("claim_analysis", p_lease_seconds=60, p_max_active=1)

    def expire(self, job):
        self.sql.run(
            f"UPDATE public.analysis_queue SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE search_id='{job}'"
        )

    def test_atomic_admission_rolls_back_reservation_and_search(self):
        self.sql.run(
            "CREATE FUNCTION public.reject_queue() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'queue write failed'; END $$; CREATE TRIGGER reject_queue BEFORE INSERT ON public.analysis_queue FOR EACH ROW EXECUTE FUNCTION public.reject_queue()"
        )
        try:
            with self.assertRaisesRegex(RuntimeError, "queue write failed"):
                self.admit()
            for table in ("searches", "analysis_queue", "usage_reservations"):
                self.assertEqual(
                    self.sql.run(f"SELECT count(*) FROM public.{table}"), "0"
                )
        finally:
            self.sql.run(
                "DROP TRIGGER reject_queue ON public.analysis_queue; DROP FUNCTION public.reject_queue()"
            )

    def test_concurrent_duplicates_lost_response_conflict_and_owner_scope(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            answers = list(pool.map(lambda _: self.admit(limit=1), range(8)))
        self.assertEqual(len({a["job_id"] for a in answers}), 1)
        # Repeat even after allowance exhausted / response discarded: no new charge.
        self.assertEqual(self.admit(limit=0)["job_id"], answers[0]["job_id"])
        self.assertEqual(self.admit(idea=IDEA + " changed")["outcome"], "conflict")
        self.assertNotEqual(self.admit(owner=OTHER)["job_id"], answers[0]["job_id"])
        for table in ("searches", "analysis_queue", "usage_reservations"):
            self.assertEqual(self.sql.run(f"SELECT count(*) FROM public.{table}"), "2")

    def test_two_workers_expired_execution_never_replayed_and_stale_writes_denied(self):
        job = self.admit()["job_id"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = list(pool.map(lambda _: self.claim(), range(2)))
        self.assertEqual(sum(c is not None for c in claims), 1)
        claim = next(c for c in claims if c)
        self.expire(job)
        for name, extra in [
            ("heartbeat_analysis", {"p_lease_seconds": 60}),
            ("stage_analysis", {"p_step": "stale"}),
            ("checkpoint_analysis", {"p_output": {}}),
            ("fail_analysis", {"p_error": "stale"}),
        ]:
            self.assertFalse(
                self.rpc(name, p_search_id=job, p_token=claim["lease_token"], **extra)
            )
        self.assertIsNone(self.claim())
        self.assertEqual(
            self.sql.run(f"SELECT status FROM public.searches WHERE id='{job}'"),
            "interrupted",
        )
        self.assertEqual(
            self.sql.run("SELECT count(*) FROM public.usage_reservations"), "1"
        )

    def test_checkpoint_recovery_fences_old_worker_and_publishes_once(self):
        job = self.admit()["job_id"]
        claim = self.claim()
        output = dict(
            result=dict(
                final_report="Exact\nα",
                white_space_analysis="Gaps",
                clusters=[],
                citation_links=[],
                retrieval_outcome="complete",
                coverage_warnings=[],
            ),
            patents=[dict(patent_id="US1", title="Evidence")],
        )
        self.assertTrue(
            self.rpc(
                "checkpoint_analysis",
                p_search_id=job,
                p_token=claim["lease_token"],
                p_output=output,
            )
        )
        self.expire(job)
        recovered = self.claim()
        self.assertEqual(recovered["state"], "finalizing")
        self.assertNotEqual(recovered["lease_token"], claim["lease_token"])
        self.assertFalse(
            self.rpc("publish_analysis", p_search_id=job, p_token=claim["lease_token"])
        )
        self.assertTrue(
            self.rpc(
                "publish_analysis", p_search_id=job, p_token=recovered["lease_token"]
            )
        )
        self.assertTrue(
            self.rpc(
                "publish_analysis", p_search_id=job, p_token=recovered["lease_token"]
            )
        )
        self.assertEqual(self.sql.run("SELECT count(*) FROM public.patents"), "1")
        self.assertEqual(
            self.sql.run("SELECT final_report FROM public.search_results"), "Exact\nα"
        )

    def test_browser_permissions_and_legacy_service_bypass_closed(self):
        job = self.admit()["job_id"]
        self.sql.run(f"INSERT INTO public.search_results(search_id) VALUES ('{job}')")
        for role in ("anon", "authenticated"):
            for query in (
                "SELECT * FROM public.analysis_queue",
                "SELECT public.claim_analysis(60,1)",
                f"SELECT public.admit_analysis('{OTHER}','{self.key}','{{}}','{{}}',100,100,100,60)",
            ):
                with self.assertRaisesRegex(RuntimeError, "permission denied"):
                    self.sql.run(f"SET ROLE {role}; {query}")
        for query in (
            f"SELECT public.finalize_analysis('{job}','{{}}','[]')",
            f"UPDATE public.searches SET status='completed' WHERE id='{job}'",
            f"INSERT INTO public.search_results(search_id) VALUES ('{job}')",
            f"UPDATE public.analysis_queue SET state='finished' WHERE search_id='{job}'",
            "TRUNCATE public.patents",
            "TRUNCATE public.search_results",
            f"DELETE FROM public.search_results WHERE search_id='{job}'",
        ):
            with self.assertRaisesRegex(RuntimeError, "permission denied|fenced"):
                self.sql.run("SET ROLE service_role; " + query)

    def test_invalid_checkpoint_cannot_trap_recovery_or_block_next_job(self):
        first = self.admit()["job_id"]
        claimed = self.claim()
        bad = dict(
            result=dict(
                final_report="",
                white_space_analysis="",
                clusters=[],
                citation_links=[],
                coverage_warnings=[],
                retrieval_outcome="complete",
            ),
            patents=[dict(patent_id="US1", title="Evidence")],
        )
        with self.assertRaisesRegex(RuntimeError, "requires evidence and a report"):
            self.rpc(
                "checkpoint_analysis",
                p_search_id=first,
                p_token=claimed["lease_token"],
                p_output=bad,
            )
        self.assertEqual(
            self.sql.run(
                f"SELECT state FROM public.analysis_queue WHERE search_id='{first}'"
            ),
            "running",
        )
        self.assertEqual(
            self.sql.run(
                f"SELECT result_snapshot IS NULL FROM public.analysis_queue WHERE search_id='{first}'"
            ),
            "t",
        )
        second = self.admit(key=str(uuid.uuid4()))["job_id"]
        self.expire(first)
        self.assertEqual(self.claim()["search_id"], second)

    def test_forward_migration_keeps_ownerless_legacy_processing_hidden(self):
        self.sql.apply(m1.ROOT / "supabase/tests/bootstrap.sql")
        for path in [p for p in sorted((m1.ROOT / "supabase/migrations").glob("*.sql")) if p.name < "202610040001_durable_jobs.sql"]:
            self.sql.apply(path)
        self.sql.run(
            f"INSERT INTO auth.users(id) VALUES ('{OWNER}'); INSERT INTO public.searches(user_id,invention_idea,status) VALUES ('{OWNER}','Owned legacy','processing'); ALTER TABLE public.searches DROP CONSTRAINT searches_owner_required; INSERT INTO public.searches(invention_idea,status) VALUES ('Hidden legacy','processing'); ALTER TABLE public.searches ADD CONSTRAINT searches_owner_required CHECK(user_id IS NOT NULL) NOT VALID"
        )
        self.sql.apply(m1.ROOT / "supabase/migrations/202610040001_durable_jobs.sql")
        self.assertEqual(
            self.sql.run(
                "SELECT status FROM public.searches WHERE user_id IS NOT NULL"
            ),
            "interrupted",
        )
        self.assertEqual(
            self.sql.run("SELECT status FROM public.searches WHERE user_id IS NULL"),
            "processing",
        )
        self.assertEqual(
            self.sql.run("SELECT count(*) FROM public.analysis_queue"), "0"
        )
        self.assertEqual(
            self.sql.run(
                f"SET ROLE authenticated; SET request.jwt.claim.sub='{OWNER}'; SELECT count(*) FROM public.searches WHERE user_id IS NULL"
            ),
            "0",
        )

    def test_repeated_publication_failure_does_not_starve_queued_work(self):
        first = self.admit()["job_id"]
        claim = self.claim()
        output = dict(
            result=dict(
                final_report="Saved report",
                white_space_analysis="",
                clusters=[],
                citation_links=[],
                coverage_warnings=[],
                retrieval_outcome="complete",
            ),
            patents=[dict(patent_id="US1", title="Evidence")],
        )
        self.rpc(
            "checkpoint_analysis",
            p_search_id=first,
            p_token=claim["lease_token"],
            p_output=output,
        )
        second = self.admit(key=str(uuid.uuid4()))["job_id"]
        self.sql.run(
            "CREATE FUNCTION public.reject_publish() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'persistent publication failure'; END $$; CREATE TRIGGER reject_publish BEFORE INSERT ON public.patents FOR EACH ROW EXECUTE FUNCTION public.reject_publish()"
        )
        try:
            with self.assertRaisesRegex(RuntimeError, "persistent publication failure"):
                self.rpc(
                    "publish_analysis", p_search_id=first, p_token=claim["lease_token"]
                )
            self.expire(first)
            retry = self.claim()
            self.assertEqual(retry["search_id"], first)
            with self.assertRaisesRegex(RuntimeError, "persistent publication failure"):
                self.rpc(
                    "publish_analysis", p_search_id=first, p_token=retry["lease_token"]
                )
            self.expire(first)
            self.assertEqual(self.claim()["search_id"], second)
            self.assertEqual(
                self.sql.run(
                    f"SELECT result_snapshot->'result'->>'final_report' FROM public.analysis_queue WHERE search_id='{first}'"
                ),
                "Saved report",
            )
            self.assertEqual(
                self.sql.run("SELECT count(*) FROM public.usage_reservations"), "2"
            )
        finally:
            self.sql.run(
                "DROP TRIGGER reject_publish ON public.patents; DROP FUNCTION public.reject_publish()"
            )
