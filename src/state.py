from __future__ import annotations

from typing import Optional, List
from typing_extensions import Annotated, TypedDict
import operator

from src.mdx_document import MDXDocument, MDXMetadata


class Artifact(TypedDict):
    id: str               # kebab-case unique identifier
    content: str          # valid MDX syntax — component body, diagram fence, etc.
    import_lines: List[str]  # import statements required by this artifact's content


class InputFile(TypedDict):
    """A single petition source file, as discovered by the loader node."""
    path: str    # absolute path on disk
    name: str    # path relative to the input directory
    chars: int   # length of the loaded (possibly trimmed) content


class PublicationState(TypedDict):
    # ── Input ────────────────────────────────────────────────────────────────
    input_dir: str               # Directory the loader reads petition files from
    petition_content: str        # Combined content of all input files (loader output)
    input_file_paths: List[str]  # Original file paths for reference
    input_files: List[InputFile] # Structured reference to each loaded source file
    template_name: str           # Template used for the Q&A (default: "default")
    template_data: dict          # Full loaded template (loader output)
    run_id: str                  # Zero-padded audit run id (prefixes output + names audit dir)

    # ── User Preferences (set during human Q&A) ──────────────────────────────
    tone: str                    # conversational / technical / formal / narrative
    audience: str                # who will read this
    additional_context: str      # extra constraints or focus areas

    # ── Pipeline Outputs ──────────────────────────────────────────────────────
    followup_questions: Optional[str]     # Interview node output — raw LLM questions block
    outline: Optional[str]                # Agent 1 output
    draft: Optional[MDXDocument]          # Agent 2 output — structured MDX
    humanized: Optional[MDXDocument]      # Agent 4 output — structured MDX
    metadata: Optional[MDXMetadata]       # Metadata node output — designed frontmatter
    final_publication: Optional[str]      # Publisher output — assembled .mdx string

    # ── Artifacts ─────────────────────────────────────────────────────────────
    artifacts: Annotated[List[Artifact], operator.add]

    # ── Review Loop ───────────────────────────────────────────────────────────
    review_feedback: Optional[str]  # Agent 3 issues (returned to Agent 2)
    review_iteration: int           # How many review rounds have completed
    max_iterations: int             # Cap on revision loops (default: 3)
    review_approved: bool           # Agent 3 approved the draft

    # ── Output ────────────────────────────────────────────────────────────────
    output_path: Optional[str]  # Absolute path where the final file was written

    # ── Errors ────────────────────────────────────────────────────────────────
    errors: Annotated[List[str], operator.add]
