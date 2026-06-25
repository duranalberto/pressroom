"""Distilled, detector-backed AI-pattern catalogue for the humanizer.

The humanizer used to inject the entire ``skills/humanizer/SKILL.md`` (5,107 words, all 33
patterns with before/after examples) into every system prompt and ask the model to "apply
every applicable pattern" in one pass. On a local model that is the classic dilution
failure: most of those 5,000 words describe patterns the draft does not contain, and the
real instructions drown.

This module replaces that with the lesson the ``_ui``/``_mermaid`` sub-agents already use:
load only what this body needs. Each :class:`Pattern` pairs a concise rewrite directive with
a cheap deterministic detector. :func:`select_patterns` runs the detectors over the draft and
returns only the patterns that actually fire (plus a small always-on voice core), so the
prompt carries ~1,000-1,500 words of *relevant* guidance instead of 5,100 of mostly-noise.

The catalogue distils the same patterns as the skill; the full skill stays on disk as the
human reference. Detectors are pure functions, so they unit-test like every other ``_helper``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

_FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`]*`")
_HEADING_RE = re.compile(r"^#{2,4}\s+(.+)$", re.MULTILINE)

# Cap on how many detected patterns we inject, so a messy draft cannot blow the prompt back
# up to the size we are trying to escape. The always-on core is always included on top.
_MAX_DETECTED = 10


def prose_only(body: str) -> str:
    """Strip fenced code blocks and inline code so detectors never fire on code."""
    return _INLINE_CODE_RE.sub(" ", _FENCED_CODE_RE.sub(" ", body))


@dataclass(frozen=True)
class Pattern:
    """A single AI-writing pattern with a cheap detector and a rewrite directive.

    Attributes:
        id: Kebab-case identifier (e.g. ``"ai-vocab"``).
        name: Human-readable name shown in the prompt.
        guidance: Rewrite directive injected into the humanizer system prompt.
        detector: Callable that returns ``True`` when the pattern is present in
            prose text. Receives code-stripped prose unless the pattern id is
            listed in ``_RAW_BODY_DETECTORS``.
        always_on: If ``True``, the pattern is included in every prompt
            regardless of whether the detector fires.
    """
    id: str
    name: str
    guidance: str
    detector: Callable[[str], bool]
    always_on: bool = False


# ── individual detectors ─────────────────────────────────────────────────────────

# Overused "AI vocabulary". Word-boundary matched, case-insensitive.
_AI_VOCAB = (
    "delve", "leverage", "seamless", "seamlessly", "robust", "underscore", "underscores",
    "pivotal", "testament", "realm", "landscape", "tapestry", "intricate", "crucial",
    "vibrant", "myriad", "navigating", "elevate", "unlock", "harness", "foster",
)
_AI_VOCAB_RE = re.compile(r"\b(" + "|".join(_AI_VOCAB) + r")\b", re.IGNORECASE)

_FILLER_RE = re.compile(
    r"\b(it'?s worth noting|it is important to note|needless to say|"
    r"at the end of the day|when it comes to|in the world of)\b",
    re.IGNORECASE,
)
_HEDGE_RE = re.compile(
    r"\b(arguably|generally speaking|in many cases|some would argue|it could be argued|"
    r"more or less|to some extent)\b",
    re.IGNORECASE,
)
_CONCLUSION_RE = re.compile(
    r"(^|\n)\s*(in conclusion|in summary|to sum up|overall|ultimately)\b",
    re.IGNORECASE,
)
_RHETORICAL_OPENER_RE = re.compile(
    r"\b(ever wondered|have you ever|what if|picture this|let'?s face it|imagine a)\b",
    re.IGNORECASE,
)
_SIGNIFICANCE_RE = re.compile(
    r"\b(plays? an? (?:crucial|key|vital|pivotal) role|stands? as a testament|"
    r"a key milestone|broader (?:significance|implications)|in today'?s (?:fast-paced|"
    r"digital|modern) (?:world|landscape)|cannot be overstated)\b",
    re.IGNORECASE,
)
_WEASEL_RE = re.compile(
    r"\b(experts (?:say|agree|believe)|it is widely believed|many believe|"
    r"studies show|research suggests|some say)\b",
    re.IGNORECASE,
)
_SIGNPOST_RE = re.compile(
    r"\b(in this section|as mentioned (?:earlier|above)|let'?s (?:dive in|explore|take a look)|"
    r"now,? let'?s|before we (?:dive|begin))\b",
    re.IGNORECASE,
)
_NEGATIVE_PARALLELISM_RE = re.compile(
    r"\b(not only\b.*?\bbut(?: also)?\b|it'?s not (?:just |merely )?\w+.*?,? it'?s\b|"
    r"isn'?t (?:just|about)\b.*?\bit'?s\b)",
    re.IGNORECASE | re.DOTALL,
)
# A list item that opens with a bolded lead-in ("- **Term:** desc") — the colon may sit
# inside or just after the bold span, so match the bold lead-in itself.
_INLINE_HEADER_LIST_RE = re.compile(r"(?m)^\s*[-*+]\s+\*\*[^*]+\*\*")
_CURLY_RE = re.compile(r"[‘’“”]")
_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF←-⇿⬀-⯿]"
)
_HYPHEN_PAIR_RE = re.compile(r"\b\w+-\w+(?:,?\s+\w+-\w+){2,}")


def _detect_rule_of_three(text: str) -> bool:
    """Fire when comma-and triads ("a, b, and c") recur — the Rule-of-Three tic."""
    return len(re.findall(r",\s+\w[\w\s]*?,?\s+and\s+\w", text, re.IGNORECASE)) >= 3


def _detect_boldface(text: str) -> bool:
    return text.count("**") >= 8  # >= 4 bolded spans


def _detect_title_case_headings(body: str) -> bool:
    for heading in _HEADING_RE.findall(body):
        words = [w for w in re.findall(r"[A-Za-z]+", heading) if len(w) >= 3]
        if len(words) >= 2 and all(w[0].isupper() for w in words):
            return True
    return False


def _kw(pattern: re.Pattern) -> Callable[[str], bool]:
    """Wrap a compiled regex into a ``Pattern.detector`` callable.

    Args:
        pattern: Compiled regex to search for.

    Returns:
        A function that returns ``True`` when ``pattern`` matches anywhere
        in the input string.
    """
    return lambda text: bool(pattern.search(text))


# ── the catalogue ────────────────────────────────────────────────────────────────

CATALOGUE: tuple[Pattern, ...] = (
    Pattern(
        "voice", "Personality and Soul",
        "Keep a real point of view. Prefer concrete, specific observations over smooth, "
        "anonymous summary. The prose should sound like one knowledgeable person talking, "
        "not a committee.",
        lambda _t: False, always_on=True,
    ),
    Pattern(
        "ai-vocab", "Overused AI Vocabulary",
        "Replace inflated words (delve, leverage, robust, seamless, pivotal, crucial, realm, "
        "landscape, tapestry, intricate) with plain, specific wording. Say what actually "
        "happens.",
        _kw(_AI_VOCAB_RE),
    ),
    Pattern(
        "significance", "Inflated Significance and Trend Framing",
        "Cut 'plays a crucial role', 'stands as a testament', 'in today's fast-paced world', "
        "'cannot be overstated'. State the concrete fact and let it carry its own weight.",
        _kw(_SIGNIFICANCE_RE),
    ),
    Pattern(
        "negative-parallelism", "Negative Parallelisms",
        "Rewrite 'it's not just X, it's Y' and 'not only X but also Y' as a single direct "
        "claim. These hollow contrasts add rhythm but no information.",
        _kw(_NEGATIVE_PARALLELISM_RE),
    ),
    Pattern(
        "rule-of-three", "Rule-of-Three Overuse",
        "Break the habit of grouping everything in threes ('fast, cheap, and reliable'). Vary "
        "list length to what is actually true; two items or four are fine.",
        _detect_rule_of_three,
    ),
    Pattern(
        "filler", "Filler Phrases",
        "Delete throat-clearing like 'it's worth noting', 'when it comes to', 'needless to "
        "say'. Lead with the substantive clause instead.",
        _kw(_FILLER_RE),
    ),
    Pattern(
        "hedging", "Excessive Hedging",
        "Trim 'arguably', 'generally speaking', 'to some extent', 'some would argue'. Commit "
        "to the claim or cut it.",
        _kw(_HEDGE_RE),
    ),
    Pattern(
        "generic-conclusion", "Generic Positive Conclusions",
        "Drop 'In conclusion', 'Overall', 'Ultimately' wrap-ups that restate without adding. "
        "End on the last real point.",
        _kw(_CONCLUSION_RE),
    ),
    Pattern(
        "rhetorical-opener", "Conversational Rhetorical Openers",
        "Remove 'Ever wondered', 'What if', 'Picture this', 'Let's face it' openers. Open on "
        "the concrete subject.",
        _kw(_RHETORICAL_OPENER_RE),
    ),
    Pattern(
        "weasel", "Vague Attributions and Weasel Words",
        "Replace 'experts say', 'studies show', 'many believe' with a specific source or a "
        "first-person claim. Unsourced authority reads as filler.",
        _kw(_WEASEL_RE),
    ),
    Pattern(
        "signposting", "Signposting and Announcements",
        "Cut 'In this section', 'Let's dive in', 'As mentioned earlier'. Just say the thing; "
        "structure shows itself.",
        _kw(_SIGNPOST_RE),
    ),
    Pattern(
        "inline-header-list", "Inline-Header Vertical Lists",
        "Convert '- **Term:** description' bullet stacks into real prose paragraphs or a clean "
        "list without the bolded inline headers.",
        lambda _t: False,  # detected on raw body, see select_patterns
    ),
    Pattern(
        "boldface", "Overuse of Boldface",
        "Stop bolding phrases for emphasis throughout the prose. Reserve bold for genuine UI "
        "labels; let sentence structure carry emphasis.",
        _detect_boldface,
    ),
    Pattern(
        "title-case", "Title Case in Headings",
        "Use sentence case for headings ('Why it matters', not 'Why It Matters'). Keep proper "
        "nouns capitalized.",
        lambda _t: False,  # detected on raw body, see select_patterns
    ),
    Pattern(
        "hyphen-pair", "Hyphenated-Pair Overuse",
        "Thin out stacked compound modifiers ('next-generation, high-performance, cloud-native'). "
        "Keep the one that matters.",
        _kw(_HYPHEN_PAIR_RE),
    ),
    Pattern(
        "emoji", "Emojis",
        "Remove decorative emojis from prose and headings.",
        lambda _t: False,  # detected on raw body, see select_patterns
    ),
    Pattern(
        "curly-quotes", "Curly Quotation Marks",
        "Use straight quotes ' and \" rather than curly typographic quotes.",
        lambda _t: False,  # handled mechanically + detected on raw body, see select_patterns
    ),
)

# Patterns whose detector must run on the RAW body (headings, list markers, glyphs), not on
# the code-stripped prose.
_RAW_BODY_DETECTORS: dict[str, Callable[[str], bool]] = {
    "inline-header-list": lambda body: bool(_INLINE_HEADER_LIST_RE.search(body)),
    "title-case": _detect_title_case_headings,
    "emoji": lambda body: bool(_EMOJI_RE.search(body)),
    "curly-quotes": lambda body: bool(_CURLY_RE.search(body)),
}


def select_patterns(body: str) -> list[Pattern]:
    """Return the always-on core plus every catalogue pattern whose detector fires.

    Detected patterns are capped at ``_MAX_DETECTED`` (catalogue order = priority) so a noisy
    draft cannot reinflate the prompt. The always-on voice pattern is always first.
    """
    prose = prose_only(body)
    selected: list[Pattern] = []
    detected: list[Pattern] = []
    for pattern in CATALOGUE:
        if pattern.always_on:
            selected.append(pattern)
            continue
        raw_detector = _RAW_BODY_DETECTORS.get(pattern.id)
        fired = raw_detector(body) if raw_detector else pattern.detector(prose)
        if fired:
            detected.append(pattern)
    return selected + detected[:_MAX_DETECTED]


def render_patterns(patterns: list[Pattern]) -> str:
    """Render selected patterns as a compact, numbered prompt block."""
    lines = []
    for i, p in enumerate(patterns, 1):
        lines.append(f"{i}. {p.name} — {p.guidance}")
    return "\n".join(lines)


def apply_mechanical_fixes(body: str) -> str:
    """Deterministically fix the purely mechanical patterns, so the LLM never has to.

    Currently: straighten curly quotation marks. (Em dashes are stripped separately by
    ``mdx_document.strip_em_dashes``.) Code spans and fenced blocks are left untouched.
    """
    def _straighten(segment: str) -> str:
        return (
            segment.replace("‘", "'").replace("’", "'")
            .replace("“", '"').replace("”", '"')
        )

    out: list[str] = []
    in_fence = False
    for line in body.split("\n"):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        # Preserve inline code spans verbatim; straighten only the prose around them.
        parts = _INLINE_CODE_RE.split(line)
        codes = _INLINE_CODE_RE.findall(line)
        rebuilt = []
        for j, part in enumerate(parts):
            rebuilt.append(_straighten(part))
            if j < len(codes):
                rebuilt.append(codes[j])
        out.append("".join(rebuilt))
    return "\n".join(out)
