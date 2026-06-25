from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent.parent


@dataclass
class Config:
    """Pipeline configuration resolved from environment variables and defaults.

    Every field reads from an environment variable (loaded by ``python-dotenv``
    at import time) and falls back to a hardcoded default. Instantiate with
    ``Config()`` — all fields have defaults, so no arguments are required.
    """
    ollama_model: str = field(
        default_factory=lambda: os.environ.get("OLLAMA_MODEL", "llama3.2:3b")
    )
    ollama_base_url: str = field(
        default_factory=lambda: os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    )
    ollama_timeout: int = field(
        default_factory=lambda: int(os.environ.get("OLLAMA_TIMEOUT", "600"))
    )
    ollama_temperature: float = field(
        default_factory=lambda: float(os.environ.get("OLLAMA_TEMPERATURE", "0.7"))
    )
    docs_dir: Path = field(default_factory=lambda: BASE_DIR / "context")
    templates_dir: Path = field(default_factory=lambda: BASE_DIR / "templates")
    input_dir: Path = field(default_factory=lambda: BASE_DIR / "input")
    output_dir: Path = field(default_factory=lambda: BASE_DIR / "output")
