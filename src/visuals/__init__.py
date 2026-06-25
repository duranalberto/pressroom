"""Visual templates — declarative, deterministic recipes for specific visuals.

A *visual template* (``templates/visuals/<id>.yaml``) captures everything needed to
produce one kind of visual: its ``kind`` (which specialized renderer builds it), its
``type`` (builder or component), the params an author supplies, the data it must extract,
and a ``render`` string whose tokens are substituted with concrete literals.

The point: code, not an LLM, writes the option object / JSX. The model only picks a
template and supplies params + an extraction intent, so the bug-prone authoring prompts
disappear.

    from src.visuals import registry, render

    vt = registry.get("price-line")
    imports, body = render.render_visual(vt, data={"series": [1, 2, 3]},
                                         params={"title": "Demo"})
"""

from __future__ import annotations

from . import registry, render  # noqa: F401  (re-export for convenience)
from .registry import VisualTemplate  # noqa: F401
