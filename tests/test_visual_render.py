"""Tests for src/visuals/render.py — deterministic token substitution.

Also doubles as a lint over the four shipped templates: each must render from
representative data to a snippet with balanced JSX and no leftover tokens.
"""

from __future__ import annotations

import pytest

from src.visuals import registry, render
from src.visuals.render import VisualRenderError, render_visual


@pytest.fixture(autouse=True)
def _clear_cache():
    registry.clear_cache()
    yield
    registry.clear_cache()


# ── token substitution semantics ────────────────────────────────────────────

def _vt(**over):
    """Build a one-off VisualTemplate for focused substitution tests."""
    base = dict(
        id="t", kind="echart", type="raw", summary="",
        params={}, extract={}, labels={}, imports=["import X from 'x';"],
        render="", raw={},
    )
    base.update(over)
    return registry.VisualTemplate(**base)


def test_data_token_becomes_json_array():
    vt = _vt(extract={"series": {}}, render="y: @@data:series@@")
    _, body = render_visual(vt, data={"series": [1, 2, 3]})
    assert body == "y: [1, 2, 3]"


def test_param_string_is_quoted_when_placed_bare():
    vt = _vt(params={"title": {"required": True}}, render="title={@@param:title@@}")
    _, body = render_visual(vt, data={}, params={"title": "Buy CRM"})
    assert body == 'title={"Buy CRM"}'


def test_param_bool_becomes_js_literal():
    vt = _vt(params={"h": {"default": False}}, render="horizontal: @@param:h@@")
    _, body = render_visual(vt, data={})
    assert body == "horizontal: false"


def test_default_param_used_when_not_supplied():
    vt = _vt(params={"name": {"default": "Value"}}, render="name: @@param:name@@")
    _, body = render_visual(vt, data={})
    assert body == 'name: "Value"'


def test_sequential_labels_match_series_length():
    vt = _vt(
        extract={"series": {}},
        labels={"x": {"from": "sequential", "of": "series"}},
        render="x: @@label:x@@",
    )
    _, body = render_visual(vt, data={"series": [10, 20, 30]})
    assert body == 'x: ["D-2", "D-1", "D-0"]'


def test_window_labels_only_endpoints():
    vt = _vt(
        extract={"series": {}},
        labels={"x": {"from": "window", "of": "series", "start": "Oldest", "end": "Latest"}},
        render="x: @@label:x@@",
    )
    _, body = render_visual(vt, data={"series": [1, 2, 3, 4]})
    assert body == 'x: ["Oldest", "", "", "Latest"]'


def test_window_labels_single_point():
    vt = _vt(
        extract={"series": {}},
        labels={"x": {"from": "window", "of": "series", "start": "A", "end": "B"}},
        render="x: @@label:x@@",
    )
    _, body = render_visual(vt, data={"series": [9]})
    assert body == 'x: ["B"]'


def test_param_labels_pass_through():
    vt = _vt(
        params={"cats": {"required": True}},
        labels={"x": {"from": "param", "name": "cats"}},
        render="x: @@label:x@@",
    )
    _, body = render_visual(vt, data={}, params={"cats": ["A", "B"]})
    assert body == 'x: ["A", "B"]'


def test_text_token_is_escaped_not_quoted():
    vt = _vt(extract={"r": {}}, render="Verdict: **@@text:r@@**")
    _, body = render_visual(vt, data={"r": "Buy"})
    assert body == "Verdict: **Buy**"


def test_text_token_escapes_braces_and_lt():
    vt = _vt(extract={"r": {}}, render="@@text:r@@")
    _, body = render_visual(vt, data={"r": "a{b}<c"})
    assert body == "a&#123;b&#125;&lt;c"


def test_str_token_json_escapes_without_surrounding_quotes():
    # @@str@@ drops a value INSIDE an existing JSON string (e.g. a fence's "content"): it
    # escapes JSON-special characters but adds no surrounding quotes, so the object parses.
    import json as _json

    vt = _vt(extract={"r": {}}, render='"content": "V: @@str:r@@"')
    _, body = render_visual(vt, data={"r": 'a "q" b'})
    assert body == '"content": "V: a \\"q\\" b"'
    assert _json.loads("{" + body + "}")["content"] == 'V: a "q" b'


# ── derive: a param computed from a data slot via a value map ────────────────

def _derive_vt():
    return _vt(
        extract={"rec": {}},
        params={"variant": {"default": "note"}},
        derive={"variant": {"from": "rec",
                            "map": {"Buy": "information", "Sell": "caution"},
                            "default": "note"}},
        render="@@param:variant@@",
    )


def test_derive_maps_data_value_to_param():
    _, body = render_visual(_derive_vt(), data={"rec": "Sell"})
    assert body == '"caution"'


def test_derive_falls_back_to_default_when_unmapped():
    _, body = render_visual(_derive_vt(), data={"rec": "Hold"})
    assert body == '"note"'  # Hold is not in the map -> default


def test_derive_does_not_override_explicit_caller_param():
    _, body = render_visual(_derive_vt(), data={"rec": "Sell"}, params={"variant": "error"})
    assert body == '"error"'  # an explicit caller value always wins over a derived one


def test_verdict_callout_variant_follows_recommendation():
    vt = registry.get("verdict-callout")
    for rec, expected in (("Buy", "information"), ("Hold", "note"), ("Sell", "caution")):
        _, body = render_visual(vt, data={"recommendation": rec, "confidence": "High"})
        assert f'"variant": "{expected}"' in body, f"{rec} -> {body}"


# ── failure modes (degrade, never ship a hole) ──────────────────────────────

def test_missing_required_param_raises():
    vt = _vt(params={"title": {"required": True}}, render="title={@@param:title@@}")
    with pytest.raises(VisualRenderError, match="required param"):
        render_visual(vt, data={})


def test_unresolved_data_token_raises():
    vt = _vt(extract={"series": {}}, render="y: @@data:series@@")
    with pytest.raises(VisualRenderError, match="unresolved"):
        render_visual(vt, data={})  # 'series' never supplied


def test_returns_template_imports():
    vt = _vt(render="x", imports=["import A from 'a';", "import B from 'b';"])
    imports, _ = render_visual(vt, data={})
    assert imports == ["import A from 'a';", "import B from 'b';"]


# ── lint: every shipped template renders cleanly from representative data ────

_SAMPLES = {
    "price-line": (
        {"series": [149.9, 150.2, 151.0]},
        {"title": "CRM closing price, last 3 months",
         "description": "Line chart of CRM's closing price over three days."},
    ),
    "category-bar": (
        {"values": [1.0, 2.0, 3.0, 4.0]},
        {"title": "Annual revenue", "categories": ["FY-3", "FY-2", "FY-1", "TTM"],
         "description": "Bar chart of annual revenue across four periods."},
    ),
    "grouped-bar": (
        {"series_a": [1, 2], "series_b": [3, 4], "series_c": [5, 6],
         "categories": ["DCF", "PE"]},
        {"title": "Valuations", "description": "Grouped bars for three valuation scenarios."},
    ),
    "verdict-callout": (
        {"recommendation": "Buy", "confidence": "High"},
        {},
    ),
}


@pytest.mark.parametrize("tid", sorted(_SAMPLES))
def test_shipped_template_renders_without_leftover_tokens(tid):
    vt = registry.get(tid)
    data, params = _SAMPLES[tid]
    imports, body = render_visual(vt, data=data, params=params)
    assert imports == [], f"{tid} fences declare no imports"
    assert "@@" not in body, f"{tid} left an unresolved token: {body}"
    # Balanced JSON braces.
    assert body.count("{") == body.count("}"), f"{tid} brace imbalance:\n{body}"
    # Compliant output is a fenced echart or daisyui block, not JSX + imports.
    assert body.startswith("```echart") or body.startswith("```daisyui"), body


def test_grouped_bar_has_overlap_safe_layout():
    # Regression: legend must be pinned top and the grid must reserve label room so the
    # series legend never collides with the category labels (the production overlap bug).
    vt = registry.get("grouped-bar")
    _, body = render_visual(
        vt,
        data={"series_a": [1], "series_b": [2], "series_c": [3], "categories": ["X"]},
        params={"title": "T", "description": "d"},
    )
    assert '"containLabel": true' in body
    assert '"top": 0' in body                        # legend pinned to the top
    assert '"yAxis": { "type": "category"' in body   # horizontal: categories on the left


def test_grouped_bar_emits_three_series():
    vt = registry.get("grouped-bar")
    _, body = render_visual(
        vt,
        data={"series_a": [1], "series_b": [2], "series_c": [3], "categories": ["X"]},
        params={"title": "T", "name_a": "Bear", "name_b": "Base", "name_c": "Bull",
                "description": "d"},
    )
    assert body.count('"type": "bar"') == 3
    assert '"Bear"' in body and '"Base"' in body and '"Bull"' in body
