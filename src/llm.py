"""LLM factory and Ollama health-check.

Mirrors the pattern used in langchain-investor/stock_evaluation/llm.py.
"""

from __future__ import annotations

import logging
import re
import sys

import httpx
from langchain_ollama import ChatOllama
from tenacity import Retrying, stop_after_attempt, wait_exponential

from src.config import Config

logger = logging.getLogger(__name__)


def build_model(temperature: float | None = None) -> ChatOllama:
    """Build a ChatOllama instance from environment config.

    Args:
        temperature: Sampling temperature. Pass ``None`` to use the value
            from ``OLLAMA_TEMPERATURE`` (or the 0.7 default). Pass a
            float to override for a specific node (e.g. 0.2 for the
            reviewer, 0.3 for the metadata node).

    Returns:
        A ``ChatOllama`` configured from ``Config``, with per-node
        ``validate_model_on_init=False`` so the startup health-check
        is not duplicated on every node instantiation.
    """
    cfg = Config()
    temp = temperature if temperature is not None else cfg.ollama_temperature
    logger.info("Model: %s @ %s (temp=%.1f)", cfg.ollama_model, cfg.ollama_base_url, temp)
    return ChatOllama(
        model=cfg.ollama_model,
        base_url=cfg.ollama_base_url,
        temperature=temp,
        client_kwargs={"timeout": cfg.ollama_timeout},
        reasoning=False,
        # check_ollama() validates the model once at startup, so skip the per-node
        # HTTP validation round-trip that fires every time a node builds a model.
        validate_model_on_init=False,
    )


def check_ollama() -> None:
    """Verify Ollama is reachable and the configured model is available.

    Called once at pipeline startup. Logs a descriptive error and calls
    ``sys.exit(1)`` on any failure — connection refused, model not pulled,
    or an unexpected HTTP error — so the user knows exactly what to fix
    before a run is attempted.
    """
    cfg = Config()
    base_url = cfg.ollama_base_url
    model = cfg.ollama_model

    try:
        resp = httpx.get(f"{base_url}/api/tags", timeout=5)
        resp.raise_for_status()
        names = [m.get("name", "") for m in resp.json().get("models", [])]
        if not any(n == model or n.startswith(model + ":") for n in names):
            logger.critical("Model '%s' is not available in Ollama.", model)
            logger.critical("Available: %s", ", ".join(names) or "none")
            logger.critical("Run: ollama pull %s", model)
            sys.exit(1)
    except httpx.ConnectError:
        logger.critical("Cannot connect to Ollama at %s. Is it running?", base_url)
        logger.critical("Start with: ollama serve")
        sys.exit(1)
    except Exception as exc:
        logger.critical("Ollama health check failed: %s", exc, exc_info=True)
        sys.exit(1)


# Matches only document-level wrapper fences: ```mdx, ```markdown, or plain ```.
# Content-specific fences (```mermaid, ```python, etc.) are intentionally excluded so
# that visualizer artifacts returned as a bare mermaid/code block are not unwrapped.
_OUTER_FENCE_RE = re.compile(r"^```(?:mdx|markdown)?\s*\n", re.IGNORECASE)


def strip_fences(text: str) -> str:
    """Remove outer MDX/markdown wrapper fences that LLMs add around body responses.

    Strips ` ```mdx `, ` ```markdown `, and bare ` ``` ` when they wrap the entire
    response. Content-specific fences (` ```mermaid `, ` ```python `, etc.) are left
    untouched so visualizer snippets keep their language tag and inner content.

    Args:
        text: Raw LLM response, possibly wrapped in a document-level fence.

    Returns:
        The unwrapped content, or ``text`` unchanged if no outer fence is detected.
    """
    text = text.strip()
    if not _OUTER_FENCE_RE.match(text):
        return text
    first_newline = text.find("\n")
    text = text[first_newline + 1:]
    if text.endswith("```"):
        text = text[: text.rfind("```")].rstrip()
    return text


def strip_json_fences(raw: str) -> str:
    """Remove ` ```json ` or bare ` ``` ` wrapper fences from a JSON response.

    Args:
        raw: Raw LLM response that may be wrapped in a code fence.

    Returns:
        The unwrapped string, ready to pass to ``json.loads()``.
    """
    return raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()


def invoke_with_retry(llm: ChatOllama, messages: list) -> str:
    """Call ``llm.invoke()`` with up to 3 retries and strip outer code fences.

    Args:
        llm: The model instance to call.
        messages: Conversation history (``SystemMessage`` + ``HumanMessage``).

    Returns:
        The model's text response with any document-level fence wrapper removed.

    Raises:
        Exception: Re-raises the last exception after all 3 attempts are exhausted.
    """
    for attempt in Retrying(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    ):
        with attempt:
            return strip_fences(llm.invoke(messages).content)
