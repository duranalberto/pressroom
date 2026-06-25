"""Tests for src/graph.py — _route_review conditional edge logic."""

from __future__ import annotations

from src.graph import _route_review


# ── Approval path ─────────────────────────────────────────────────────────────

def test_approved_routes_to_humanizer():
    state = {"review_approved": True, "review_iteration": 1, "max_iterations": 3}
    assert _route_review(state) == "humanizer"


def test_approved_on_first_iteration_routes_to_humanizer():
    state = {"review_approved": True, "review_iteration": 0, "max_iterations": 3}
    assert _route_review(state) == "humanizer"


# ── Revision path ─────────────────────────────────────────────────────────────

def test_not_approved_under_max_routes_to_writer():
    state = {"review_approved": False, "review_iteration": 1, "max_iterations": 3}
    assert _route_review(state) == "writer"


def test_not_approved_at_max_still_routes_to_writer():
    # iteration == max_iterations: writer still gets one more revision (> not >=)
    state = {"review_approved": False, "review_iteration": 3, "max_iterations": 3}
    assert _route_review(state) == "writer"


# ── Force-advance path ────────────────────────────────────────────────────────

def test_not_approved_over_max_force_advances_to_humanizer():
    state = {"review_approved": False, "review_iteration": 4, "max_iterations": 3}
    assert _route_review(state) == "humanizer"


def test_iteration_far_over_max_still_force_advances():
    state = {"review_approved": False, "review_iteration": 99, "max_iterations": 3}
    assert _route_review(state) == "humanizer"


# ── Default / missing state keys ─────────────────────────────────────────────

def test_empty_state_defaults_to_writer():
    # review_approved defaults to False, iteration/max default to 0/3 → goes to writer
    assert _route_review({}) == "writer"


def test_missing_approved_key_goes_to_writer():
    state = {"review_iteration": 1, "max_iterations": 3}
    assert _route_review(state) == "writer"
