from __future__ import annotations

from typing import Any, Optional


def get_workflow_mermaid(*, compiled_graph: Any) -> str:
    """
    Return a Mermaid diagram (text) for the compiled graph.

    LangGraph visualization APIs can differ across versions; this function uses
    best-effort feature detection.
    """
    # Most common: compiled_graph.get_graph().draw_mermaid()
    try:
        g = compiled_graph.get_graph()
        if hasattr(g, "draw_mermaid"):
            return g.draw_mermaid()  # type: ignore[no-any-return]
    except Exception:
        pass

    # Alternate: compiled_graph.get_graph().to_mermaid()
    try:
        g = compiled_graph.get_graph()
        if hasattr(g, "to_mermaid"):
            return g.to_mermaid()  # type: ignore[no-any-return]
    except Exception:
        pass

    return "graph TD\n  A[Visualization not available in this LangGraph version]"

