"""Agent 3 — Reviewer.

Reads the draft and returns structured feedback. If issues are found,
the graph loops back to the Content Writer (up to max_iterations times).

Uses JSON mode + manual parsing (same pattern as langchain-investor) since
Ollama structured output support varies by model.

Docs loaded:
  Inline body-only publication criteria.
"""

from __future__ import annotations

import json
import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, ValidationError, field_validator
from tenacity import Retrying, stop_after_attempt, wait_exponential

from rich.console import Console

from src.llm import build_model, strip_json_fences
from src.state import PublicationState
from src.template_config import apply_finetune
from src.agents._style import style_rules_block

_console = Console()

logger = logging.getLogger(__name__)

_FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`]*`")
_URL_RE = re.compile(r"https?://\S+")
_H1_RE = re.compile(r"^#(?!#)\s", re.MULTILINE)   # a single-`#` heading (forbidden in body)
_H2_RE = re.compile(r"^##\s", re.MULTILINE)
_WORD_RE = re.compile(r"\b[\w'-]+\b")

# Reading-time + word-count band the body must land in (mirrors the writer/outline targets).
_WORDS_PER_MINUTE = 220
_WORD_MIN, _WORD_MAX = 1_400, 3_000


def _count_prose_colons(body: str) -> int:
    """Count colons that appear in prose — outside fenced code blocks, inline code, and URLs."""
    text = _FENCED_CODE_RE.sub("", body)
    text = _INLINE_CODE_RE.sub("", text)
    text = _URL_RE.sub("", text)
    return text.count(":")


def _prose_word_count(body: str) -> int:
    """Words in prose, excluding fenced code blocks and inline code."""
    text = _FENCED_CODE_RE.sub(" ", body)
    text = _INLINE_CODE_RE.sub(" ", text)
    return len(_WORD_RE.findall(text))


def _count_unlabeled_fences(body: str) -> int:
    """Count opening code fences that carry no language identifier.

    Only opener fences are inspected; the closing ``` of every block is bare by design and
    must not be counted. artifact-slot fences carry the ``artifact-slot`` info string, so
    they are correctly seen as labeled.
    """
    count = 0
    in_fence = False
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped.startswith("```"):
            continue
        if not in_fence:
            if not stripped[3:].strip():
                count += 1
            in_fence = True
        else:
            in_fence = False
    return count


def _count_missing_h2_separators(body: str) -> int:
    """Count ## headings not preceded by a --- separator line."""
    lines = body.splitlines()
    missing = 0
    for i, line in enumerate(lines):
        if not line.startswith("## "):
            continue
        j = i - 1
        while j >= 0 and lines[j].strip() == "":
            j -= 1
        if j < 0 or lines[j].strip() != "---":
            missing += 1
    return missing


def _has_hook(body: str) -> bool:
    """True when prose appears before the first `##` section heading."""
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            return False
        if not stripped or stripped.startswith(("#", "---", "import ", "<", "```")):
            continue
        return True
    return False


def _verdict(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def _build_facts(body: str) -> str:
    """Pre-compute every mechanical check and render it as a [PIPELINE FACTS] block.

    Moving these out of the LLM's hands is the whole point: a small model spends no
    attention re-counting em dashes or words, and a FAIL here can never be argued away —
    so the reviewer focuses entirely on editorial judgment.
    """
    colons = _count_prose_colons(body)
    em_dashes = body.count("—")
    has_h1 = bool(_H1_RE.search(body))
    unlabeled = _count_unlabeled_fences(body)
    sections = len(_H2_RE.findall(body))
    missing_sep = _count_missing_h2_separators(body)
    hook = _has_hook(body)
    words = _prose_word_count(body)
    minutes = round(words / _WORDS_PER_MINUTE, 1)
    words_ok = _WORD_MIN <= words <= _WORD_MAX

    lines = [
        "[PIPELINE FACTS — deterministic checks already done. TRUST these; do not re-scan, "
        "recount, or raise an issue any line marks PASS.]",
        f"- Prose colons: {colons} — {_verdict(colons == 0)} (must be 0)",
        f"- Em dashes: {em_dashes} — {_verdict(em_dashes == 0)} (must be 0)",
        f"- First-level (#) heading in body: {'yes' if has_h1 else 'no'} — "
        f"{_verdict(not has_h1)} (a body with no first-level heading is CORRECT)",
        f"- Code fences missing a language tag: {unlabeled} — {_verdict(unlabeled == 0)}",
        f"- Number of ## sections: {sections} — {_verdict(sections >= 2)} (need at least 2)",
        f"- ## headings missing --- separator: {missing_sep} — {_verdict(missing_sep == 0)} (must be 0)",
        f"- Hook before the first ## heading: {'present' if hook else 'absent'} — "
        f"{_verdict(hook)}",
        f"- Prose word count: {words} (~{minutes} min read) — {_verdict(words_ok)} "
        f"(target {_WORD_MIN}-{_WORD_MAX} words)",
    ]
    return "\n".join(lines) + "\n\n"


class _ReviewResult(BaseModel):
    approved: bool = Field(description="True only when all criteria pass")
    summary: str = Field(description="One-paragraph quality assessment")
    issues: list[str] = Field(
        default_factory=list,
        description="Specific, actionable issues the writer must fix (empty when approved)",
    )
    suggestions: list[str] = Field(
        default_factory=list,
        description="Optional improvement ideas (not blockers)",
    )

    @field_validator("issues", "suggestions", mode="before")
    @classmethod
    def _coerce_items_to_str(cls, v: object) -> list[str]:
        if not isinstance(v, list):
            return v
        result = []
        for item in v:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, dict):
                criterion = item.get("criterion", "")
                description = item.get("description", item.get("fix", ""))
                result.append(f"{criterion}: {description}".strip(": "))
            else:
                result.append(str(item))
        return result


_SYSTEM_HEAD = """\
You are a senior editor and publication reviewer for theJournal at albertoduran.com.

Approve a draft only when it is genuinely ready for humanization. Be rigorous but fair.

The draft begins with a [PIPELINE FACTS] block that already resolves every MECHANICAL check
for you: prose colons, em dashes, first-level (#) headings, code-fence language tags, section
count, hook presence, and word count / reading time. TRUST those verdicts completely. Do not
re-scan the text for them and never raise an issue any fact marks PASS. A body with no
first-level heading is structurally CORRECT;
do not flag or mention the absence of first-level headings.

Your job is the EDITORIAL judgment that code cannot make. Check only these:

E1. Phrasing — no banned or obviously AI-patterned wording, no hollow contrasts, no
    salesperson triads, no fluff openers.
E2. Honesty — no invented facts or uncited claims. Every figure must attach to the correct
    metric. Flag a number tied to the wrong metric (two values swapped, or a value relabeled
    as a different metric) as a blocker.
E3. Cleanliness — no MDX component imports, no JSX components (`<Component>` tags), no
    document metadata blocks or file-level wrappers left in the body. Fenced visual
    blocks (```echart, ```daisyui, ```mermaid) and ```artifact-slot fences are expected;
    leave them.
E4. Substance — does the publication teach, answer, challenge, or walk through something
    genuinely useful, and does it deliver the outline's intent section by section?
E5. Hook quality — does the opening prose (before the first `##`) signal the problem and
    promise the payoff?

The body must already obey theJournal prose style (the mechanical parts are pre-checked in
the facts block); judge the rest against this canon:
"""

_SYSTEM_TAIL = """\

Blockers vs. suggestions:
- issues (blockers): any FAILING pipeline fact, plus any E1-E3 violation or a body that does
  not deliver the outline (an E4 structural miss).
- suggestions (optional): passive voice, paragraph-length wobble (most prose paragraphs land
  between 20 and 80 words), and E4/E5 polish. Never withhold approval on a suggestion alone.

Return `approved: true` only when every blocker is clear. When returning `approved: false`,
list each blocker as a separate, actionable issue.

Return ONLY a valid JSON object — no markdown fences, no extra text — matching this structure:
{{
  "approved": true,
  "summary": "...",
  "issues": [],
  "suggestions": []
}}
"""

_SYSTEM = _SYSTEM_HEAD + style_rules_block() + _SYSTEM_TAIL

_REVIEW_PROMPT = """\
Review this draft publication.

ORIGINAL OUTLINE (reference):
{outline}

DRAFT:
{draft}

CONTEXT:
- Intended tone: {tone}
- Target audience: {audience}
- Review round: {iteration} of {max_iterations}

The [PIPELINE FACTS] block at the top of the draft already settles every mechanical check —
trust it. Judge only the editorial criteria E1-E5. Return ONLY valid JSON matching the schema
in your instructions.
"""


def _build_system(state: PublicationState) -> str:
    """Compose the reviewer system prompt, appending any template fine-tuning.

    Concatenation only — the base prompt contains literal ``{{ }}`` braces, so it must
    never be passed through ``str.format``.
    """
    template = state.get("template_data") or {}
    return apply_finetune(_SYSTEM, template, "reviewer")


def run(state: PublicationState) -> dict:
    """Run mechanical fact checks then editorial review on the current draft.

    Reads: draft, outline, tone, audience, review_iteration, max_iterations,
           template_data
    Writes: review_feedback, review_approved, review_iteration
    """
    iteration = state.get("review_iteration", 0) + 1
    _console.print(
        f"  [yellow]Reviewer:[/yellow] linting mechanics, then judging E1-E5 "
        f"(round {iteration})…"
    )
    llm = build_model(temperature=0.2)
    json_llm = llm.model_copy(update={"format": "json", "validate_model_on_init": False})

    draft_doc = state.get("draft")
    draft_body = draft_doc["body"] if draft_doc else ""

    draft_body_annotated = _build_facts(draft_body) + draft_body

    messages = [
        SystemMessage(content=_build_system(state)),
        HumanMessage(content=_REVIEW_PROMPT.format(
            outline=state.get("outline", "not available"),
            draft=draft_body_annotated,
            tone=state.get("tone", "conversational"),
            audience=state.get("audience", "developers"),
            iteration=iteration,
            max_iterations=state.get("max_iterations", 3),
        )),
    ]

    result: _ReviewResult | None = None
    try:
        for attempt in Retrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=2, max=10),
            reraise=True,
        ):
            with attempt:
                response = json_llm.invoke(messages)
                raw = response.content or response.additional_kwargs.get("reasoning_content", "")
                if not raw.strip():
                    raise ValueError("Model returned empty content for review")
                raw = strip_json_fences(raw)
                try:
                    result = _ReviewResult(**json.loads(raw))
                except (json.JSONDecodeError, ValidationError) as exc:
                    logger.warning("Review parse failed (attempt %d): %s", attempt.retry_state.attempt_number, exc)
                    raise  # triggers retry
    except Exception as exc:
        logger.error("Reviewer: all parse attempts exhausted — force-advancing to humanizer. %s", exc)
        return {
            "errors": [f"Reviewer (round {iteration}): parse failed after 3 attempts — {exc}"],
            "review_approved": True,
            "review_iteration": iteration,
        }

    lines = [f"## Review — Round {iteration}", f"\n**Assessment:** {result.summary}"]

    if result.issues:
        lines.append("\n**Issues (must fix):**")
        lines.extend(f"{i}. {issue}" for i, issue in enumerate(result.issues, 1))

    if result.suggestions:
        lines.append("\n**Suggestions (optional):**")
        lines.extend(f"- {s}" for s in result.suggestions)

    return {
        "review_feedback": "\n".join(lines),
        "review_approved": result.approved,
        "review_iteration": iteration,
    }
