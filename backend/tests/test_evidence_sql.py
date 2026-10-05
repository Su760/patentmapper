"""M3a evidence persistence and compatibility in disposable real PostgreSQL."""
import json
import uuid
import unittest
import test_milestone1_sql as m1
import test_durable_jobs_sql as queue
from test_private_analyses import OWNER, OTHER
from app.services.evidence import observation, with_evidence


def evidence_output():
    patent=with_evidence(dict(title='Exact title',abstract='  α\ntext &hellip;  ',url='https://lens.org/lens/patent/1'),[
        observation(provider='lens',record_id='1',publication_id=None,url='https://lens.org/lens/patent/1',
            query='one',text='  α\ntext &hellip;  ',text_type='abstract',jurisdiction='ep',dates={'priority':'2000-01-01'})])
    import copy
    second=copy.deepcopy(patent['evidence']['observations'][0])
    second.update(matching_queries=['two'],text='Second observation.\nExact.')
    patent['evidence']['observations'].append(second)
    return dict(result=dict(final_report='Saved',white_space_analysis='',clusters=[],citation_links=[],coverage_warnings=[],
        retrieval_outcome='complete',evidence_version=1,requested_jurisdiction='ep',analysis_warnings=['Visible exclusion']),patents=[patent])

class EvidenceSQLTest(unittest.TestCase):
    setUpClass=classmethod(m1.Milestone1SQLTest.setUpClass.__func__)
    setUp=queue.DurableJobsSQLTest.setUp
    rpc=queue.DurableJobsSQLTest.rpc
    admit=queue.DurableJobsSQLTest.admit
    claim=queue.DurableJobsSQLTest.claim
    expire=queue.DurableJobsSQLTest.expire

    def test_exact_roundtrip_fencing_rls_and_atomic_rollback(self):
        job=self.admit()['job_id']; claim=self.claim(); output=evidence_output()
        self.assertTrue(self.rpc('checkpoint_analysis',p_search_id=job,p_token=claim['lease_token'],p_output=output))
        self.sql.run("CREATE FUNCTION public.reject_evidence() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'fixture rollback'; END $$; CREATE TRIGGER reject_evidence BEFORE INSERT ON public.patents FOR EACH ROW EXECUTE FUNCTION public.reject_evidence()")
        try:
            with self.assertRaisesRegex(RuntimeError,'fixture rollback'):
                self.rpc('publish_analysis',p_search_id=job,p_token=claim['lease_token'])
            self.assertEqual(self.sql.run('SELECT count(*) FROM public.search_results'),'0')
        finally:
            self.sql.run('DROP TRIGGER reject_evidence ON public.patents; DROP FUNCTION public.reject_evidence()')
        self.expire(job); recovered=self.claim()
        self.assertFalse(self.rpc('publish_analysis',p_search_id=job,p_token=claim['lease_token']))
        self.assertTrue(self.rpc('publish_analysis',p_search_id=job,p_token=recovered['lease_token']))
        self.assertEqual(json.loads(self.sql.run('SELECT evidence FROM public.patents')),output['patents'][0]['evidence'])
        self.assertEqual(self.sql.run('SELECT requested_jurisdiction FROM public.search_results'),'ep')
        for user,count in ((OWNER,'1'),(OTHER,'0')):
            self.assertEqual(self.sql.run(f"SET ROLE authenticated; SET request.jwt.claim.sub='{user}'; SELECT count(evidence) FROM public.patents"),count)
        with self.assertRaisesRegex(RuntimeError,'fenced'):
            self.sql.run("SET ROLE service_role; UPDATE public.patents SET evidence=NULL")
        self.assertTrue(self.rpc('publish_analysis',p_search_id=job,p_token=recovered['lease_token']))
        self.assertEqual(self.sql.run('SELECT count(*) FROM public.patents'),'1')

    def test_upgrade_queued_running_and_legacy_finalizing(self):
        self.sql.apply(m1.ROOT/'supabase/tests/bootstrap.sql')
        for p in sorted((m1.ROOT/'supabase/migrations').glob('*.sql')):
            if p.name < '202610040002_evidence_workbench.sql': self.sql.apply(p)
        self.setUp()
        finalized=self.admit()['job_id']; claim=self.claim()
        output=evidence_output(); output['result'].pop('evidence_version'); output['patents'][0].pop('evidence')
        self.rpc('checkpoint_analysis',p_search_id=finalized,p_token=claim['lease_token'],p_output=output)
        self.expire(finalized)
        running=self.admit(key=str(uuid.uuid4()))['job_id']
        # Claim the legacy finalizer then allow capacity for running fixture.
        old=self.rpc('claim_analysis',p_lease_seconds=60,p_max_active=2)
        self.rpc('claim_analysis',p_lease_seconds=60,p_max_active=2)
        queued=self.admit(key=str(uuid.uuid4()))['job_id']
        self.sql.apply(m1.ROOT/'supabase/migrations/202610040002_evidence_workbench.sql')
        self.assertEqual(self.sql.run(f"SELECT execution_inputs->>'version' FROM public.analysis_queue WHERE search_id='{queued}'"),'2')
        self.assertEqual(self.sql.run(f"SELECT state FROM public.analysis_queue WHERE search_id='{running}'"),'interrupted')
        self.assertTrue(self.rpc('publish_analysis',p_search_id=finalized,p_token=old['lease_token']))
        self.assertEqual(self.sql.run('SELECT evidence IS NULL FROM public.patents'),'t')

    def test_unknown_version_or_malformed_evidence_checkpoint_rejected(self):
        job=self.admit(version=2)['job_id']; claim=self.claim()
        for mutation in ('unknown','missing','bad_type','missing_result_version','unknown_reference'):
            output=evidence_output()
            if mutation=='missing_result_version': output['result'].pop('evidence_version')
            if mutation=='unknown_reference': output['result']['clusters']=[{'patent_ids':['ghost']}]
            if mutation=='unknown': output['patents'][0]['evidence']['version']=99
            if mutation=='missing': output['patents'][0].pop('evidence')
            if mutation=='bad_type': output['patents'][0]['evidence']['observations'][0]['text_type']='claims'
            with self.assertRaisesRegex(RuntimeError,'evidence'):
                self.rpc('checkpoint_analysis',p_search_id=job,p_token=claim['lease_token'],p_output=output)
