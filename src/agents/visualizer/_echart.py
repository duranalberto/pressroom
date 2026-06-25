"""ECharts specialized renderer — deterministic template fill (no LLM authoring).

Charts are produced by filling a visual template's ``render`` string with extracted data
and author params: code, not the model, writes the option object. This removes the whole
class of hand-authoring bugs the old freeform prompt fought (unbalanced parens, x/y length
mismatch, illegal multi-series), so the verbose defensive prompt is gone.

A chart slot must reference a visual template; there is no freeform echart fallback. A
slot the outline routes to echart without a template degrades loudly in the orchestrator.
"""

from __future__ import annotations

from typing import Any

from src.visuals.registry import VisualTemplate
from src.visuals.render import render_visual


def render_template(
    template: VisualTemplate,
    data: dict[str, Any],
    params: dict[str, Any],
) -> tuple[list[str], str]:
    """Render an echart visual template to ``(import_lines, body)``.

    Every ``echart`` fence needs a non-empty ``figure.description`` for accessibility.
    When the caller (outline or publication template) supplies none, default it to the
    chart ``title`` so the emitted fence is always valid without forcing a separate summary.
    An explicit ``description`` always wins; a chart with neither title nor description is a
    config error and surfaces loudly as an unresolved token in the shared renderer.
    """
    params = dict(params)
    if not params.get("description"):
        title = params.get("title") or template.param_default("title")
        if title:
            params["description"] = title
    return render_visual(template, data=data, params=params)
