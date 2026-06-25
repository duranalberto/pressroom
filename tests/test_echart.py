"""Tests for src/agents/visualizer/_echart.py — deterministic templated rendering.

The freeform LLM-authoring path (and its defensive prompt) was removed: charts are
template-only now. This covers the echart specialized renderer's templated entry point.
"""

from __future__ import annotations

import pytest

from src.agents.visualizer import _echart
from src.visuals import registry
from src.visuals.render import VisualRenderError


@pytest.fixture(autouse=True)
def _clear_cache():
    registry.clear_cache()
    yield
    registry.clear_cache()


def test_render_template_fills_line_chart_deterministically():
    vt = registry.get("price-line")
    imports, body = _echart.render_template(
        vt,
        {"series": [149.9, 150.2, 151.0]},
        {"title": "CRM closing price", "name": "Close"},
    )
    assert imports == []  # fences need no imports
    assert body.startswith("```echart")
    assert '"y": [149.9, 150.2, 151.0]' in body
    assert '"name": "Close"' in body
    assert "@@" not in body  # no leftover tokens


def test_render_template_is_deterministic():
    vt = registry.get("category-bar")
    data = {"values": [1.0, 2.0, 3.0]}
    params = {"title": "Revenue", "categories": ["A", "B", "C"]}
    a = _echart.render_template(vt, data, params)
    b = _echart.render_template(vt, data, params)
    assert a == b


def test_render_template_grouped_bar_three_series():
    vt = registry.get("grouped-bar")
    _, body = _echart.render_template(
        vt,
        {"series_a": [1, 2], "series_b": [3, 4], "series_c": [5, 6],
         "categories": ["DCF", "PE"]},
        {"title": "Valuations", "name_a": "Bear", "name_b": "Base", "name_c": "Bull"},
    )
    assert body.count('"type": "bar"') == 3
    assert "[1, 2]" in body and "[5, 6]" in body


def test_render_template_defaults_description_to_title():
    vt = registry.get("price-line")
    _, body = _echart.render_template(
        vt, {"series": [1, 2, 3]}, {"title": "Closing price"}
    )
    # figure.description is required by the echart fence; it defaults to the title.
    assert '"description": "Closing price"' in body


def test_render_template_explicit_description_wins():
    vt = registry.get("price-line")
    _, body = _echart.render_template(
        vt, {"series": [1, 2, 3]},
        {"title": "Closing price", "description": "Three-day close."},
    )
    assert '"description": "Three-day close."' in body


def test_render_template_missing_required_param_raises():
    vt = registry.get("price-line")  # title is required
    with pytest.raises(VisualRenderError):
        _echart.render_template(vt, {"series": [1, 2]}, {})
