from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from src.agents import (
    humanizer,
    loader,
    metadata,
    outline,
    publisher,
    reviewer,
    visualizer,
    writer,
)
from src.state import PublicationState


def _route_review(state: PublicationState) -> str:
    """Decide whether the writer revises or the pipeline advances to the humanizer.

    Returns ``"humanizer"`` when the reviewer approved the draft or when the
    revision cap is exceeded (force-advance). Returns ``"writer"`` otherwise.
    The cap check uses ``>`` so the writer gets a revision on every round up to
    ``max_iterations``; round ``max_iterations + 1`` is the force-advance gate.
    """
    if state.get("review_approved", False):
        return "humanizer"
    # > (not >=) so the writer gets a revision on every round up to max_iterations.
    # With max_iterations=3 the writer can revise after rounds 1, 2, and 3;
    # round 4 is the force-advance gate.
    if state.get("review_iteration", 0) > state.get("max_iterations", 3):
        return "humanizer"
    return "writer"


def build_graph():
    """Compile and return the full LangGraph publication pipeline.

    Returns:
        A compiled ``StateGraph`` with an in-memory checkpoint saver. The graph
        runs from ``loader`` → ``interview`` → ``outline_designer`` → ``visualizer``
        → ``writer`` ⇄ ``reviewer`` → ``humanizer`` → ``metadata`` → ``publisher``.
        The writer/reviewer edge is conditional: the reviewer's approval state and
        ``max_iterations`` determine whether to loop back or advance.
    """
    builder = StateGraph(PublicationState)

    builder.add_node("loader", loader.run)
    builder.add_node("interview", outline.run_interview)
    builder.add_node("outline_designer", outline.run)
    builder.add_node("visualizer", visualizer.run)
    builder.add_node("writer", writer.run)
    builder.add_node("reviewer", reviewer.run)
    builder.add_node("humanizer", humanizer.run)
    builder.add_node("metadata", metadata.run)
    builder.add_node("publisher", publisher.run)

    builder.add_edge(START, "loader")
    builder.add_edge("loader", "interview")
    builder.add_edge("interview", "outline_designer")
    builder.add_edge("outline_designer", "visualizer")
    builder.add_edge("visualizer", "writer")
    builder.add_edge("writer", "reviewer")
    builder.add_conditional_edges("reviewer", _route_review, {
        "writer": "writer",
        "humanizer": "humanizer",
    })
    builder.add_edge("humanizer", "metadata")
    builder.add_edge("metadata", "publisher")
    builder.add_edge("publisher", END)

    return builder.compile(checkpointer=MemorySaver())
