"""Tests for src/agents/humanizer_patterns.py — the triaged AI-pattern catalogue."""

from __future__ import annotations

from src.agents.humanizer_patterns import (
    CATALOGUE,
    _MAX_DETECTED,
    apply_mechanical_fixes,
    prose_only,
    render_patterns,
    select_patterns,
)


def _ids(patterns):
    return {p.id for p in patterns}


def test_voice_pattern_is_always_selected():
    assert "voice" in _ids(select_patterns(""))
    assert "voice" in _ids(select_patterns("Perfectly clean prose with nothing wrong."))


def test_clean_prose_selects_only_the_core():
    selected = select_patterns("The cache holds 64 entries and evicts the oldest first.")
    assert _ids(selected) == {"voice"}


def test_detects_ai_vocabulary():
    selected = select_patterns("We leverage a robust pipeline to delve into the data.")
    assert "ai-vocab" in _ids(selected)


def test_detects_negative_parallelism():
    selected = select_patterns("It's not just a cache, it's a foundation for everything.")
    assert "negative-parallelism" in _ids(selected)


def test_detects_generic_conclusion():
    selected = select_patterns("Work happened here.\n\nIn conclusion, it all worked out fine.")
    assert "generic-conclusion" in _ids(selected)


def test_detectors_ignore_code_blocks():
    body = "Plain prose.\n\n```python\nleverage = robust_seamless_delve()\n```\n"
    assert "ai-vocab" not in _ids(select_patterns(body))


def test_detects_inline_header_list_on_raw_body():
    body = "- **Latency:** under 5ms\n- **Throughput:** 10k rps\n"
    assert "inline-header-list" in _ids(select_patterns(body))


def test_detects_title_case_headings_on_raw_body():
    assert "title-case" in _ids(select_patterns("## Why It Really Matters\n\nText."))
    assert "title-case" not in _ids(select_patterns("## Why it matters\n\nText."))


def test_detects_emoji_and_curly_quotes_on_raw_body():
    assert "emoji" in _ids(select_patterns("Great work 🚀 shipped today."))
    assert "curly-quotes" in _ids(select_patterns("He said “done” and left."))


def test_detected_patterns_are_capped():
    noisy = (
        "We leverage robust seamless tooling. It's not just fast, it's pivotal. "
        "Experts say studies show many believe. In conclusion, overall it works. "
        "Ever wondered what if? Let's dive in. It's worth noting, generally speaking. "
        "It plays a crucial role and cannot be overstated in today's fast-paced world. "
        "next-gen, high-performance, cloud-native, battle-tested systems."
    )
    selected = select_patterns(noisy)
    # core voice + at most the cap of detected patterns
    assert len(selected) <= _MAX_DETECTED + 1


def test_render_patterns_numbers_each_entry():
    rendered = render_patterns(select_patterns("We leverage robust tooling."))
    assert "1. Personality and Soul" in rendered
    assert "Overused AI Vocabulary" in rendered


def test_apply_mechanical_fixes_straightens_curly_quotes():
    assert apply_mechanical_fixes("He said “done”.") == 'He said "done".'
    assert apply_mechanical_fixes("don’t stop") == "don't stop"


def test_apply_mechanical_fixes_leaves_code_fences_untouched():
    body = "Prose “quote”.\n\n```js\nconst s = “keep”;\n```\n"
    fixed = apply_mechanical_fixes(body)
    assert 'Prose "quote".' in fixed
    assert "const s = “keep”;" in fixed  # inside the fence, unchanged


def test_prose_only_strips_code():
    assert "secret" not in prose_only("text `secret` more")
    assert "fenced" not in prose_only("a\n\n```\nfenced\n```\n\nb")


def test_catalogue_ids_are_unique():
    ids = [p.id for p in CATALOGUE]
    assert len(ids) == len(set(ids))
