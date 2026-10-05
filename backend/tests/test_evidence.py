"""Deterministic M3a fixtures; no network or paid calls."""
import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from app.services.patent_api import fetch_lens_patents, fetch_serpapi_patents
from app.agents.nodes.deduplicator import deduplicator_node

TEXT = '  Exact α\nsecond line &hellip;  '

def client_for(data):
    response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: data)
    return SimpleNamespace(post=AsyncMock(return_value=response), get=AsyncMock(return_value=response))

class EvidenceTest(unittest.IsolatedAsyncioTestCase):
    async def lens(self, record, query='first'):
        return (await inspect.unwrap(fetch_lens_patents)(query, client_for({'data':[record]}), 'fixture', jurisdiction='ep'))[0]

    async def test_lens_preserves_abstract_variants_ids_dates_and_no_filter_claim(self):
        p = await self.lens({'lens_id':'123', 'abstract':[{'text':TEXT,'lang':'en'},{'text':'Bonjour','lang':'fr'}],
            'date_published':'2024-03-02', 'biblio':{'invention_title':[{'text':'Title','lang':'en'}],
            'priority_claims':{'earliest_claim':{'date':'2019-01-01'}}, 'application_reference':{'date':'2020-02-01'},
            'publication_reference':{'jurisdiction':'US','doc_number':'123','kind':'B2'}}})
        self.assertEqual(p['patent_id'], 'lens:123')
        observations = p['evidence']['observations']
        self.assertEqual([o['text'] for o in observations], [TEXT,'Bonjour'])
        o = observations[0]
        self.assertEqual(o['provider_record_id'],'123')
        self.assertEqual(o['publication_id'],'US123B2')
        self.assertEqual(o['text_type'],'abstract')
        self.assertEqual(o['dates'],{'priority':'2019-01-01','filing':'2020-02-01','publication':'2024-03-02'})
        self.assertEqual(o['matching_queries'],['first'])
        self.assertEqual(o['requested_jurisdiction'],'ep')
        self.assertIsNone(o['jurisdiction_filter'])
        self.assertIn('not applied',' '.join(o['coverage_limitations']))
        self.assertTrue(o['retrieved_at'].endswith('+00:00'))

    async def test_serp_snippet_is_not_abstract_or_filing_date(self):
        client=client_for({'organic_results':[{'patent_id':'patent/US123/en','publication_number':'US123A1',
            'patent_link':'https://patents.google.com/patent/US123/en','title':'Title','snippet':TEXT,
            'priority_date':'2018-01-01','publication_date':'2021-01-01'}]})
        p=(await fetch_serpapi_patents('query',client,'fixture','us'))[0]
        o=p['evidence']['observations'][0]
        self.assertEqual(o['text'],TEXT)
        self.assertEqual(o['text_type'],'search_snippet')
        self.assertEqual(o['provider_record_id'],'patent/US123/en')
        self.assertEqual(o['publication_id'],'US123A1')
        self.assertIsNone(o['dates']['filing'])
        self.assertIsNone(p.get('filing_year'))
        self.assertEqual(o['jurisdiction_filter'],{'country':'US'})
        self.assertEqual(client.get.call_args.kwargs['params']['country'],'US')

    async def test_title_only_missing_publication_and_string_abstract(self):
        p=await self.lens({'lens_id':'only','biblio':{'invention_title':[{'text':' Only title '}]}})
        o=p['evidence']['observations'][0]
        self.assertEqual(o['text_type'],'title_only')
        self.assertEqual(o['text'],' Only title ')
        self.assertIsNone(o['publication_id'])
        self.assertEqual(o['dates'],dict(priority=None,filing=None,publication=None))
        p=await self.lens({'lens_id':'string','abstract':TEXT})
        self.assertEqual(p['evidence']['observations'][0]['text'],TEXT)

    async def test_dedup_keeps_query_observations_and_no_cross_provider_equivalence(self):
        a=await self.lens({'lens_id':'same','abstract':TEXT})
        b=await self.lens({'lens_id':'same','abstract':'Different exact text'},'second')
        c=(await fetch_serpapi_patents('first',client_for({'organic_results':[{'patent_id':'same','snippet':TEXT}]}),'fixture'))[0]
        with patch('app.agents.nodes.deduplicator.update_stage',new=AsyncMock()):
            result=await deduplicator_node({'search_id':'fixture','raw_patents':[a,b,c,a]},None)
        rows=result['deduped_patents']
        self.assertEqual(len(rows),2)
        self.assertEqual([o['matching_queries'] for o in rows[0]['evidence']['observations']],[['first'],['second']])
        self.assertEqual(rows[1]['patent_id'],'serpapi:same')

    async def test_structured_refs_excluded_deterministically_and_metrics_suppressed(self):
        from app.services import evidence
        validate = getattr(evidence, 'validate_references', None)
        self.assertIsNotNone(validate, 'Reference validator is required')
        patents=[{'patent_id':'lens:1'}]
        clusters=[{'theme_name':'A','patent_ids':['lens:1','ghost','lens:1',None], 'filing_trend':[{'year':2000,'count':5}]}]
        links=[{'source':'ghost','target':'lens:1'}, {'source':'lens:1','target':'lens:1'},
               {'source':[], 'target':'lens:1'}]
        c,l,w=validate(clusters,links,patents)
        self.assertEqual(c[0]['patent_ids'],['lens:1'])
        self.assertEqual(c[0]['filing_trend'],[])
        self.assertEqual(l,[])
        self.assertTrue(w)
        self.assertEqual((c,l,w),validate(clusters,links,patents))
        _,l,_=validate([], [{'source':'lens:1','target':'serpapi:2','strength':0.8,'is_ai_inferred':False}],patents+[{'patent_id':'serpapi:2'}])
        self.assertTrue(l[0]['is_ai_inferred'])

    async def test_mock_graph_cluster_ids_match_synthetic_evidence(self):
        from app.agents.nodes.clusterer import clusterer_node
        from app.agents.nodes.fetcher import fetcher_node
        from app.core.config import settings
        state={'search_id':'fixture','search_queries':['query'], 'jurisdiction':'wo'}
        with patch('app.agents.nodes.fetcher.update_stage',new=AsyncMock()), patch('app.agents.nodes.clusterer.update_stage',new=AsyncMock()), patch.object(settings,'mock_mode',True):
            fetched=await fetcher_node(state,None)
            result=await clusterer_node({**state,'deduped_patents':fetched['raw_patents']},None)
        allowed={p['patent_id'] for p in fetched['raw_patents']}
        self.assertTrue(all(pid in allowed for c in result['clusters'] for pid in c['patent_ids']))
        self.assertTrue(all(not c.get('filing_trend') for c in result['clusters']))

    async def test_records_without_provider_identity_are_not_usable_evidence(self):
        rows=await inspect.unwrap(fetch_lens_patents)('q',client_for({'data':[{'abstract':TEXT}]}),'fixture')
        self.assertEqual(rows,[])
        rows=await fetch_serpapi_patents('q',client_for({'organic_results':[{'title':'Title','snippet':TEXT}]}),'fixture')
        self.assertEqual(rows,[])

    async def test_title_only_keeps_language_variants_and_malformed_members_warn(self):
        p=await self.lens({'lens_id':'title','biblio':{'invention_title':[{'text':'Titre exact','lang':'fr'},{'text':'Exact title','lang':'en'}]}})
        observations=p['evidence']['observations']
        self.assertEqual([(o['text'],o['language']) for o in observations],[('Titre exact','fr'),('Exact title','en')])
        from app.services.evidence import validate_references
        c,_,warnings=validate_references([{'patent_ids':'lens:1'}],[],[{'patent_id':'lens:1'}])
        self.assertEqual(c[0]['patent_ids'],[])
        self.assertTrue(warnings)
        from app.services.evidence import filter_claims
        self.assertTrue(filter_claims({"patent_id":"lens:1"}, [])[1])

    async def test_real_model_nodes_validate_ids_before_downstream_use(self):
        from app.agents.nodes.clusterer import clusterer_node
        from app.agents.nodes.reporter import reporter_node
        from app.core.config import settings
        import json
        def response(value):
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(value)))])
        patents=[{'patent_id':'lens:1','title':'One','abstract':TEXT},{'patent_id':'serpapi:2','title':'Two','abstract':TEXT}]
        state={'search_id':'fixture','deduped_patents':patents,'invention_idea':'Idea','white_space_analysis':''}
        with patch.object(settings,'mock_mode',False), patch('app.agents.nodes.clusterer.update_stage',new=AsyncMock()), patch('app.agents.nodes.clusterer.AsyncGroq'), patch('app.agents.nodes.clusterer.create_chat_completion',new=AsyncMock(return_value=response({'clusters':[{'theme_name':'Test','patent_ids':['lens:1','ghost']}]}))):
            clustered=await clusterer_node(state,None)
        self.assertEqual(clustered['clusters'][0]['patent_ids'],['lens:1'])
        self.assertTrue(clustered['analysis_warnings'])
        with patch.object(settings,'mock_mode',False), patch('app.agents.nodes.reporter.update_stage',new=AsyncMock()), patch('app.agents.nodes.reporter.AsyncGroq'), patch('app.agents.nodes.reporter.create_chat_completion',new=AsyncMock(side_effect=[response('Report'),response([{'source':'lens:1','target':'ghost'},{'source':'lens:1','target':'serpapi:2','strength':.8}])])):
            reported=await reporter_node({**state,**clustered},None)
        self.assertEqual(len(reported['citation_links']),1)
        self.assertTrue(reported['citation_links'][0]['is_ai_inferred'])
        self.assertGreater(len(reported['analysis_warnings']),len(clustered['analysis_warnings']))

    async def test_unsupported_execution_version_never_builds_graph(self):
        from app.worker import run_claim
        from test_saved_results import claim
        for version in (1,99):
            job=claim(); job['execution_inputs']['version']=version
            calls=[]
            async def execute(name, params):
                calls.append((name,params)); return SimpleNamespace(data=True)
            db=SimpleNamespace(rpc=lambda name,params: SimpleNamespace(execute=lambda:execute(name,params)))
            with patch('app.worker.build_graph') as graph:
                await run_claim(db,job)
                graph.assert_not_called()
            self.assertIn('fail_analysis',[name for name,_ in calls])
