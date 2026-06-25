"""Tests for src/agents/writer.py."""

from __future__ import annotations

from src.agents import writer
from src.agents.writer import _FIRST_DRAFT_PROMPT, _REVISION_PROMPT, _SYSTEM, _build_system
from src.mdx_document import MDXDocument


def test_build_system_appends_finetune_when_set():
    system = _build_system({
        "template_data": {"agents": {"writer": {"prompt": "Open with a takeaway."}}},
    })
    assert system.startswith(_SYSTEM)
    assert "ADDITIONAL INSTRUCTIONS (from template)" in system
    assert "Open with a takeaway." in system


def test_build_system_is_base_when_unset():
    assert _build_system({"template_data": {}}) == _SYSTEM
    assert _build_system({}) == _SYSTEM


def test_writer_prompts_are_body_only():
    combined = "\n".join([_SYSTEM, _FIRST_DRAFT_PROMPT, _REVISION_PROMPT])
    assert "frontmatter" not in combined.lower()
    assert "full .mdx" not in combined.lower()
    assert "THEJOURNAL_GUIDE_POLICY" not in combined
    assert "mdx-blog-writer" not in combined
    assert "mdx-rules" not in combined
    assert "ARTIFACT PLACEHOLDER RULES" not in combined
    assert "Mermaid" not in combined
    assert "mermaid" not in combined
    assert "body" in _FIRST_DRAFT_PROMPT


def test_writer_no_longer_imports_full_mdx_helpers():
    assert not hasattr(writer, "parse_mdx")
    assert not hasattr(writer, "render_mdx")
    assert not hasattr(writer, "load_doc")


def test_writer_has_no_orphan_placeholder_logic():
    assert not hasattr(writer, "_strip_orphaned_placeholders")
    assert not hasattr(writer, "ARTIFACT_TOKEN_RE")
    assert not hasattr(writer, "ARTIFACT_SLOT_ID_RE")


def test_writer_system_prompt_treats_artifact_slot_as_opaque_fence():
    assert "artifact-slot" in _SYSTEM
    assert "verbatim" in _SYSTEM or "exactly" in _SYSTEM
    assert "@@artifact:<id>@@" not in _SYSTEM
    assert "Do NOT copy the fence" not in _SYSTEM


def test_run_returns_body_only_document(monkeypatch):
    body = "Hook paragraph with enough words to be a draft opening.\n\n## Section\n\nContent."

    monkeypatch.setattr(writer, "build_model", lambda: object())
    monkeypatch.setattr(writer, "invoke_with_retry", lambda _llm, _messages: body)

    result = writer.run({
        "outline": "",
        "tone": "conversational",
        "audience": "developers",
        "additional_context": "",
        "review_iteration": 0,
        "review_feedback": None,
    })

    assert result["draft"]["metadata"] == {}
    assert result["draft"]["imports"] == []
    assert result["draft"]["body"].startswith("Hook paragraph")
    # The writer returns the LLM body verbatim (stripped). Separator/heading
    # enforcement is the writer-prompt's job and the reviewer's deterministic lint —
    # the writer node no longer post-processes the body.
    assert result["draft"]["body"] == body


def test_run_preserves_artifact_slot_fence_verbatim(monkeypatch):
    fence = '```artifact-slot\nid="chart-1" context="some chart context"\n```'
    body = f"Hook paragraph.\n\n{fence}\n\n## Section\n\nContent."

    monkeypatch.setattr(writer, "build_model", lambda: object())
    monkeypatch.setattr(writer, "invoke_with_retry", lambda _llm, _messages: body)

    result = writer.run({
        "outline": fence,
        "tone": "conversational",
        "audience": "developers",
        "additional_context": "",
        "review_iteration": 0,
        "review_feedback": None,
    })

    assert fence in result["draft"]["body"]
    assert "@@artifact:chart-1@@" not in result["draft"]["body"]


def test_revision_prompt_receives_body_not_rendered_mdx(monkeypatch):
    captured: dict[str, str] = {}

    def fake_invoke(_llm, messages):
        captured["user"] = messages[-1].content
        return "Revised hook.\n\n## Revised\n\nBody."

    monkeypatch.setattr(writer, "build_model", lambda: object())
    monkeypatch.setattr(writer, "invoke_with_retry", fake_invoke)

    writer.run({
        "outline": "",
        "draft": MDXDocument(
            metadata={"title": "Hidden title"},
            imports=["import Hidden from './Hidden'"],
            body="Current body only.",
        ),
        "review_feedback": "Tighten prose.",
        "review_iteration": 1,
        "tone": "conversational",
        "audience": "developers",
        "additional_context": "",
        "petition_content": "source",
    })

    assert "Current body only." in captured["user"]
    assert "Hidden title" not in captured["user"]
    assert "import Hidden" not in captured["user"]
