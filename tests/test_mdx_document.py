"""Tests for src/mdx_document.py — pure parsing and rendering logic."""

from __future__ import annotations

from datetime import date

from src.mdx_document import (
    MDXDocument,
    _fm_value,
    parse_mdx,
    render_mdx,
    strip_em_dashes,
)


# ── _fm_value ────────────────────────────────────────────────────────────────

def test_fm_value_bool_true():
    assert _fm_value(True) == "true"


def test_fm_value_bool_false():
    assert _fm_value(False) == "false"


def test_fm_value_date_object():
    assert _fm_value(date(2026, 6, 26)) == "2026-06-26"


def test_fm_value_date_string_stays_unquoted():
    assert _fm_value("2026-06-26") == "2026-06-26"


def test_fm_value_regular_string_gets_quoted():
    assert _fm_value("hello world") == '"hello world"'


def test_fm_value_list_of_strings():
    result = _fm_value(["ai", "llm"])
    assert result == '["ai", "llm"]'


def test_fm_value_integer():
    assert _fm_value(42) == "42"


# ── parse_mdx ────────────────────────────────────────────────────────────────

_FULL_MDX = """\
---
title: "My Article"
description: "A great read"
tags: ["ai", "llm"]
pubDate: 2026-06-26
author: "Alberto Duran"
draft: true
---

import Foo from './Foo'
import Bar from './Bar'

Some body content here.

---

## Section One

Content of section one.
"""


def test_parse_mdx_extracts_metadata():
    doc = parse_mdx(_FULL_MDX)
    assert doc["metadata"]["title"] == "My Article"
    assert doc["metadata"]["author"] == "Alberto Duran"
    assert doc["metadata"]["draft"] is True


def test_parse_mdx_extracts_pubdate():
    doc = parse_mdx(_FULL_MDX)
    # YAML parses bare date strings as date objects
    assert str(doc["metadata"]["pubDate"]) == "2026-06-26"


def test_parse_mdx_extracts_imports():
    doc = parse_mdx(_FULL_MDX)
    assert "import Foo from './Foo'" in doc["imports"]
    assert "import Bar from './Bar'" in doc["imports"]


def test_parse_mdx_extracts_body():
    doc = parse_mdx(_FULL_MDX)
    assert "Some body content here." in doc["body"]
    assert "## Section One" in doc["body"]


def test_parse_mdx_no_frontmatter_fallback():
    content = "No frontmatter here"
    doc = parse_mdx(content)
    assert doc["metadata"] == {}
    assert doc["imports"] == []
    assert doc["body"] == "No frontmatter here"


def test_parse_mdx_no_imports():
    content = '---\ntitle: "Test"\n---\n\nBody only.'
    doc = parse_mdx(content)
    assert doc["imports"] == []
    assert doc["body"] == "Body only."


def test_parse_mdx_empty_body():
    content = '---\ntitle: "Empty"\n---\n'
    doc = parse_mdx(content)
    assert doc["body"] == ""


def test_parse_mdx_imports_not_leaked_into_body():
    doc = parse_mdx(_FULL_MDX)
    assert not any(line.startswith("import ") for line in doc["body"].splitlines())


# ── render_mdx ───────────────────────────────────────────────────────────────

def test_render_mdx_roundtrip_title():
    doc = parse_mdx(_FULL_MDX)
    rendered = render_mdx(doc)
    doc2 = parse_mdx(rendered)
    assert doc2["metadata"]["title"] == doc["metadata"]["title"]


def test_render_mdx_roundtrip_body():
    doc = parse_mdx(_FULL_MDX)
    rendered = render_mdx(doc)
    doc2 = parse_mdx(rendered)
    assert doc2["body"] == doc["body"]


def test_render_mdx_no_imports_omits_import_block():
    doc = MDXDocument(metadata={"title": "T"}, imports=[], body="Hello")
    rendered = render_mdx(doc)
    assert "import" not in rendered
    assert "Hello" in rendered


def test_render_mdx_includes_imports():
    doc = MDXDocument(
        metadata={"title": "T"},
        imports=["import Foo from './Foo'"],
        body="Hello",
    )
    rendered = render_mdx(doc)
    assert "import Foo from './Foo'" in rendered


def test_render_mdx_ends_with_newline():
    doc = MDXDocument(metadata={"title": "T"}, imports=[], body="Hello")
    assert render_mdx(doc).endswith("\n")


def test_render_mdx_frontmatter_fences_present():
    doc = MDXDocument(metadata={"title": "T"}, imports=[], body="Hello")
    rendered = render_mdx(doc)
    assert rendered.startswith("---\n")
    lines = rendered.splitlines()
    assert lines[0] == "---"
    assert "---" in lines[1:]


def test_render_mdx_draft_false_serialized_correctly():
    doc = MDXDocument(metadata={"draft": False}, imports=[], body="X")
    rendered = render_mdx(doc)
    assert "draft: false" in rendered


def test_parse_mdx_deduplicates_imports():
    """LLMs sometimes repeat identical imports; parse_mdx must deduplicate them."""
    content = (
        "---\ntitle: \"T\"\n---\n\n"
        "import Foo from './Foo'\n"
        "import Foo from './Foo'\n"
        "import Bar from './Bar'\n\n"
        "Body text."
    )
    doc = parse_mdx(content)
    assert doc["imports"].count("import Foo from './Foo'") == 1
    assert "import Bar from './Bar'" in doc["imports"]


def test_parse_mdx_deduplication_preserves_order():
    """First occurrence of a duplicate import wins; insertion order is kept."""
    content = (
        "---\ntitle: \"T\"\n---\n\n"
        "import A from 'a'\n"
        "import B from 'b'\n"
        "import A from 'a'\n\n"
        "Body."
    )
    doc = parse_mdx(content)
    assert doc["imports"] == ["import A from 'a'", "import B from 'b'"]


# ── strip_em_dashes ───────────────────────────────────────────────────────────

def test_strip_em_dashes_spaced_replaced_with_comma():
    assert strip_em_dashes("the market — it panics — sometimes") == "the market, it panics, sometimes"


def test_strip_em_dashes_unspaced_replaced():
    assert strip_em_dashes("risk—reward") == "risk, reward"


def test_strip_em_dashes_no_em_dash_unchanged():
    body = "Plain prose with, commas and a hyphen-word."
    assert strip_em_dashes(body) == body


def test_strip_em_dashes_preserves_code_fences():
    body = "Prose — here.\n\n```python\nx = a — b  # em dash inside code\n```\n\nAfter — text."
    result = strip_em_dashes(body)
    assert "x = a — b  # em dash inside code" in result   # code untouched
    assert "Prose, here." in result
    assert "After, text." in result


def test_strip_em_dashes_does_not_swallow_newlines():
    body = "line one —\nline two"
    # The em dash is normalized but the newline (paragraph/line structure) survives.
    result = strip_em_dashes(body)
    assert "\n" in result
    assert "—" not in result


def test_strip_em_dashes_idempotent():
    body = "a — b — c"
    once = strip_em_dashes(body)
    assert strip_em_dashes(once) == once
