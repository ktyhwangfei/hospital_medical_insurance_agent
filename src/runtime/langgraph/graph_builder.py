from collections.abc import Callable

from langgraph.graph import END, START, StateGraph

from src.runtime.langgraph.states import BaseAgentState


def build_agent_graph(
    nodes: dict[str, Callable],
    edges: list[tuple[str, str]],
    conditional_edges: list[tuple[str, Callable, dict[str, str]]] | None = None,
    checkpointer=None,
) -> StateGraph:
    builder = StateGraph(BaseAgentState)
    for name, fn in nodes.items():
        builder.add_node(name, fn)
    for source, target in edges:
        resolved_source = START if source == "START" else source
        resolved_target = END if target == "END" else target
        builder.add_edge(resolved_source, resolved_target)
    if conditional_edges:
        for source, condition_fn, mapping in conditional_edges:
            builder.add_conditional_edges(source, condition_fn, mapping)
    return builder.compile(checkpointer=checkpointer)
