"""Tests for src/agents/visualizer/_extractor.py.

Static resolution runs against a stable committed fixture dataset (no LLM). We use the
checked-in ``tests/fixtures/reports/CRM`` snapshot rather than the mutable ``input/`` dir so
the value assertions are reproducible regardless of which petition is loaded in ``input/``.
Intent resolution is tested with a fake LLM so the deterministic plumbing is covered
without Ollama.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.agents.visualizer import _extractor
from src.json_query import clear_cache as clear_query_cache
from src.visuals import registry

# A stable, committed dataset (the CRM reference report) — never changes between runs.
CRM_DATA = "tests/fixtures/reports/CRM"


@pytest.fixture(autouse=True)
def _clear_cache():
    registry.clear_cache()
    clear_query_cache()
    yield
    registry.clear_cache()
    clear_query_cache()


class _FakeLLM:
    """Returns a canned spec line; records the prompt it was asked to resolve."""

    def __init__(self, reply: str):
        self.reply = reply
        self.last_prompt = None

    def model_copy(self, update=None):
        return self

    def invoke(self, messages):
        self.last_prompt = messages[-1].content
        return SimpleNamespace(content=self.reply)


# ── looks_like_spec ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("expr,expected", [
    ("valuation_data.json:historical_data.price_history?last=63", True),
    ("valuation_data.json:[a.b, c.d]", True),
    ("analysis.json:recommendation", True),
    ("report.md:something", True),
    ("last 3 months of daily close prices", False),
    ("the base intrinsic values across six models", False),
])
def test_looks_like_spec(expr, expected):
    assert _extractor.looks_like_spec(expr) is expected


# ── static resolution against real input files ──────────────────────────────

def test_static_single_path_resolves():
    vt = registry.get("price-line")
    data, errors = _extractor.resolve(
        vt,
        {"series": "valuation_data.json:historical_data.price_history?last=63"},
        CRM_DATA,
    )
    assert errors == []
    assert len(data["series"]) == 63
    assert all(isinstance(x, (int, float)) for x in data["series"])


def test_static_multipath_assembles_array():
    vt = registry.get("grouped-bar")
    base = ("valuation_data.json:[valuations.DCF.scenarios.Base.intrinsic_value_per_share, "
            "valuations.PE.scenarios.Base.present_value, "
            "valuations.ROE.scenarios.Base.intrinsic_value, "
            "valuations.EVEBITDA.scenarios.Base.intrinsic_value_per_share, "
            "valuations.PS.scenarios.Base.intrinsic_value_per_share, "
            "valuations.NAV.scenarios.Base.intrinsic_value_per_share]")
    data, errors = _extractor.resolve(
        vt,
        {"series_a": base, "series_b": base, "series_c": base,
         "categories": "valuation_data.json:summary.models_run"},
        CRM_DATA,
    )
    assert errors == []
    assert len(data["series_a"]) == 6
    assert data["series_a"][0] == pytest.approx(7146.1077)
    assert data["series_a"][-1] == pytest.approx(-3.7888)
    assert data["categories"] == ["DCF", "PE", "ROE", "EVEBITDA", "PS", "NAV"]


def test_missing_binding_is_recorded_not_raised():
    vt = registry.get("price-line")  # needs slot 'series'
    data, errors = _extractor.resolve(vt, {}, CRM_DATA)
    assert data == {}
    assert any("series" in e for e in errors)


def test_bad_path_degrades():
    vt = registry.get("price-line")
    data, errors = _extractor.resolve(
        vt, {"series": "valuation_data.json:nope.not.here"}, CRM_DATA)
    assert data == {}
    assert errors


def test_transform_scales_and_rounds():
    vt = registry.get("category-bar")  # extract slot 'values'
    data, errors = _extractor.resolve(
        vt,
        {"values": "valuation_data.json:stock_metrics.financials.history.revenue_annual"},
        CRM_DATA,
        transforms={"values": {"scale": 1e-9, "round": 1}},
    )
    assert errors == []
    # raw billions -> single-decimal billions
    assert data["values"] == [31.4, 34.9, 37.9, 41.5]


def test_transform_is_noop_on_strings():
    vt = registry.get("verdict-callout")  # extract slots are strings
    data, errors = _extractor.resolve(
        vt,
        {"recommendation": "analysis.json:recommendation",
         "confidence": "analysis.json:confidence"},
        CRM_DATA,
        transforms={"recommendation": {"scale": 1e-9}},
    )
    assert errors == []
    assert data["recommendation"] == "Buy"  # unchanged


def test_drops_synthetic_labels_keys():
    vt = registry.get("price-line")
    data, _ = _extractor.resolve(
        vt, {"series": "valuation_data.json:historical_data.price_history?last=5"}, CRM_DATA)
    assert "series" in data
    assert "series_labels" not in data  # render computes labels itself


# ── intent resolution (fake LLM) ────────────────────────────────────────────

def test_intent_resolved_via_llm_then_read_deterministically():
    vt = registry.get("price-line")
    llm = _FakeLLM("valuation_data.json:historical_data.price_history?last=63")
    data, errors = _extractor.resolve(
        vt, {"series": "last 3 months of daily close prices"}, CRM_DATA, llm=llm)
    assert errors == []
    assert len(data["series"]) == 63
    # The model saw the request and the schema, not the values.
    assert "close" in llm.last_prompt.lower()


def test_intent_without_llm_degrades():
    vt = registry.get("price-line")
    data, errors = _extractor.resolve(
        vt, {"series": "last 3 months of prices"}, CRM_DATA, llm=None)
    assert data == {}
    assert any("no model" in e for e in errors)


def test_intent_llm_returns_garbage_degrades():
    vt = registry.get("price-line")
    llm = _FakeLLM("I think you want the price history")  # not a spec line
    data, errors = _extractor.resolve(
        vt, {"series": "the prices"}, CRM_DATA, llm=llm)
    assert data == {}
    assert any("valid spec" in e for e in errors)
