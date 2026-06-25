"""Single source of truth for theJournal body prose-style rules.

Three agents enforce the same prose canon — the writer (as constraints it must obey), the
reviewer (as criteria it checks), and the humanizer (as output rules it preserves). The
wording used to live inline in all three, hand-maintained, so the copies drifted. When two
copies disagree, the writer and reviewer fight and the review loop never converges.

Keeping the canon here, imported by every body-producing agent, makes that class of
contradiction structurally impossible. The rules are phrased as plain directives so they
read correctly whether framed as "you must" (writer/humanizer) or "check that" (reviewer).
"""

from __future__ import annotations

# The prose rules every body-producing agent must agree on. Mechanical ones (em dashes,
# colons) are ALSO checked deterministically downstream, but stating them here keeps each
# agent's intent aligned with the deterministic enforcement.
BODY_STYLE_RULES: tuple[str, ...] = (
    "No em dashes (—). Use a comma, a period, or parentheses instead.",
    "No colons in prose. Colons are allowed only in code blocks, URLs, and technical syntax.",
    "No hollow contrasts, no salesperson triads, no filler openers.",
    "No promotional or advertisement-like phrasing.",
    "Never invent facts, measurements, claims, or citations.",
)


def style_rules_block(bullet: str = "- ") -> str:
    """Render the shared prose-style canon as a bullet list for a system prompt.

    Args:
        bullet: Prefix for each rule line. Defaults to ``"- "`` (Markdown
            list item). Pass ``""`` for a plain numbered list or any other
            prefix the prompt format requires.

    Returns:
        Multi-line string with one rule per line, ready to interpolate into
        a ``{style_rules}`` placeholder.
    """
    return "\n".join(f"{bullet}{rule}" for rule in BODY_STYLE_RULES)
