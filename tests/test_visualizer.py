"""Tests for src/agents/visualizer/ — _split_imports, _validate_artifact, _classify_artifact."""

from __future__ import annotations

from src.agents import visualizer
from src.agents.visualizer import (
    _classify_artifact,
    _prepare,
    _split_imports,
    _validate_artifact,
)
from src.json_query import clear_cache
from src.visuals import registry


# ── _prepare — data token substitution into a render ──────────────────────────

def test_prepare_substitutes_data_tokens():
    raw = '```echart\n{"type": "bar", "data": {"y": @@data:p@@}}\n```'
    imports, body = _prepare("chart", raw, {"p": [1, 2, 3]})
    assert imports == []
    assert "@@data:p@@" not in body
    assert "[1, 2, 3]" in body


def test_prepare_without_resolved_leaves_body():
    raw = "```daisyui\n{\"component\": \"callout\"}\n```"
    _, body = _prepare("id", raw, {})
    assert body == '```daisyui\n{"component": "callout"}\n```'


# ── run — templated orchestration ─────────────────────────────────────────────

def _templated_slot(artifact_id: str, template_id: str) -> str:
    return f'```artifact-slot\nid="{artifact_id}" template="{template_id}"\n```'


def test_run_renders_templated_visual_from_config(tmp_path, monkeypatch):
    (tmp_path / "v.json").write_text('{"p": [10, 20, 30]}', encoding="utf-8")
    clear_cache()
    registry.clear_cache()
    monkeypatch.setattr(visualizer, "build_model", lambda: object())

    state = {
        "outline": _templated_slot("price-chart", "price-line"),
        "input_dir": str(tmp_path),
        "template_data": {"visuals": [{
            "id": "price-chart", "template": "price-line",
            "params": {"title": "Prices", "name": "Close"},
            "bind": {"series": "v.json:p"},
        }]},
    }
    result = visualizer.run(state)

    art = result["artifacts"][0]
    assert art["id"] == "price-chart"
    assert "@@" not in art["content"]            # all tokens substituted
    assert "[10, 20, 30]" in art["content"]      # exact values injected by code, no LLM
    assert '"name": "Close"' in art["content"]   # fence JSON, no imports/JSX
    assert art["import_lines"] == []
    assert art["content"].startswith("```echart")
    assert "errors" not in result


def test_run_injects_missing_configured_visual_into_outline(tmp_path, monkeypatch):
    (tmp_path / "v.json").write_text('{"p": [1, 2, 3]}', encoding="utf-8")
    clear_cache()
    registry.clear_cache()
    monkeypatch.setattr(visualizer, "build_model", lambda: object())

    state = {
        "outline": "## Market Snapshot\n\nSome prose about the market.",
        "input_dir": str(tmp_path),
        "template_data": {
            "visuals": [{
                "id": "price-chart", "template": "price-line", "section": "market",
                "params": {"title": "Prices"}, "bind": {"series": "v.json:p"},
            }],
            "agents": {"outline": {"structure": [{"id": "market", "title": "Market Snapshot"}]}},
        },
    }
    result = visualizer.run(state)

    # The outline the writer copies from now carries the fence, placed in its section.
    assert 'id="price-chart"' in result["outline"]
    assert result["outline"].index("price-chart") > result["outline"].index("Market Snapshot")
    assert result["artifacts"][0]["id"] == "price-chart"


def test_run_skips_templated_visual_on_bad_bind(tmp_path, monkeypatch):
    (tmp_path / "v.json").write_text('{"p": [1]}', encoding="utf-8")
    clear_cache()
    registry.clear_cache()
    monkeypatch.setattr(visualizer, "build_model", lambda: object())

    state = {
        "outline": _templated_slot("chart", "price-line"),
        "input_dir": str(tmp_path),
        "template_data": {"visuals": [{
            "id": "chart", "template": "price-line",
            "params": {"title": "P"}, "bind": {"series": "v.json:nope.missing"},
        }]},
    }
    result = visualizer.run(state)

    assert result["artifacts"] == []           # never ship a chart with missing data
    assert any("chart" in e for e in result["errors"])


def test_run_unknown_template_degrades(tmp_path, monkeypatch):
    clear_cache()
    registry.clear_cache()
    monkeypatch.setattr(visualizer, "build_model", lambda: object())

    state = {
        "outline": _templated_slot("x", "no-such-template"),
        "input_dir": str(tmp_path),
        "template_data": {},
    }
    result = visualizer.run(state)

    assert result["artifacts"] == []
    assert any("unknown visual template" in e for e in result["errors"])


def test_run_echart_without_template_degrades(tmp_path, monkeypatch):
    """A chart slot with no template is not hand-authored — it degrades."""
    clear_cache()
    registry.clear_cache()
    monkeypatch.setattr(visualizer, "build_model", lambda: object())

    outline = '```artifact-slot\nid="x" context="EChart barChartOption of revenue"\n```'
    result = visualizer.run({"outline": outline, "input_dir": str(tmp_path), "template_data": {}})

    assert result["artifacts"] == []
    assert any("template" in e for e in result["errors"])


# ── _split_imports ────────────────────────────────────────────────────────────

def test_split_imports_single_import():
    raw = "import Foo from './Foo'\n\n<Foo />"
    imports, body = _split_imports(raw)
    assert imports == ["import Foo from './Foo'"]
    assert body == "<Foo />"


def test_split_imports_multiple_imports():
    raw = "import A from 'a'\nimport B from 'b'\n\n<A /><B />"
    imports, body = _split_imports(raw)
    assert imports == ["import A from 'a'", "import B from 'b'"]
    assert body == "<A /><B />"


def test_split_imports_blank_lines_between_imports():
    raw = "import A from 'a'\n\nimport B from 'b'\n\n<content />"
    imports, body = _split_imports(raw)
    assert "import A from 'a'" in imports
    assert "import B from 'b'" in imports
    assert body == "<content />"


def test_split_imports_no_imports_mermaid():
    raw = "```mermaid\ngraph LR\nA --> B\n```"
    imports, body = _split_imports(raw)
    assert imports == []
    assert "mermaid" in body
    assert "graph LR" in body


def test_split_imports_fence_content_not_treated_as_import():
    # A compliant artifact is a fence — it starts with ``` not "import", so nothing is
    # extracted as an import even if the JSON body mentions the word.
    raw = '```daisyui\n{"component": "callout", "content": "import something"}\n```'
    imports, body = _split_imports(raw)
    assert imports == []
    assert body.startswith("```daisyui")


def test_split_imports_trailing_whitespace_stripped():
    raw = "import Foo from 'foo'   \n\n<Foo />"
    imports, body = _split_imports(raw)
    assert imports == ["import Foo from 'foo'"]


def test_split_imports_body_only_no_imports():
    raw = '```echart\n{"type": "bar"}\n```'
    imports, body = _split_imports(raw)
    assert imports == []
    assert "echart" in body


def test_split_imports_empty_string():
    imports, body = _split_imports("")
    assert imports == []
    assert body == ""


# ── _validate_artifact — fence contract ───────────────────────────────────────

_GOOD_ECHART = (
    "```echart\n"
    '{"type": "bar", "figure": {"title": "T", "description": "A bar chart."}, '
    '"data": {"x": ["a", "b"], "y": [1, 2]}}\n'
    "```"
)
_GOOD_DAISYUI = (
    "```daisyui\n"
    '{"component": "callout", "variant": "note", "content": "Hi"}\n'
    "```"
)


def test_validate_clean_echart_fence_no_issues():
    assert _validate_artifact("a", _GOOD_ECHART, []) == []


def test_validate_clean_daisyui_fence_no_issues():
    assert _validate_artifact("a", _GOOD_DAISYUI, []) == []


def test_validate_mermaid_no_issues():
    content = "```mermaid\nflowchart TD\nA --> B\n```"
    assert _validate_artifact("x", content, []) == []


def test_validate_echart_missing_description_flagged():
    content = ('```echart\n{"type": "bar", "figure": {"title": "T"}, '
               '"data": {"x": ["a"], "y": [1]}}\n```')
    issues = _validate_artifact("x", content, [])
    assert any("description" in i for i in issues)


def test_validate_echart_missing_type_flagged():
    content = '```echart\n{"figure": {"description": "d"}}\n```'
    issues = _validate_artifact("x", content, [])
    assert any('"type"' in i for i in issues)


def test_validate_echart_xy_length_mismatch_flagged():
    """The production bug: 1 x-label but 3 y-values must be flagged, now in fence form."""
    content = ('```echart\n{"type": "bar", "figure": {"description": "d"}, '
               '"data": {"x": ["Metric"], "y": [149.91, 276.80, 146.32]}}\n```')
    issues = _validate_artifact("crm", content, [])
    assert any("x has 1 label" in i and "y has 3 value" in i for i in issues)


def test_validate_echart_xy_matching_lengths_ok():
    content = ('```echart\n{"type": "bar", "figure": {"description": "d"}, '
               '"data": {"x": ["a", "b", "c"], "y": [1, 2, 3]}}\n```')
    assert _validate_artifact("x", content, []) == []


def test_validate_echart_option_type_has_no_xy_check():
    # A raw `option` fence (grouped/multi-series) has no top-level data.x/data.y to compare.
    content = ('```echart\n{"type": "option", "figure": {"description": "d"}, '
               '"option": {"series": [{"type": "bar", "data": [1, 2]}]}}\n```')
    assert _validate_artifact("x", content, []) == []


def test_validate_invalid_json_fence_flagged():
    content = '```echart\n{"type": "bar", "figure": {"description": "d",}}\n```'  # trailing comma
    issues = _validate_artifact("x", content, [])
    assert any("not valid JSON" in i for i in issues)


def test_validate_daisyui_missing_component_flagged():
    content = '```daisyui\n{"variant": "note", "content": "Hi"}\n```'
    issues = _validate_artifact("x", content, [])
    assert any("component" in i for i in issues)


def test_validate_stray_jsx_component_flagged():
    # A leftover JSX component (the model ignored the fence contract) is a hard error.
    content = '<Callout variant="note">text</Callout>'
    issues = _validate_artifact("x", content, [])
    assert any("Callout" in i and "fenced" in i for i in issues)


def test_validate_import_line_in_body_flagged():
    content = ('import Callout from "@x";\n\n'
               '```daisyui\n{"component": "callout", "content": "Hi"}\n```')
    issues = _validate_artifact("x", content, [])
    assert any("import" in i.lower() for i in issues)


def test_validate_split_import_lines_flagged():
    issues = _validate_artifact("x", _GOOD_DAISYUI, ['import Callout from "@x";'])
    assert any("import" in i.lower() for i in issues)


def test_validate_html_comment_flagged():
    content = _GOOD_DAISYUI + "\n<!-- note -->"
    issues = _validate_artifact("x", content, [])
    assert any("<!--" in i for i in issues)


def test_validate_angle_bracket_inside_fence_not_flagged():
    # A `<` inside the fence JSON (e.g. in prose content) must not be read as a JSX tag.
    content = '```daisyui\n{"component": "callout", "content": "See <Thing> below"}\n```'
    assert _validate_artifact("x", content, []) == []


# ── _classify_artifact ────────────────────────────────────────────────────────

def test_classify_mermaid_by_flowchart_keyword():
    assert _classify_artifact("Mermaid flowchart TD showing the pipeline stages") == "mermaid"


def test_classify_mermaid_by_sequence_diagram():
    assert _classify_artifact("sequenceDiagram showing API auth flow") == "mermaid"


def test_classify_mermaid_by_state_diagram():
    assert _classify_artifact("stateDiagram-v2 for job lifecycle states") == "mermaid"


def test_classify_mermaid_by_graph_keyword():
    assert _classify_artifact("graph TD with subgraphs for the architecture") == "mermaid"


def test_classify_mermaid_by_mindmap():
    assert _classify_artifact("mindmap showing the content taxonomy") == "mermaid"


def test_classify_mermaid_by_gantt():
    assert _classify_artifact("gantt chart for the release schedule") == "mermaid"


def test_classify_echart_by_echart_keyword():
    assert _classify_artifact("EChart barChartOption showing monthly revenue") == "echart"


def test_classify_echart_by_builder_name():
    assert _classify_artifact("lineChartOption showing growth over 12 months") == "echart"


def test_classify_echart_pie_chart():
    assert _classify_artifact("pieChartOption donut chart showing allocation") == "echart"


def test_classify_echart_candlestick():
    assert _classify_artifact("candlestickWithVolumeOption for BTC/USD 30-day") == "echart"


def test_classify_echart_case_insensitive():
    assert _classify_artifact("ECHARTS LINECHARTOPTIONP showing data") == "echart"


def test_classify_ui_callout_default():
    assert _classify_artifact("Callout warning variant before deploying") == "ui"


def test_classify_ui_steps_default():
    assert _classify_artifact("Steps component showing 4 release stages") == "ui"


def test_classify_ui_list_default():
    assert _classify_artifact("List component showing release artifacts") == "ui"


def test_classify_ui_mockup_browser():
    assert _classify_artifact("MockupBrowser showing the hosted report at /reports/") == "ui"


def test_classify_ui_unknown_falls_back():
    assert _classify_artifact("some ambiguous description with no known keywords") == "ui"


def test_classify_mermaid_takes_priority_over_echart():
    # If somehow both keywords appear, mermaid wins (checked first)
    assert _classify_artifact("mermaid flowchart with echart label") == "mermaid"


def test_classify_case_insensitive_mermaid():
    assert _classify_artifact("MERMAID FLOWCHART TD for the deployment process") == "mermaid"
