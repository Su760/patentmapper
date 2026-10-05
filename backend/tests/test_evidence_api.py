"""Owner-only saved evidence reads and overlap reference validation."""
import unittest
from unittest.mock import AsyncMock
from types import SimpleNamespace
import test_private_analyses as security
from test_evidence_sql import evidence_output

class EvidenceAPITest(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=security.PrivateAnalysesTest.asyncSetUp
    asyncTearDown=security.PrivateAnalysesTest.asyncTearDown
    request=security.PrivateAnalysesTest.request

    async def test_owner_reads_legacy_known_and_unknown_versions_without_paid_calls(self):
        rows=[*evidence_output()['patents'],{'patent_id':'legacy','title':'Old','abstract':'Old exact text'},
              {'patent_id':'future','title':'Future','evidence':{'version':99}}]
        self.db.rows['patents']=[{**p,'search_id':security.JOB} for p in rows]
        for _ in range(2):
            r=await self.request('GET',f'/api/jobs/{security.JOB}/evidence')
            self.assertEqual(r.status_code,200)
            data=r.json()['patents']
            self.assertEqual(data[0]['evidence'],rows[0]['evidence'])
            self.assertEqual(data[1]['evidence_status'],'legacy_unknown')
            self.assertEqual(data[1]['abstract'],'Old exact text')
            self.assertEqual(data[2]['evidence_status'],'unsupported_version')
            self.assertIsNone(data[2]['evidence'])
        self.model.assert_not_awaited(); self.lens.assert_not_awaited(); self.serp.assert_not_awaited()
        self.assertEqual(self.db.reservations,[])

    async def test_foreign_unauthenticated_and_ownerless_reads_are_denied(self):
        for token,status in ((None,401),('other',404),('invalid',401)):
            r=await self.request('GET',f'/api/jobs/{security.JOB}/evidence',token=token)
            self.assertEqual(r.status_code,status)
        r=await self.request('GET',f'/api/jobs/{security.LEGACY}/evidence')
        self.assertEqual(r.status_code,404)
        self.assertEqual(self.db.reservations,[])
        self.model.assert_not_awaited()

    async def test_overlap_unknown_ids_filtered_and_visible_on_reopen(self):
        self.model.return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"claims":[{"patent_id":"ghost"},{"patent_id":"fixture","title":"Invented title"}]}'))])
        r=await self.request('POST',f'/api/jobs/{security.JOB}/analyze-claims')
        self.assertEqual(r.status_code,200)
        self.assertEqual([c['patent_id'] for c in r.json()['claims']],['fixture'])
        self.assertTrue(r.json()['warnings'])
        prompt=self.model.call_args.kwargs['messages'][1]['content']
        self.assertIn('inference',prompt)
        # Store raw response so free reads also protect old cached model output.
        self.db.rows['search_results'][0]['claims_analysis']=[{'patent_id':'ghost'},{'patent_id':'fixture'}]
        cached=await self.request('GET',f'/api/jobs/{security.JOB}/analyze-claims')
        self.assertEqual([c['patent_id'] for c in cached.json()['claims']],['fixture'])
        self.assertTrue(cached.json()['warnings'])
