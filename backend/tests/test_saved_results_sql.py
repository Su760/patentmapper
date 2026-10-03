"""Disposable PostgreSQL finalization transactions and function permissions."""
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
import test_milestone1_sql as m1
from test_milestone1_sql import literal
from test_private_analyses import OWNER, JOB
from test_saved_results import REPORT, PATENT


class SavedResultsSQLTest(unittest.TestCase):
    setUpClass = classmethod(m1.Milestone1SQLTest.setUpClass.__func__)

    def setUp(self):
        self.sql.run(f"TRUNCATE public.usage_reservations, public.searches, auth.users CASCADE; INSERT INTO auth.users(id,is_anonymous) VALUES ('{OWNER}',false); INSERT INTO public.searches(id,user_id,invention_idea,status) VALUES ('{JOB}','{OWNER}','Synthetic invention','processing')")
        self.result = dict(final_report=REPORT, white_space_analysis="Separate gaps", clusters=[], citation_links=[], retrieval_outcome="partial", coverage_warnings=["Partial coverage"])

    def query(self, patents=None, result=None, role="service_role"):
        return f"SET ROLE {role}; SELECT public.finalize_analysis('{JOB}',{literal(json.dumps(result if result is not None else self.result))}::jsonb,{literal(json.dumps(patents if patents is not None else [PATENT]))}::jsonb)"

    def snapshot(self):
        return self.sql.run(f"SELECT jsonb_build_object('job',(SELECT to_jsonb(s) FROM public.searches s WHERE id='{JOB}'),'results',(SELECT jsonb_agg(r) FROM public.search_results r),'patents',(SELECT jsonb_agg(p) FROM public.patents p))")

    def test_exact_report_roundtrip_and_terminal_retry_preserves_claims(self):
        self.assertEqual(self.sql.run(self.query([PATENT, {**PATENT, 'search_id':'00000000-0000-0000-0000-000000000099', 'id':JOB}])), "saved")
        row = json.loads(self.sql.run("SELECT to_jsonb(r) FROM public.search_results r"))
        self.assertEqual(row["final_report"], REPORT)
        self.assertEqual(row["white_space_analysis"], "Separate gaps")
        self.assertEqual(row["coverage_warnings"], ["Partial coverage"])
        self.sql.run("UPDATE public.search_results SET claims_analysis='[{\"title\":\"Keep claims\"}]'")
        before = self.snapshot()
        self.assertEqual(self.sql.run(self.query(result={**self.result, "final_report":"Changed"})), "already_finalized")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.sql.run("SELECT count(*) FROM public.patents"), "1")
        self.assertEqual(self.sql.run("SELECT search_id FROM public.patents"), JOB)

    def test_mid_write_failure_rolls_back_and_retry_replaces_partial_rows(self):
        self.sql.run(f"INSERT INTO public.search_results(search_id,white_space_analysis,claims_analysis) VALUES ('{JOB}','Legacy partial','[]'); INSERT INTO public.patents(search_id,patent_id) VALUES ('{JOB}','OLD'); CREATE FUNCTION public.reject_fixture() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected mid-write failure'; END $$; CREATE TRIGGER reject_fixture BEFORE INSERT ON public.patents FOR EACH ROW EXECUTE FUNCTION public.reject_fixture()")
        before = self.snapshot()
        try:
            with self.assertRaisesRegex(RuntimeError, "injected mid-write failure"):
                self.sql.run(self.query())
            self.assertEqual(self.snapshot(), before)
            self.assertEqual(self.sql.run("SELECT status FROM public.searches"), "processing")
        finally:
            self.sql.run("DROP TRIGGER reject_fixture ON public.patents; DROP FUNCTION public.reject_fixture()")
        # The worker may have recorded failure after the rolled-back write.
        self.sql.run("UPDATE public.searches SET status='failed',error_message='Save failed'")
        self.assertEqual(self.sql.run(self.query()), "saved")
        self.assertEqual(self.sql.run("SELECT status FROM public.searches"), "completed")
        self.assertEqual(self.sql.run("SELECT error_message IS NULL FROM public.searches"), "t")
        self.assertEqual(self.sql.run("SELECT patent_id FROM public.patents"), "US1")
        self.assertEqual(self.sql.run("SELECT claims_analysis FROM public.search_results"), "[]")

    def test_concurrent_finalizations_write_once(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(lambda _: self.sql.run(self.query()), range(8)))
        self.assertEqual(outcomes.count("saved"), 1)
        self.assertEqual(outcomes.count("already_finalized"), 7)
        self.assertEqual(self.sql.run("SELECT count(*) FROM public.patents"), "1")
        self.assertEqual(self.sql.run("SELECT count(*) FROM public.search_results"), "1")

    def test_empty_evidence_has_no_conclusions_and_legacy_report_stays_null(self):
        self.sql.run(f"INSERT INTO public.search_results(search_id,white_space_analysis) VALUES ('{JOB}','Legacy gap text')")
        self.assertEqual(self.sql.run("SELECT final_report IS NULL FROM public.search_results"), "t")
        empty = dict(final_report="",white_space_analysis="",clusters=[],citation_links=[],retrieval_outcome="insufficient_evidence",coverage_warnings=[])
        self.assertEqual(self.sql.run(self.query([],empty)), "saved")
        self.assertEqual(self.sql.run("SELECT status FROM public.searches"), "insufficient_evidence")
        self.assertEqual(self.sql.run("SELECT final_report IS NULL FROM public.search_results"), "t")
        self.assertEqual(self.sql.run("SELECT count(*) FROM public.patents"), "0")

    def test_browser_roles_cannot_finalize_and_bad_input_cannot_complete(self):
        for role in ("anon", "authenticated"):
            with self.assertRaisesRegex(RuntimeError,"permission denied"):
                self.sql.run(self.query(role=role))
        for patents, result in (([],self.result), ([{"patent_id":""}],self.result), ([PATENT],{**self.result,"final_report":""})):
            with self.assertRaises(RuntimeError): self.sql.run(self.query(patents,result))
            self.assertEqual(self.sql.run("SELECT status FROM public.searches"),"processing")
            self.assertEqual(self.sql.run("SELECT count(*) FROM public.search_results"),"0")
