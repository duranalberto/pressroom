"""Tests for src/json_query.py — deterministic JSON lookup rooted at the input dir."""

from __future__ import annotations

import json

import pytest

from src.json_query import JsonQueryError, clear_cache, query


@pytest.fixture
def input_dir(tmp_path):
    data = {
        "ticker": "CRM",
        "valuations": {
            "DCF": {"scenarios": {"Base": {"intrinsic_value_per_share": 7314.55}}},
            "PE": {"scenarios": {"Base": {"present_value": 7630.4}}},
        },
        "historical_data": {"price_history": [float(i) for i in range(100)]},
        "items": [{"title": "first"}, {"title": "second"}],
    }
    (tmp_path / "valuation_data.json").write_text(json.dumps(data), encoding="utf-8")
    (tmp_path / "broken.json").write_text("{not valid json", encoding="utf-8")
    clear_cache()
    return tmp_path


# ── navigation ─────────────────────────────────────────────────────────────────

def test_query_top_level_scalar(input_dir):
    assert query("valuation_data.json", "ticker", input_dir=input_dir) == "CRM"


def test_query_nested_path(input_dir):
    v = query("valuation_data.json", "valuations.DCF.scenarios.Base.intrinsic_value_per_share",
              input_dir=input_dir)
    assert v == 7314.55


def test_query_array_index(input_dir):
    assert query("valuation_data.json", "items[1].title", input_dir=input_dir) == "second"


def test_query_returns_full_array(input_dir):
    v = query("valuation_data.json", "historical_data.price_history", input_dir=input_dir)
    assert len(v) == 100


# ── last= tail slicing ───────────────────────────────────────────────────────

def test_query_last_n_slices_tail(input_dir):
    v = query("valuation_data.json", "historical_data.price_history", last=10, input_dir=input_dir)
    assert v == [float(i) for i in range(90, 100)]


def test_query_last_on_non_list_errors(input_dir):
    with pytest.raises(JsonQueryError):
        query("valuation_data.json", "ticker", last=5, input_dir=input_dir)


def test_query_last_longer_than_series_returns_all(input_dir):
    v = query("valuation_data.json", "historical_data.price_history", last=500,
              input_dir=input_dir)  # 500 > 100
    assert len(v) == 100


def test_query_last_zero_errors(input_dir):
    with pytest.raises(JsonQueryError, match="positive integer"):
        query("valuation_data.json", "historical_data.price_history", last=0,
              input_dir=input_dir)


def test_query_last_negative_errors(input_dir):
    with pytest.raises(JsonQueryError, match="positive integer"):
        query("valuation_data.json", "historical_data.price_history", last=-5,
              input_dir=input_dir)


def test_query_last_non_int_errors(input_dir):
    with pytest.raises(JsonQueryError, match="positive integer"):
        query("valuation_data.json", "historical_data.price_history", last="3mo",  # type: ignore[arg-type]
              input_dir=input_dir)


# ── failure modes ──────────────────────────────────────────────────────────────

def test_query_missing_file_errors(input_dir):
    with pytest.raises(JsonQueryError, match="not found"):
        query("nope.json", "ticker", input_dir=input_dir)


def test_query_missing_path_errors(input_dir):
    with pytest.raises(JsonQueryError, match="not found"):
        query("valuation_data.json", "valuations.ZZZ.scenarios", input_dir=input_dir)


def test_query_malformed_json_errors(input_dir):
    with pytest.raises(JsonQueryError, match="not valid JSON"):
        query("broken.json", "x", input_dir=input_dir)


def test_query_rejects_path_traversal(input_dir):
    with pytest.raises(JsonQueryError, match="outside the input directory"):
        query("../secret.json", "x", input_dir=input_dir)


def test_query_rejects_absolute_escape(input_dir, tmp_path):
    outside = tmp_path.parent / "outside.json"
    outside.write_text('{"x": 1}', encoding="utf-8")
    with pytest.raises(JsonQueryError):
        query(str(outside), "x", input_dir=input_dir)


# ── caching ────────────────────────────────────────────────────────────────────

def test_query_uses_cache_until_file_changes(input_dir):
    assert query("valuation_data.json", "ticker", input_dir=input_dir) == "CRM"
    # Rewrite with a new mtime; cache key includes mtime so the new value is read.
    import os
    import time
    path = input_dir / "valuation_data.json"
    new = json.loads(path.read_text())
    new["ticker"] = "AAPL"
    path.write_text(json.dumps(new), encoding="utf-8")
    os.utime(path, (time.time() + 5, time.time() + 5))
    assert query("valuation_data.json", "ticker", input_dir=input_dir) == "AAPL"
