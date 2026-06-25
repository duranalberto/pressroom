"""Tests for src/agents/outline.py — body-only planning contract."""

from __future__ import annotations

from src.agents import outline
from src.agents.outline import (
    _OUTLINE_PROMPT,
    _SYSTEM,
    _SYSTEM_INTERVIEW,
    _build_interview_system,
    _build_system,
    _build_template_context,
)


def test_outline_prompts_are_body_only():
    combined = "\n".join([_SYSTEM, _OUTLINE_PROMPT])
    assert "frontmatter" not in combined.lower()
    assert "Publication Metadata" not in combined
    assert "THEJOURNAL_GUIDE_POLICY" not in combined
    assert "mdx-blog-writer" not in combined
    assert "body" in combined


def test_outline_system_no_longer_owns_the_question_job():
    """The questions responsibility moved to the lean interview prompt; the outline
    system must not still instruct the model to generate follow-up questions."""
    assert "Generate targeted follow-up questions" not in _SYSTEM
    assert "interview is already done" in _SYSTEM


def test_interview_system_is_lean_no_visual_or_artifact_context():
    """The interview only asks questions, so it must not carry the visual menu,
    artifact-slot rules, or input-file schema that bloat the outline prompt."""
    assert "artifact-slot" not in _SYSTEM_INTERVIEW
    assert "VISUAL COMPONENTS AVAILABLE" not in _SYSTEM_INTERVIEW
    assert "INPUT FILES AVAILABLE" not in _SYSTEM_INTERVIEW
    assert "{visual_menu}" not in _SYSTEM_INTERVIEW
    # It still grounds the questions in the template identity.
    assert "TEMPLATE USED" in _SYSTEM_INTERVIEW


def test_build_interview_system_omits_visual_menu(monkeypatch):
    monkeypatch.setattr(outline, "load_doc", lambda name: "VISUAL-MENU-SENTINEL")
    system = _build_interview_system({
        "template_data": {"name": "t", "agents": {"outline": {"structure": [
            {"id": "intro", "title": "Why It Matters"},
        ]}}},
    })
    assert "VISUAL-MENU-SENTINEL" not in system   # the heavy menu doc is never loaded here
    assert "Why It Matters" in system             # but template structure still guides it


def test_build_interview_system_appends_finetune(monkeypatch):
    monkeypatch.setattr(outline, "load_doc", lambda name: "MENU")
    system = _build_interview_system({
        "template_data": {"name": "t", "agents": {"outline": {"prompt": "Ask about scope."}}},
    })
    assert "ADDITIONAL INSTRUCTIONS (from template)" in system
    assert "Ask about scope." in system


def test_outline_owns_mermaid_artifact_prompt_guidance():
    assert "Mermaid flowchart TD" in _OUTLINE_PROMPT
    assert "Mermaid sequenceDiagram" in _OUTLINE_PROMPT
    assert "the visualizer node renders every artifact" in _OUTLINE_PROMPT
    assert "Do NOT try to write the actual MDX" in _OUTLINE_PROMPT


def test_outline_prompt_drops_the_wordy_data_directive_block():
    # The data= grammar block moved into visual templates + the extractor.
    assert "DATA-BACKED CHARTS" not in _OUTLINE_PROMPT
    assert "semicolon-separated bindings" not in _OUTLINE_PROMPT
    # Charts are now template-only.
    assert 'template="<id>"' in _OUTLINE_PROMPT


def test_visuals_block_lists_templates_and_preconfigured(tmp_path):
    from src.agents.outline import _build_visuals_block
    template = {
        "visuals": [
            {"id": "price-3m", "template": "price-line", "section": "market"},
        ],
        "agents": {"outline": {"structure": [{"id": "market", "title": "Market Snapshot"}]}},
    }
    block = _build_visuals_block(template)
    assert "VISUAL TEMPLATES AVAILABLE" in block          # the registry menu
    assert "PRECONFIGURED VISUALS" in block
    assert 'id="price-3m" template="price-line"' in block  # exact fence to place
    assert "Market Snapshot" in block                      # resolved section title


def test_outline_no_longer_imports_full_writer_skill_loader():
    assert not hasattr(outline, "load_skill")


def test_template_context_includes_structure_from_new_location():
    template = {
        "name": "t",
        "agents": {"outline": {"structure": [
            {"id": "intro", "title": "Why It Matters", "description": "Set up the problem."},
        ]}},
    }
    ctx = _build_template_context(template)
    assert "Required Publication Structure" in ctx
    assert "Why It Matters" in ctx
    assert "Set up the problem." in ctx


def test_template_context_includes_structure_from_legacy_location():
    template = {"name": "t", "outline_structure": [{"id": "x", "title": "Legacy Section"}]}
    ctx = _build_template_context(template)
    assert "Legacy Section" in ctx


def test_build_system_appends_finetune_when_set(monkeypatch):
    monkeypatch.setattr(outline, "load_doc", lambda name: "VISUAL MENU")
    system = _build_system({
        "template_data": {"name": "t", "agents": {"outline": {"prompt": "Keep sections short."}}},
    })
    assert "ADDITIONAL INSTRUCTIONS (from template)" in system
    assert "Keep sections short." in system


def test_build_system_no_finetune_when_unset(monkeypatch):
    monkeypatch.setattr(outline, "load_doc", lambda name: "VISUAL MENU")
    system = _build_system({"template_data": {"name": "t"}})
    assert "ADDITIONAL INSTRUCTIONS (from template)" not in system


def test_run_interview_generates_and_stores_questions(monkeypatch):
    monkeypatch.setattr(outline, "build_model", lambda: object())
    monkeypatch.setattr(outline, "load_doc", lambda name: "VISUAL MENU")
    captured: dict[str, str] = {}

    def fake_invoke(llm, messages):
        captured["user"] = messages[-1].content
        return "UNDERSTANDING: x\n\nQUESTIONS:\n1. Q?\n   DEFAULT: A"

    monkeypatch.setattr(outline, "invoke_with_retry", fake_invoke)

    result = outline.run_interview({
        "petition_content": "PETITION-XYZ",
        "template_data": {"name": "default"},
        "tone": "conversational",
        "audience": "devs",
        "additional_context": "ctx",
    })

    assert "QUESTIONS:" in result["followup_questions"]
    assert result["tone"] == "conversational"
    assert "PETITION-XYZ" in captured["user"]


def test_run_uses_stored_questions_without_regenerating(monkeypatch):
    """The outline node must reuse the interview's questions and make exactly one LLM
    call (the outline) — never a second question-generation call on resume."""
    seen: dict[str, object] = {}

    def fake_interrupt(payload):
        seen["payload"] = payload
        return {"followup_context": "Q: a\nA: b"}

    calls = {"n": 0}

    def fake_invoke(llm, messages):
        calls["n"] += 1
        return "## Section Plan\n### H2 Title"

    monkeypatch.setattr(outline, "interrupt", fake_interrupt)
    monkeypatch.setattr(outline, "build_model", lambda: object())
    monkeypatch.setattr(outline, "load_doc", lambda name: "MENU")
    monkeypatch.setattr(outline, "invoke_with_retry", fake_invoke)

    result = outline.run({
        "petition_content": "PET",
        "template_data": {"name": "default"},
        "followup_questions": "STORED QUESTIONS",
        "tone": "conversational",
        "audience": "devs",
        "additional_context": "ctx",
    })

    assert seen["payload"]["questions"] == "STORED QUESTIONS"  # not regenerated
    assert calls["n"] == 1                                     # outline only, no question call
    assert "Section Plan" in result["outline"]
    assert "Q: a" in result["additional_context"]
