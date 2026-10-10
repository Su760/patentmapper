"""M2a pipeline regressions: no live model, patent or database calls."""
import unittest
import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.worker import run_claim
from app.agents.graph import build_graph
from app.agents.nodes.fetcher import fetcher_node
from app.services.patent_api import fetch_lens_patents, fetch_serpapi_patents
from app.core.config import settings
from security_fixtures import MemoryDB

JOB = "10000000-0000-0000-0000-000000000001"
from app.services.evidence import observation, with_evidence
PATENT = with_evidence({"patent_id": "US1", "title": "Synthetic patent", "abstract": "Evidence"}, [observation(
    provider="synthetic", record_id="US1", publication_id=None, url=None, query="", text="Evidence",
    text_type="synthetic", jurisdiction="all", dates={})])
REPORT = "# Exact report\n\nDistinct from gaps. Unicode: α\n"


def state():
    return dict(search_id=JOB, lease_token=JOB, invention_idea="Synthetic irrigation invention", jurisdiction="all",
                search_queries=["query"], raw_patents=[], deduped_patents=[PATENT], clusters=[],
                white_space_analysis="Separate gaps", final_report=REPORT, citation_links=[],
                retrieval_outcome="complete", coverage_warnings=[], errors=[])


def claim():
    return dict(search_id=JOB, lease_token=JOB, state="running", payload=dict(invention_idea="idea",jurisdiction="all"),
                execution_inputs=dict(version=2,mock_mode=False,serpapi_enabled=False,groq_model="fixture"))


class SavedResultsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = MemoryDB()
        self.db.rows["searches"] = [{"id": JOB, "status": "processing"}]

    async def test_exact_report_and_coverage_use_single_finalization_rpc(self):
        final = state()
        final.update(retrieval_outcome="partial", coverage_warnings=["Coverage warning"])
        rpc = AsyncMock(return_value=SimpleNamespace(data=True))
        self.db.rpc = Mock(return_value=SimpleNamespace(execute=rpc))
        with patch("app.worker.build_graph", return_value=SimpleNamespace(ainvoke=AsyncMock(return_value=final))):
            await run_claim(self.db, claim())
        args = next(c.args[1]["p_output"] for c in self.db.rpc.call_args_list if c.args[0] == "checkpoint_analysis")
        self.assertEqual(args["result"]["final_report"], REPORT)
        self.assertEqual(args["result"]["white_space_analysis"], "Separate gaps")
        self.assertEqual(args["result"]["coverage_warnings"], ["Coverage warning"])
        self.assertFalse(any(table in ("patents", "search_results") for table, _, _ in self.db.writes))

    async def test_lost_finalization_response_does_not_downgrade_completion(self):
        async def lost_response():
            self.db.rows["searches"][0]["status"] = "completed"
            raise RuntimeError("database response lost after commit")
        self.db.rpc = lambda name, *_: SimpleNamespace(execute=lost_response if name == "publish_analysis" else AsyncMock(return_value=SimpleNamespace(data=True)))
        with patch("app.worker.build_graph", return_value=SimpleNamespace(ainvoke=AsyncMock(return_value=state()))):
            await run_claim(self.db, claim())
        self.assertEqual(self.db.rows["searches"][0]["status"], "completed")

    async def test_total_failure_empty_and_partial_are_distinct(self):
        for lens, serp, expected in ((RuntimeError("lens"), RuntimeError("serp"), "failure"),
                                     ([], [], "insufficient_evidence"),
                                     ([], RuntimeError("fallback"), "insufficient_evidence"),
                                     (RuntimeError("lens"), [PATENT], "partial"),
                                     ([PATENT], [], "complete")):
            with self.subTest(expected=expected), patch.object(settings, "mock_mode", False), patch.object(settings, "serpapi_enabled", True), \
                 patch("app.agents.nodes.fetcher.fetch_lens_patents", new=AsyncMock(side_effect=lens if isinstance(lens, Exception) else None, return_value=lens)), \
                 patch("app.agents.nodes.fetcher.fetch_serpapi_patents", new=AsyncMock(side_effect=serp if isinstance(serp, Exception) else None, return_value=serp)):
                if expected == "failure":
                    with self.assertRaisesRegex(RuntimeError, "retrieval failed"):
                        await fetcher_node(state(), self.db)
                else:
                    result = await fetcher_node(state(), self.db)
                    self.assertEqual(result["retrieval_outcome"], expected)
                    self.assertEqual(any("failed" in w for w in result["coverage_warnings"]), isinstance(lens, Exception) or isinstance(serp, Exception) and lens == [])

    async def test_disabled_fallback_and_mixed_queries(self):
        with patch.object(settings, "mock_mode", False), patch.object(settings, "serpapi_enabled", False), \
             patch("app.agents.nodes.fetcher.fetch_lens_patents", new=AsyncMock(side_effect=RuntimeError("down"))), \
             patch("app.agents.nodes.fetcher.fetch_serpapi_patents", new=AsyncMock()) as serp:
            with self.assertRaisesRegex(RuntimeError, "retrieval failed"):
                await fetcher_node(state(), self.db)
            serp.assert_not_awaited()
        with patch.object(settings, "mock_mode", False), patch.object(settings, "serpapi_enabled", False), \
             patch("app.agents.nodes.fetcher.fetch_lens_patents", new=AsyncMock(side_effect=[[PATENT], RuntimeError("down")])):
            initial = state(); initial["search_queries"] = ["one", "two"]
            result = await fetcher_node(initial, self.db)
            self.assertEqual(result["retrieval_outcome"], "partial")
            self.assertEqual(result["raw_patents"], [PATENT])

    async def test_unusable_evidence_never_calls_conclusion_nodes(self):
        initial = state(); initial.update(raw_patents=[{"patent_id":" "}, {"patent_id":"US2"}, {"title":"No ID"}], deduped_patents=[], final_report="", white_space_analysis="")
        with patch("app.agents.graph.expander_node", new=AsyncMock(return_value={})), \
             patch("app.agents.graph.fetcher_node", new=AsyncMock(return_value={})), \
             patch("app.agents.graph.clusterer_node", new=AsyncMock(return_value={})) as cluster, \
             patch("app.agents.graph.whitespace_node", new=AsyncMock(return_value={})) as gaps, \
             patch("app.agents.graph.reporter_node", new=AsyncMock(return_value={})) as report:
            result = await build_graph(self.db).ainvoke(initial)
        self.assertEqual(result["deduped_patents"], [])
        self.assertEqual(result["retrieval_outcome"], "insufficient_evidence")
        for model in (cluster, gaps, report): model.assert_not_awaited()

    async def test_error_shaped_http_200_is_failure_not_empty(self):
        for provider, method in ((inspect.unwrap(fetch_lens_patents), "post"), (fetch_serpapi_patents, "get")):
            client = SimpleNamespace(**{method: AsyncMock(return_value=SimpleNamespace(raise_for_status=lambda:None, json=lambda:{"error":"synthetic failure"}))})
            with self.assertRaises(ValueError):
                await provider("q", client, "test-only")

    async def test_documented_serp_success_with_no_results_is_empty(self):
        client = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(raise_for_status=lambda:None, json=lambda:{"search_metadata":{"status":"Success"},"error":"No results returned"})))
        self.assertEqual(await fetch_serpapi_patents("q", client, "test-only"), [])

    async def test_retrieval_failure_persists_explicit_failure_without_finalizing(self):
        async def execute(name, params):
            if name == "fail_analysis":
                self.db.rows["searches"][0].update(status="failed",error_message=params['p_error'])
            return SimpleNamespace(data=True)
        self.db.rpc = Mock(side_effect=lambda name, params: SimpleNamespace(execute=lambda: execute(name,params)))
        for queries in (["q"], []):
            self.db.rows["searches"][0]["status"] = "processing"
            with patch.object(settings, "mock_mode", False), patch.object(settings, "serpapi_enabled", False), \
                 patch("app.agents.graph.expander_node", new=AsyncMock(return_value={"search_queries":queries})), \
                 patch("app.agents.nodes.fetcher.fetch_lens_patents", new=AsyncMock(side_effect=RuntimeError("outage"))) as lens, \
                 patch("app.agents.graph.clusterer_node", new=AsyncMock()) as cluster, \
                 patch("app.agents.graph.whitespace_node", new=AsyncMock()) as gaps, \
                 patch("app.agents.graph.reporter_node", new=AsyncMock()) as report:
                await run_claim(self.db, claim())
                self.assertEqual(self.db.rows["searches"][0]["status"], "failed")
                self.assertIn("all attempted providers failed" if queries else "no search queries", self.db.rows["searches"][0]["error_message"])
                for model in (cluster,gaps,report): model.assert_not_awaited()
                if not queries: lens.assert_not_awaited()
            self.assertFalse(any(c.args[0] in ("checkpoint_analysis","publish_analysis") for c in self.db.rpc.call_args_list))
