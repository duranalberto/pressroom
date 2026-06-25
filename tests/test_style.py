"""Tests for src/agents/_style.py — the shared body-style canon."""

from __future__ import annotations

from src.agents._style import BODY_STYLE_RULES, style_rules_block


def test_canon_covers_the_core_prose_rules():
    joined = " ".join(BODY_STYLE_RULES).lower()
    assert "em dash" in joined
    assert "colon" in joined
    assert "invent" in joined


def test_style_rules_block_renders_each_rule_as_a_bullet():
    block = style_rules_block()
    for rule in BODY_STYLE_RULES:
        assert f"- {rule}" in block
    assert block.count("\n") == len(BODY_STYLE_RULES) - 1


def test_style_rules_block_supports_custom_bullet():
    assert style_rules_block(bullet="* ").startswith("* ")


def test_writer_system_embeds_the_shared_canon():
    from src.agents.writer import _SYSTEM

    # The canon is interpolated at import time, not left as a placeholder.
    assert "{style_rules}" not in _SYSTEM
    for rule in BODY_STYLE_RULES:
        assert rule in _SYSTEM
