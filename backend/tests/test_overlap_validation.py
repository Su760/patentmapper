"""Overlap parsers reject unsafe records without inventing or charging on reads."""
import copy
import json
import unittest
from types import SimpleNamespace

import test_private_analyses as security
from app.services.evidence import filter_claims

VALID = dict(patent_id='fixture', title='Model title', likely_claims=['Saved inference'],
             overlap_level='low', overlap_explanation='Limited conceptual overlap',
             differentiators='Different control mechanism')


def malformed_records():
    for field in VALID:
        for bad in (None, {}, 4, True):
            yield {**VALID, field: bad}
        value = dict(VALID)
        del value[field]
        yield value
    for bad in ('text', [None], [{}], [4], [['nested']]):
        yield {**VALID, 'likely_claims': bad}
    for bad in ('HIGH', 'unknown', '', []):
        yield {**VALID, 'overlap_level': bad}


class OverlapShapeTest(unittest.TestCase):
    def test_known_id_with_null_aspects_is_excluded(self):
        claims, warnings = filter_claims([{**VALID, 'likely_claims': None}], [{'patent_id':'fixture','title':'Saved title'}])
        self.assertEqual(claims, [])
        self.assertTrue(warnings)

    def test_complete_shape_and_duplicates_preserve_valid_content(self):
        patents = [{'patent_id':'fixture','title':'Saved title'}]
        for record in malformed_records():
            with self.subTest(record=record):
                clean, warnings = filter_claims([record, VALID, VALID], patents)
                self.assertEqual(clean, [{**VALID, 'title':'Saved title'}])
                self.assertTrue(warnings)
        for level in ('high','medium','low','none'):
            valid = {**VALID, 'overlap_level':level, 'likely_claims':[]}
            self.assertEqual(filter_claims([valid], patents), ([{**valid,'title':'Saved title'}], []))


class OverlapAPITest(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = security.PrivateAnalysesTest.asyncSetUp
    asyncTearDown = security.PrivateAnalysesTest.asyncTearDown
    request = security.PrivateAnalysesTest.request

    async def test_generated_records_are_filtered_and_warnings_survive_free_reopen(self):
        records = [{**VALID, 'likely_claims':None}, VALID, {**VALID,'patent_id':'ghost'}]
        self.model.return_value = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({'claims':records})))])
        generated = await self.request('POST', f'/api/jobs/{security.JOB}/analyze-claims')
        self.assertEqual(generated.status_code, 200)
        self.assertEqual(generated.json()['claims'], [{**VALID, 'title':'Fixture'}])
        self.assertTrue(generated.json()['warnings'])
        stored = copy.deepcopy(self.db.rows['search_results'][0]['claims_analysis'])
        for _ in range(2):
            reopened = await self.request('GET', f'/api/jobs/{security.JOB}/analyze-claims')
            self.assertEqual(reopened.json(), generated.json())
        self.assertEqual(self.db.rows['search_results'][0]['claims_analysis'], stored)
        self.assertEqual(self.model.await_count, 1)
        self.assertEqual(self.db.reservations, [(security.OWNER, 'claims')])

    async def test_legacy_lists_and_malformed_cache_envelopes_are_free_and_read_only(self):
        cases = [([VALID], False), ([{**VALID,'likely_claims':None},VALID], True),
                 ({'version':1,'claims':[VALID],'warnings':['Saved warning']}, True),
                 ({'version':1,'claims':[VALID],'warnings':None}, True),
                 ({'version':1,'claims':[VALID],'warnings':[{},'Saved warning']}, True),
                 ({'version':1,'claims':[VALID],'warnings':'not a list'}, True),
                 ({'version':1,'claims':None}, True), ({'version':1}, True),
                 ({'version':99,'claims':[VALID]}, True), ({'version':True,'claims':[VALID]}, True),
                 ({'version':1.0,'claims':[VALID]}, True), ('invalid', True)]
        for cached, warn in cases:
            with self.subTest(cached=cached):
                self.db.rows['search_results'][0]['claims_analysis'] = copy.deepcopy(cached)
                response = await self.request('GET', f'/api/jobs/{security.JOB}/analyze-claims')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(bool(response.json().get('warnings')), warn)
                self.assertTrue(all(isinstance(w,str) for w in response.json().get('warnings',[])))
                self.assertEqual(self.db.rows['search_results'][0]['claims_analysis'],cached)
        self.model.assert_not_awaited()
        self.assertEqual(self.db.reservations, [])

    async def test_malformed_generated_collection_is_saved_with_visible_warning(self):
        for body in ({}, {'claims':None}, {'claims':{}}, [], None):
            self.db.reservations.clear()
            self.model.return_value = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(body)))])
            response = await self.request('POST', f'/api/jobs/{security.JOB}/analyze-claims')
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()['claims'],[])
            self.assertTrue(response.json()['warnings'])
