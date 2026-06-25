# Audit trail

Every pipeline run leaves a reproducible paper trail so a finished publication can be
traced back to exactly what each intermediary agent produced. This is the first place to
look when a published `.mdx` has a defect and you need to know **which step introduced it**.

## How runs are identified

Each run is allocated a monotonically incrementing numeric id, zero-padded to four digits
(`0001`, `0002`, …). The counter lives in `.run_id` at the repo root and is **git-ignored**
— it is per-checkout and never committed, so ids are local to your machine.

- Allocation happens once, at the start of `python main.py run`, in `src/audit.py`
  (`allocate_run_id`). A missing or corrupt counter resets to `1`.
- The id is stored in `state["run_id"]` and threaded through the whole run.
- It prefixes the final publication filename and names the run's audit directory.

## Layout

```
.run_id                                          ← git-ignored counter (repo root)
output/
  0042-2026-06-28-salesforce-is-it-a-buy.mdx     ← final publication, id-prefixed
  pipeline_state.json                            ← latest-run snapshot (convenience copy)
  audit/
    0042/                                        ← this run's audit directory
      pipeline_state.json                        ← full state snapshot for run 0042
      outline.md                                 ← outline designer output
      writer.md                                  ← writer draft body (last round)
      reviewer.md                                ← reviewer verdict (last round)
      humanizer.md                               ← humanizer output body
```

## What each file contains

| File | Source | Notes |
|---|---|---|
| `outline.md` | `state["outline"]` | The outline designer's plan, verbatim. |
| `writer.md` | `draft["body"]` | The draft **body only** — no frontmatter, no imports. |
| `reviewer.md` | `state["review_feedback"]` | The reviewer's assessment, issues, and suggestions. |
| `humanizer.md` | `humanized["body"]` | The humanized **body only** — what the publisher ships. |
| `pipeline_state.json` | full graph state | Every field, including per-round review history. |

All four step files are saved **without frontmatter or imports**, so they diff cleanly
against each other and across runs.

### The review loop caveat

The graph loops `writer ⇄ reviewer` up to `max_iterations` times. `writer.md` and
`reviewer.md` are overwritten each round, so on disk they hold the **last** round only.
When you need earlier rounds, read `pipeline_state.json` — `review_iteration` tells you how
many rounds ran and `review_feedback` carries the final feedback. (Per-round body history
on disk was intentionally left out to keep one file per step.)

## Recipe: trace a defect back to its source

1. Note the leading id on the bad file, e.g. `0042-2026-06-28-….mdx`.
2. Open `output/audit/0042/`.
3. Read the step files in pipeline order and find where the defect first appears:
   - `outline.md` — was the structure/claim wrong from the plan?
   - `writer.md` — did the writer introduce it while drafting?
   - `reviewer.md` — did the reviewer catch it, miss it, or approve anyway?
   - `humanizer.md` — did the humanization pass introduce or fail to remove it?
4. The first file where the defect appears is the agent to investigate. If it is present in
   `humanizer.md` but not `writer.md`, the humanizer is the culprit; if it is in `writer.md`
   already, check whether `reviewer.md` should have flagged it.
5. For anything round-specific (e.g. "the reviewer flagged it in round 1 but it survived"),
   open `pipeline_state.json` for the full state.

## Implementation pointers

- Run id + step snapshots: `src/audit.py` (`allocate_run_id`, `format_run_id`, `run_dir`,
  `write_step_body`).
- Wiring (allocation, per-node snapshots): `main.py` (`_save_audit_step`, the stream loops).
- Filename prefixing: `src/agents/publisher.py` (`_save`).
- Tests: `tests/test_audit.py`, plus `_save_audit_step` cases in `tests/test_main.py`.
