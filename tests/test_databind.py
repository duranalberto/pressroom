"""Tests for src/agents/visualizer/_databind.py — directive parsing, resolution, tokens."""

from __future__ import annotations

import json

import pytest

from src.agents.visualizer._databind import (
    parse_data_spec,
    parse_inline_params,
    parse_slots,
    resolve_spec,
    substitute_data_tokens,
)
from src.json_query import clear_cache


# ── parse_slots: template + params ───────────────────────────────────────────

def test_parse_slots_extracts_template_and_params():
    outline = (
        '```artifact-slot\n'
        'id="price-3m" template="price-line" params="title=Prices; name=Close"\n'
        '```'
    )
    slots = parse_slots(outline)
    assert slots[0].id == "price-3m"
    assert slots[0].template == "price-line"
    assert slots[0].params == "title=Prices; name=Close"


def test_parse_slots_template_absent_is_empty():
    outline = '```artifact-slot\nid="x" context="a diagram"\n```'
    slots = parse_slots(outline)
    assert slots[0].template == ""
    assert slots[0].params == ""


# ── parse_inline_params ──────────────────────────────────────────────────────

def test_parse_inline_params_splits_pairs():
    assert parse_inline_params("title=Prices; name=Close") == {
        "title": "Prices", "name": "Close"}


def test_parse_inline_params_empty_is_empty_dict():
    assert parse_inline_params("") == {}


def test_parse_inline_params_ignores_blank_chunks_and_keyless():
    assert parse_inline_params("a=1; ; =nope; b=2") == {"a": "1", "b": "2"}


# ── parse_slots ────────────────────────────────────────────────────────────────

def test_parse_slots_extracts_id_context_data():
    outline = (
        'intro text\n\n'
        '```artifact-slot\n'
        'id="price-3m" data="prices=valuation_data.json:historical_data.price_history?last=63" '
        'context="line chart"\n'
        '```\n'
    )
    slots = parse_slots(outline)
    assert len(slots) == 1
    assert slots[0].id == "price-3m"
    assert slots[0].context == "line chart"
    assert "prices=" in slots[0].data


def test_parse_slots_data_absent_is_empty():
    outline = '```artifact-slot\nid="x" context="a diagram"\n```'
    slots = parse_slots(outline)
    assert slots[0].data == ""


def test_parse_slots_attribute_order_independent():
    outline = '```artifact-slot\ncontext="c" id="abc" data="n=f.json:p"\n```'
    slots = parse_slots(outline)
    assert slots[0].id == "abc"
    assert slots[0].data == "n=f.json:p"


def test_parse_slots_skips_block_without_id():
    outline = '```artifact-slot\ncontext="no id here"\n```'
    assert parse_slots(outline) == []


# ── parse_data_spec ────────────────────────────────────────────────────────────

def test_parse_single_path():
    [b] = parse_data_spec("prices=valuation_data.json:historical_data.price_history")
    assert b.name == "prices"
    assert b.file == "valuation_data.json"
    assert b.paths == ["historical_data.price_history"]
    assert b.is_list is False
    assert b.last is None


def test_parse_last_suffix():
    [b] = parse_data_spec("p=f.json:a.b?last=63")
    assert b.paths == ["a.b"]
    assert b.last == 63


def test_parse_multi_path_list():
    [b] = parse_data_spec("bear=f.json:[a.b, c.d, e.f]")
    assert b.is_list is True
    assert b.paths == ["a.b", "c.d", "e.f"]


def test_parse_projection_spec():
    [b] = parse_data_spec("s=f.json:summary.rows[scenario=Base].intrinsic_value")
    assert b.is_list is False
    assert b.paths == ["summary.rows"]
    assert b.extras["project"] == ("scenario", "Base", "intrinsic_value")


def test_parse_multiple_bindings():
    bs = parse_data_spec("a=f.json:x; b=f.json:y")
    assert [b.name for b in bs] == ["a", "b"]


def test_parse_malformed_binding_sets_error():
    [b] = parse_data_spec("garbage_without_equals")
    assert b.error


def test_parse_missing_file_path_sets_error():
    [b] = parse_data_spec("name=nocolon")
    assert b.error


# ── resolve_spec ───────────────────────────────────────────────────────────────

@pytest.fixture
def input_dir(tmp_path):
    data = {
        "valuations": {
            "DCF": {"scenarios": {"Base": {"iv": 7314.55}}},
            "PE": {"scenarios": {"Base": {"pv": 7630.4}}},
        },
        "historical_data": {"price_history": [float(i) for i in range(100)]},
        "summary": {"rows": [
            {"model_name": "DCF", "scenario": "Bear", "intrinsic_value": 1.0},
            {"model_name": "DCF", "scenario": "Base", "intrinsic_value": 2.0},
            {"model_name": "PE", "scenario": "Bear", "intrinsic_value": 3.0},
            {"model_name": "PE", "scenario": "Base", "intrinsic_value": 4.0},
        ]},
    }
    (tmp_path / "v.json").write_text(json.dumps(data), encoding="utf-8")
    clear_cache()
    return tmp_path


def test_resolve_single_array_adds_labels(input_dir):
    resolved, errors = resolve_spec("prices=v.json:historical_data.price_history?last=5", input_dir)
    assert errors == []
    assert resolved["prices"] == [95.0, 96.0, 97.0, 98.0, 99.0]
    assert resolved["prices_labels"] == ["D-4", "D-3", "D-2", "D-1", "D-0"]


def test_resolve_multi_path_assembles_array(input_dir):
    resolved, errors = resolve_spec(
        "base=v.json:[valuations.DCF.scenarios.Base.iv, valuations.PE.scenarios.Base.pv]",
        input_dir,
    )
    assert errors == []
    assert resolved["base"] == [7314.55, 7630.4]


def test_resolve_projection_selects_field_in_order(input_dir):
    resolved, errors = resolve_spec(
        "vals=v.json:summary.rows[scenario=Base].intrinsic_value; "
        "names=v.json:summary.rows[scenario=Base].model_name",
        input_dir,
    )
    assert errors == []
    assert resolved["vals"] == [2.0, 4.0]      # Base rows only, in list order
    assert resolved["names"] == ["DCF", "PE"]  # parallel projection stays aligned


def test_resolve_projection_no_match_degrades(input_dir):
    resolved, errors = resolve_spec(
        "v=v.json:summary.rows[scenario=Nope].intrinsic_value", input_dir)
    assert "v" not in resolved
    assert any("matched no rows" in e for e in errors)


def test_resolve_projection_non_list_source_degrades(input_dir):
    resolved, errors = resolve_spec(
        "v=v.json:valuations[scenario=Base].iv", input_dir)
    assert "v" not in resolved
    assert any("not a list" in e for e in errors)


def test_resolve_bad_path_records_error_and_drops_binding(input_dir):
    resolved, errors = resolve_spec("x=v.json:nope.nope", input_dir)
    assert "x" not in resolved
    assert len(errors) == 1
    assert "failed" in errors[0]


def test_resolve_partial_failure_keeps_good_bindings(input_dir):
    resolved, errors = resolve_spec(
        "good=v.json:valuations.DCF.scenarios.Base.iv; bad=v.json:zzz", input_dir
    )
    assert resolved["good"] == 7314.55
    assert "bad" not in resolved
    assert len(errors) == 1


# ── substitute_data_tokens ─────────────────────────────────────────────────────

def test_substitute_replaces_tokens_with_json():
    body = "y: @@data:prices@@"
    out, missing = substitute_data_tokens(body, {"prices": [1, 2, 3]})
    assert out == "y: [1, 2, 3]"
    assert missing == []


def test_substitute_scalar_token():
    out, _ = substitute_data_tokens("v = @@data:x@@", {"x": 42.5})
    assert out == "v = 42.5"


def test_substitute_strips_and_reports_unresolved():
    out, missing = substitute_data_tokens("a @@data:ghost@@ b", {})
    assert "@@data:ghost@@" not in out
    assert missing == ["ghost"]


def test_substitute_no_tokens_unchanged():
    out, missing = substitute_data_tokens("plain body", {"x": 1})
    assert out == "plain body"
    assert missing == []
