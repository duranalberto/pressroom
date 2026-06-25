"""Tests for src/template_config.py — per-agent template fine-tuning helpers."""

from __future__ import annotations

from src.template_config import (
    agent_prompt,
    apply_finetune,
    outline_structure,
    section_titles,
    warn_unknown_agents,
)


# ── section_titles ───────────────────────────────────────────────────────────

def test_section_titles_prefers_structure_then_outline():
    template = {"agents": {"outline": {"structure": [
        {"id": "a", "title": "Company Overview"},
        {"id": "b", "title": "Valuation"},
    ]}}}
    outline = "## Section Plan\n\n### Company Overview\n\n### Extra From Outline\n"
    titles = section_titles(template, outline)
    # Structure titles first, outline-only sections appended, no duplicate of Company Overview.
    assert titles == ["Company Overview", "Valuation", "Extra From Outline"]


def test_section_titles_empty_when_nothing_available():
    assert section_titles({}, "") == []


# ── agent_prompt ───────────────────────────────────────────────────────────────

def test_agent_prompt_returns_set_value():
    template = {"agents": {"writer": {"prompt": "  be concise  "}}}
    assert agent_prompt(template, "writer") == "be concise"


def test_agent_prompt_absent_agent_returns_empty():
    assert agent_prompt({"agents": {"writer": {"prompt": "x"}}}, "reviewer") == ""


def test_agent_prompt_no_agents_block_returns_empty():
    assert agent_prompt({}, "writer") == ""


def test_agent_prompt_empty_prompt_returns_empty():
    assert agent_prompt({"agents": {"writer": {"prompt": ""}}}, "writer") == ""


def test_agent_prompt_non_dict_entry_returns_empty():
    assert agent_prompt({"agents": {"writer": "oops"}}, "writer") == ""


def test_agent_prompt_non_dict_agents_block_returns_empty():
    assert agent_prompt({"agents": ["nope"]}, "writer") == ""


# ── apply_finetune ─────────────────────────────────────────────────────────────

def test_apply_finetune_appends_when_set():
    template = {"agents": {"writer": {"prompt": "Open with a takeaway."}}}
    result = apply_finetune("BASE", template, "writer")
    assert result.startswith("BASE")
    assert "ADDITIONAL INSTRUCTIONS (from template)" in result
    assert "Open with a takeaway." in result


def test_apply_finetune_noop_when_unset():
    assert apply_finetune("BASE", {}, "writer") == "BASE"
    assert apply_finetune("BASE", {"agents": {}}, "reviewer") == "BASE"


def test_apply_finetune_preserves_braces_in_base_and_prompt():
    """Concatenation, not str.format — braces in either side must survive verbatim."""
    base = 'Return JSON like {{"approved": true}}'
    template = {"agents": {"reviewer": {"prompt": "Use {curly} placeholders."}}}
    result = apply_finetune(base, template, "reviewer")
    assert '{{"approved": true}}' in result
    assert "Use {curly} placeholders." in result


def test_apply_finetune_unset_agent_leaves_base_untouched():
    template = {"agents": {"writer": {"prompt": "x"}}}
    assert apply_finetune("BASE", template, "humanizer") == "BASE"


# ── outline_structure ──────────────────────────────────────────────────────────

def test_outline_structure_new_location():
    template = {"agents": {"outline": {"structure": [{"id": "intro", "title": "Intro"}]}}}
    assert outline_structure(template) == [{"id": "intro", "title": "Intro"}]


def test_outline_structure_legacy_fallback():
    template = {"outline_structure": [{"id": "legacy", "title": "Legacy"}]}
    assert outline_structure(template) == [{"id": "legacy", "title": "Legacy"}]


def test_outline_structure_new_location_wins_over_legacy():
    template = {
        "agents": {"outline": {"structure": [{"id": "new"}]}},
        "outline_structure": [{"id": "legacy"}],
    }
    assert outline_structure(template) == [{"id": "new"}]


def test_outline_structure_empty_new_falls_back_to_legacy():
    template = {
        "agents": {"outline": {"structure": []}},
        "outline_structure": [{"id": "legacy"}],
    }
    assert outline_structure(template) == [{"id": "legacy"}]


def test_outline_structure_missing_returns_empty():
    assert outline_structure({}) == []


# ── warn_unknown_agents ────────────────────────────────────────────────────────

def test_warn_unknown_agents_logs_for_typo(caplog):
    import logging

    with caplog.at_level(logging.WARNING):
        warn_unknown_agents({"agents": {"writter": {"prompt": "x"}, "writer": {"prompt": "y"}}})
    assert "writter" in caplog.text
    assert "writer'" not in caplog.text  # the valid one is not warned about


def test_warn_unknown_agents_silent_when_all_known(caplog):
    import logging

    with caplog.at_level(logging.WARNING):
        warn_unknown_agents({"agents": {"outline": {}, "humanizer": {}}})
    assert caplog.text == ""
