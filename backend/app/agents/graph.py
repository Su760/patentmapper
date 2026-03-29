"""
LangGraph DAG — Patent Landscape Mapper
Strict 6-node pipeline: expander → fetcher → deduplicator → clusterer → whitespace → reporter
"""
import logging
from functools import partial
from typing import Any, Dict

from langgraph.graph import END, START, StateGraph
from supabase import AsyncClient

from app.agents.nodes.clusterer import clusterer_node
from app.agents.nodes.deduplicator import deduplicator_node
from app.agents.nodes.expander import expander_node
from app.agents.nodes.fetcher import fetcher_node
from app.agents.nodes.reporter import reporter_node
from app.agents.nodes.whitespace import whitespace_node
from app.agents.state import LandscapeState

logger = logging.getLogger(__name__)


def build_graph(supabase: AsyncClient) -> Any:
    """
    Build and compile the LangGraph DAG.
    Supabase client is injected so nodes can update current_step.
    """
    graph = StateGraph(LandscapeState)

    # Wrap each node to inject the supabase client via partial
    graph.add_node("expander", partial(expander_node, supabase=supabase))
    graph.add_node("fetcher", partial(fetcher_node, supabase=supabase))
    graph.add_node("deduplicator", partial(deduplicator_node, supabase=supabase))
    graph.add_node("clusterer", partial(clusterer_node, supabase=supabase))
    graph.add_node("whitespace", partial(whitespace_node, supabase=supabase))
    graph.add_node("reporter", partial(reporter_node, supabase=supabase))

    # Strict DAG edges
    graph.add_edge(START, "expander")
    graph.add_edge("expander", "fetcher")
    graph.add_edge("fetcher", "deduplicator")
    graph.add_edge("deduplicator", "clusterer")
    graph.add_edge("clusterer", "whitespace")
    graph.add_edge("whitespace", "reporter")
    graph.add_edge("reporter", END)

    return graph.compile()
