"""Tests for src/agents/publisher.py — pure helper functions."""

from __future__ import annotations

from datetime import date

from src.agents import publisher
from src.agents.publisher import (
    _inject_artifacts,
    _merge_artifact_imports,
    _save,
    _slug_from_metadata,
    _strip_remaining_placeholders,
)
from src.mdx_document import MDXDocument
from src.state import Artifact


# ── helpers ───────────────────────────────────────────────────────────────────

def _ph(artifact_id: str, context: str = "some context") -> str:
    return f'```artifact-slot\nid="{artifact_id}" context="{context}"\n```'


# ── _slug_from_metadata ───────────────────────────────────────────────────────

def test_slug_basic_title():
    assert _slug_from_metadata({"title": "My Great Article"}) == "my-great-article"


def test_slug_strips_special_chars():
    assert _slug_from_metadata({"title": "Hello, World! Test"}) == "hello-world-test"


def test_slug_truncated_at_50():
    slug = _slug_from_metadata({"title": "A" * 100})
    assert len(slug) <= 50


def test_slug_empty_title_falls_back():
    assert _slug_from_metadata({}) == "publication"


def test_slug_quoted_title_strips_quotes():
    slug = _slug_from_metadata({"title": '"My Article"'})
    assert slug == "my-article"


def test_slug_collapses_spaces():
    assert _slug_from_metadata({"title": "hello   world"}) == "hello-world"


def test_slug_lowercase():
    assert _slug_from_metadata({"title": "ALL CAPS TITLE"}) == "all-caps-title"


# ── _inject_artifacts ─────────────────────────────────────────────────────────

def test_inject_artifacts_replaces_placeholder():
    content = _ph("chart-1", "a chart")
    artifacts = [Artifact(id="chart-1", content="<EChart />", import_lines=[])]
    result = _inject_artifacts(content, artifacts)
    assert result == "<EChart />"


def test_inject_artifacts_unknown_id_preserved():
    content = _ph("missing", "x")
    result = _inject_artifacts(content, [])
    assert 'id="missing"' in result


def test_inject_artifacts_no_placeholders():
    content = "Just normal content."
    result = _inject_artifacts(content, [])
    assert result == "Just normal content."


def test_inject_artifacts_multiple_replaced():
    content = f"{_ph('a', 'x')}\n{_ph('b', 'y')}"
    artifacts = [
        Artifact(id="a", content="<CompA />", import_lines=[]),
        Artifact(id="b", content="<CompB />", import_lines=[]),
    ]
    result = _inject_artifacts(content, artifacts)
    assert "<CompA />" in result
    assert "<CompB />" in result


def test_inject_artifacts_empty_artifacts_list():
    content = "No placeholders here."
    assert _inject_artifacts(content, []) == "No placeholders here."


# ── _merge_artifact_imports ───────────────────────────────────────────────────

def test_merge_artifact_imports_adds_new():
    doc = MDXDocument(metadata={}, imports=[], body="")
    artifacts = [Artifact(id="x", content="", import_lines=["import Foo from './Foo'"])]
    merged = _merge_artifact_imports(doc, artifacts)
    assert "import Foo from './Foo'" in merged["imports"]


def test_merge_artifact_imports_deduplicates():
    existing_import = "import Foo from './Foo'"
    doc = MDXDocument(metadata={}, imports=[existing_import], body="")
    artifacts = [Artifact(id="x", content="", import_lines=[existing_import])]
    merged = _merge_artifact_imports(doc, artifacts)
    assert merged["imports"].count(existing_import) == 1


def test_merge_artifact_imports_empty_artifacts_returns_same():
    doc = MDXDocument(metadata={}, imports=["import X from 'x'"], body="")
    merged = _merge_artifact_imports(doc, [])
    assert merged == doc


def test_merge_artifact_imports_multiple_artifacts():
    doc = MDXDocument(metadata={}, imports=[], body="")
    artifacts = [
        Artifact(id="a", content="", import_lines=["import A from 'a'"]),
        Artifact(id="b", content="", import_lines=["import B from 'b'"]),
    ]
    merged = _merge_artifact_imports(doc, artifacts)
    assert "import A from 'a'" in merged["imports"]
    assert "import B from 'b'" in merged["imports"]


def test_merge_artifact_imports_preserves_existing():
    doc = MDXDocument(metadata={}, imports=["import Existing from 'e'"], body="")
    artifacts = [Artifact(id="x", content="", import_lines=["import New from 'n'"])]
    merged = _merge_artifact_imports(doc, artifacts)
    assert "import Existing from 'e'" in merged["imports"]
    assert "import New from 'n'" in merged["imports"]


def test_merge_artifact_imports_ignores_empty_import_lines():
    doc = MDXDocument(metadata={}, imports=[], body="")
    artifacts = [Artifact(id="x", content="", import_lines=["", "import A from 'a'", ""])]
    merged = _merge_artifact_imports(doc, artifacts)
    assert "" not in merged["imports"]
    assert "import A from 'a'" in merged["imports"]


def test_merge_artifact_imports_deduplicates_across_artifacts():
    """Two artifacts sharing the same import must not produce a duplicate."""
    shared = "import EChart from '@components/ui/mdx/EChart.astro'"
    doc = MDXDocument(metadata={}, imports=[], body="")
    artifacts = [
        Artifact(id="chart-1", content="", import_lines=[shared]),
        Artifact(id="chart-2", content="", import_lines=[shared]),
    ]
    merged = _merge_artifact_imports(doc, artifacts)
    assert merged["imports"].count(shared) == 1


# ── _inject_artifacts — robustness against content mutations ──────────────────

def test_inject_artifacts_matches_when_closing_quote_missing():
    """When the LLM drops the closing quote of context=, id is still captured."""
    content = '```artifact-slot\nid="model-vs-reality" context="Some context\n```'
    artifacts = [Artifact(id="model-vs-reality", content="```mermaid\nA-->B\n```", import_lines=[])]
    result = _inject_artifacts(content, artifacts)
    assert "artifact-slot" not in result
    assert "A-->B" in result


def test_inject_artifacts_matches_across_multiline_content():
    """Fence with multi-line content (hypothetical LLM line-wrapping) still injects."""
    content = (
        '```artifact-slot\n'
        'id="multi" context="line one\n'
        'line two"\n'
        '```'
    )
    artifacts = [Artifact(id="multi", content="<Callout />", import_lines=[])]
    result = _inject_artifacts(content, artifacts)
    assert "artifact-slot" not in result
    assert "<Callout />" in result


def test_inject_artifacts_matches_bare_placeholder_without_fences():
    """The writer LLM sometimes drops the ``` fence, leaving a bare placeholder.
    Injection must still match it by id (the regression that left raw placeholders)."""
    content = 'Prose before.\n\nartifact-slot\nid="margin-benchmark" context="Callout body text"\n\n---\n\nAfter.'
    artifacts = [Artifact(id="margin-benchmark", content="<Callout>hi</Callout>", import_lines=[])]
    result = _inject_artifacts(content, artifacts)
    assert "artifact-slot" not in result
    assert "<Callout>hi</Callout>" in result
    assert "Prose before." in result
    assert "After." in result


def test_inject_bare_placeholder_does_not_swallow_following_code_fence():
    """A bare placeholder must consume only its own line, never a later code fence."""
    content = 'artifact-slot\nid="bare" context="c"\n\nProse.\n\n```python\nx = 1\n```\n'
    artifacts = [Artifact(id="bare", content="<EChart />", import_lines=[])]
    result = _inject_artifacts(content, artifacts)
    assert "<EChart />" in result
    assert "```python\nx = 1\n```" in result  # code fence untouched
    assert "Prose." in result


def test_strip_remaining_matches_bare_placeholder():
    """A bare (unfenced) placeholder with no artifact must still be stripped, not leaked."""
    content = 'Before.\n\nartifact-slot\nid="ghost" context="never rendered"\n\nAfter.'
    cleaned, stripped = _strip_remaining_placeholders(content)
    assert "artifact-slot" not in cleaned
    assert "ghost" in stripped


# ── @@artifact:id@@ token form (primary writer placement) ──────────────────────

def test_inject_artifacts_replaces_token():
    content = "Before.\n\n@@artifact:price-chart@@\n\nAfter."
    artifacts = [Artifact(id="price-chart", content="<EChart />", import_lines=[])]
    result = _inject_artifacts(content, artifacts)
    assert "@@artifact:price-chart@@" not in result
    assert "<EChart />" in result
    assert "Before." in result and "After." in result


def test_inject_artifacts_token_and_fence_both_handled():
    """Token is primary, but a copied fence is still injected as a backstop."""
    content = '@@artifact:a@@\n\n```artifact-slot\nid="b" context="c"\n```'
    artifacts = [
        Artifact(id="a", content="<Callout>A</Callout>", import_lines=[]),
        Artifact(id="b", content="<Callout>B</Callout>", import_lines=[]),
    ]
    result = _inject_artifacts(content, artifacts)
    assert "<Callout>A</Callout>" in result
    assert "<Callout>B</Callout>" in result
    assert "artifact-slot" not in result and "@@artifact" not in result


def test_strip_remaining_removes_unresolved_token():
    content = "Before.\n\n@@artifact:ghost@@\n\nAfter."
    cleaned, stripped = _strip_remaining_placeholders(content)
    assert "@@artifact" not in cleaned
    assert "ghost" in stripped


# ── _strip_remaining_placeholders ─────────────────────────────────────────────

def test_strip_remaining_removes_unresolved():
    content = f"Before.\n\n{_ph('orphan', 'x')}\n\nAfter."
    cleaned, stripped = _strip_remaining_placeholders(content)
    assert "artifact-slot" not in cleaned
    assert "orphan" in stripped
    assert "Before." in cleaned
    assert "After." in cleaned


def test_strip_remaining_no_placeholders_unchanged():
    content = "Clean content with no placeholders."
    cleaned, stripped = _strip_remaining_placeholders(content)
    assert cleaned == content
    assert stripped == []


def test_strip_remaining_reports_all_ids():
    content = f"{_ph('a', 'x')}\n{_ph('b', 'y')}"
    _, stripped = _strip_remaining_placeholders(content)
    assert set(stripped) == {"a", "b"}


def test_strip_remaining_matches_missing_closing_quote():
    """Even if the LLM dropped the closing quote of context=, the id is still stripped."""
    content = '```artifact-slot\nid="broken" context="no closing quote\n```'
    cleaned, stripped = _strip_remaining_placeholders(content)
    assert "artifact-slot" not in cleaned
    assert "broken" in stripped


# ── _save (run-id prefix) ─────────────────────────────────────────────────────

def test_save_prefixes_run_id(tmp_path):
    path = _save("body", {"title": "My Article"}, tmp_path, run_id="0042")
    expected = f"0042-{date.today().isoformat()}-my-article.mdx"
    assert path.endswith(expected)


def test_save_without_run_id_has_no_prefix(tmp_path):
    path = _save("body", {"title": "My Article"}, tmp_path)
    expected = f"{date.today().isoformat()}-my-article.mdx"
    assert path.endswith(expected)
    assert "-" + expected not in path or path.endswith("/" + expected)


# ── run ──────────────────────────────────────────────────────────────────────

def test_run_renders_metadata_from_state(tmp_path, monkeypatch):
    class FakeConfig:
        output_dir = tmp_path

    monkeypatch.setattr(publisher, "Config", lambda: FakeConfig())

    result = publisher.run({
        "template_name": "default",
        "humanized": MDXDocument(
            metadata={},
            imports=[],
            body="Hook paragraph.\n\n---\n\n## Section\n\nContent.",
        ),
        "metadata": {
            "title": "A Designed Title",
            "description": "Designed by the metadata node.",
            "image": "../assets/thejournal/stock/01.avif",
            "tags": ["finance-analysis", "crm"],
            "draft": True,
        },
        "artifacts": [],
    })

    assert result["final_publication"].startswith("---\n")
    assert 'title: "A Designed Title"' in result["final_publication"]
    assert 'description: "Designed by the metadata node."' in result["final_publication"]
    assert "draft: true" in result["final_publication"]
    assert result["output_path"].endswith("a-designed-title.mdx")


def test_run_prefixes_output_with_run_id(tmp_path, monkeypatch):
    class FakeConfig:
        output_dir = tmp_path

    monkeypatch.setattr(publisher, "Config", lambda: FakeConfig())

    result = publisher.run({
        "template_name": "default",
        "run_id": "0042",
        "humanized": MDXDocument(metadata={}, imports=[], body="Hook.\n\n---\n\n## S\n\nC."),
        "metadata": {"title": "A Designed Title"},
        "artifacts": [],
    })

    assert result["output_path"].endswith(f"0042-{date.today().isoformat()}-a-designed-title.mdx")


def test_run_uses_minimal_fallback_when_no_metadata(tmp_path, monkeypatch):
    class FakeConfig:
        output_dir = tmp_path

    monkeypatch.setattr(publisher, "Config", lambda: FakeConfig())

    result = publisher.run({
        "template_name": "default",
        "humanized": MDXDocument(metadata={}, imports=[], body="Hook.\n\n---\n\n## S\n\nC."),
        "metadata": None,
        "artifacts": [],
    })

    assert 'title: "Publication"' in result["final_publication"]
    assert result["output_path"].endswith("publication.mdx")
