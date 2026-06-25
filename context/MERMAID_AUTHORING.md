# Mermaid Authoring Rules (distilled)

Concise authoring rules for generating ONE inline Mermaid diagram. Distilled from the
`design-doc-mermaid` skill's syntax guide and troubleshooting catalogue — the full skill
(`skills/design-doc-mermaid/`) is for humans navigating diagram types on demand; this doc is
the focused payload for single-diagram generation.

## Output

- Emit exactly one fenced block: ` ```mermaid ` … ` ``` `. Nothing before or after it.
- First line is the diagram type: `flowchart TD`, `flowchart LR`, `sequenceDiagram`,
  `stateDiagram-v2`, `erDiagram`, `classDiagram`, `gantt`, or `mindmap`.
- One statement per line. NEVER chain statements with `;` on one line.
- Do NOT add `%%{init: ...}%%` theme blocks — the site owns Mermaid theming.
- One concept per diagram. Keep node labels ≤ 4 words; move detail into prose.

## Label quoting — the #1 cause of parse failures

If a node or edge label contains ANY of these characters, wrap the WHOLE label in double
quotes: `( ) [ ] { } : ; , # % @ & | < > $ " \`

```
✓  A["Low Model Agreement (22.25)"]
✗  A[Low Model Agreement (22.25)]        ← ( ) breaks the parser

✓  P -->|"Weight: 80%"| Q
✗  P -->|Weight: 80%| Q                   ← : and % break the edge label
```

Reserved words used as a node id or bare label must also be quoted: `end`, `default`,
`class`, `style`, `graph`, `subgraph`, `click`, `call`, `link`, `state`.

```
✓  start --> "end"
✗  start --> end                          ← `end` is reserved
```

## Edges and structure

- Flowchart/graph arrows are `-->` (or `---`, `-.->`, `==>`). Never `->`.
- Define each edge exactly once. Do not repeat `A --> B` both at top level and in a subgraph.
- Every `subgraph` must be closed with `end` on its own line.
- Sequence messages need a colon before the text: `Alice->>Bob: Request` (the colon here is
  syntax, not label content, so it is not quoted).

## Minimal templates

Flowchart (decision flow):
```
flowchart TD
    A["Start"] --> B{"Valid?"}
    B -->|"Yes"| C["Process"]
    B -->|"No"| D["Reject"]
```

Sequence:
```
sequenceDiagram
    participant U as User
    participant S as Service
    U->>S: Request data
    S-->>U: Response
```

State:
```
stateDiagram-v2
    [*] --> Idle
    Idle --> Running: start
    Running --> [*]: done
```

ER:
```
erDiagram
    CUSTOMER ||--o{ ORDER : places
    ORDER ||--|{ LINE_ITEM : contains
```

## Self-check before output

1. Every label with a special character is wrapped in double quotes.
2. One statement per line, no `;` chaining.
3. No `%%{init}%%` block. No outer markdown fence around the mermaid fence.
4. Arrows are `-->` not `->`; every `subgraph` has a matching `end`.
