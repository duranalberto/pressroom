"""Mermaid sub-agent — generates a fenced Mermaid code block from a creation prompt.

Public interface:
    render(artifact_id, context, llm) -> str

The returned string is a single fenced ```mermaid ... ``` block with no imports.
The orchestrator (__init__.py) owns import-splitting, validation, and Artifact assembly.

Prompt strategy: load the distilled `context/MERMAID_AUTHORING.md` (~120 lines). The full
per-type guides total ~4,500 lines and reliably time out Ollama, so they are intentionally
not loaded.
"""

from __future__ import annotations

import re

from langchain_core.messages import HumanMessage, SystemMessage

from src.docs_loader import load_doc
from src.llm import invoke_with_retry

# ── Deterministic sanitizer ───────────────────────────────────────────────────
# A safety net for the two errors small models make most often in Mermaid, applied
# to every generated diagram so a render never fails on them:
#   1. labels containing special characters that must be wrapped in double quotes,
#   2. multiple statements chained on one line with `;` (a hard syntax error).

_FENCE_RE = re.compile(r"^[ \t]*```")
# Characters that force a Mermaid label to be wrapped in double quotes.
_RISKY = set("()[]{}:;,#%@&|<>$")
_SQUARE_RE = re.compile(r"\[([^\[\]]*)\]")
_CURLY_RE = re.compile(r"\{([^{}]*)\}")
_EDGE_RE = re.compile(r"\|([^|]*)\|")


def _needs_quote(content: str) -> bool:
    """True when a label's text must be double-quoted to parse safely."""
    text = content.strip()
    if not text:
        return False
    if text.startswith('"') and text.endswith('"'):
        return False  # already quoted — leave it
    return any(ch in _RISKY for ch in content)


def _quote_delim(stmt: str, pattern: re.Pattern, open_ch: str, close_ch: str) -> str:
    def repl(match: re.Match) -> str:
        content = match.group(1)
        if _needs_quote(content):
            return f'{open_ch}"{content}"{close_ch}'
        return match.group(0)

    return pattern.sub(repl, stmt)


def _quote_labels(stmt: str) -> str:
    """Wrap node ([],{}) and edge (|...|) labels in quotes when they carry risky chars."""
    stmt = _quote_delim(stmt, _SQUARE_RE, "[", "]")
    stmt = _quote_delim(stmt, _CURLY_RE, "{", "}")
    stmt = _quote_delim(stmt, _EDGE_RE, "|", "|")
    return stmt


def _dechain(line: str) -> list[str]:
    """Split one line into separate statements at ``;`` outside quoted strings."""
    if ";" not in line:
        return [line]
    pieces: list[str] = []
    buf: list[str] = []
    in_quote = False
    for ch in line:
        if ch == '"':
            in_quote = not in_quote
            buf.append(ch)
        elif ch == ";" and not in_quote:
            pieces.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    pieces.append("".join(buf))
    return [p.strip() for p in pieces if p.strip()]


def sanitize(src: str) -> str:
    """Deterministically fix the two recurring Mermaid model errors.

    Quotes any node/edge label containing special characters, and breaks
    ``;``-chained statements onto their own lines. Fence lines (```…) pass
    through untouched, and ``;`` inside a quoted label is never split. Idempotent.

    Args:
        src: Raw Mermaid source (optionally wrapped in a ```mermaid fence).

    Returns:
        Sanitized Mermaid source with the same fence structure.
    """
    out: list[str] = []
    for line in src.split("\n"):
        if _FENCE_RE.match(line):
            out.append(line)
            continue
        for stmt in _dechain(line):
            out.append(_quote_labels(stmt))
    return "\n".join(out)

_SYSTEM = """\
You are a Mermaid diagram specialist for theJournal at albertoduran.com.

Your only job: produce a single, valid fenced Mermaid code block for the diagram
described in the creation prompt.

## MERMAID AUTHORING RULES

{mermaid_doc}

ABSOLUTE RULES:
- Output ONLY a fenced code block: ```mermaid\\n<diagram>\\n```  — no prose, no imports,
  no outer markdown fence.
- One statement per line. A semicolon (;) outside a quoted string is a hard syntax error
  that breaks the diagram — NEVER chain statements with ; on one line.
- If a node or edge label contains ANY of these characters: ( ) [ ] {{ }} : ; , # % @ & | < > $
  then wrap the ENTIRE label in double quotes. No exceptions.
  Correct:  A["Price ($149.91)"]   X -->|"Step: yes"| Y
  Wrong:    A[Price ($149.91)]     X -->|Step: yes| Y
- Do NOT add %%{{init: ...}}%% theme blocks — the site owns Mermaid theming.
- Keep labels short (≤4 words). One concept per diagram.
"""

_PROMPT = """\
Create the Mermaid diagram for this artifact.

Artifact id: {artifact_id}

Creation prompt:
{context}

Output ONLY the fenced Mermaid code block. Nothing else.
"""


def render(artifact_id: str, context: str, llm) -> str:
    """Generate a fenced Mermaid code block from a creation prompt.

    Args:
        artifact_id: Kebab-case slot id (used for error attribution).
        context: Natural-language creation brief written by the outline agent,
            starting with the diagram type (e.g. ``"Mermaid flowchart TD …"``).
        llm: Base ``ChatOllama`` instance; copied with ``temperature=0.3``.

    Returns:
        A single ` ```mermaid … ``` ` fenced block with no imports.
    """
    cold_llm = llm.model_copy(update={"temperature": 0.3, "validate_model_on_init": False})
    system = _SYSTEM.format(mermaid_doc=load_doc("MERMAID_AUTHORING.md"))
    raw = invoke_with_retry(cold_llm, [
        SystemMessage(content=system),
        HumanMessage(content=_PROMPT.format(
            artifact_id=artifact_id,
            context=context.strip(),
        )),
    ])
    # Deterministic safety net for the two errors small models make most often.
    return sanitize(raw)
