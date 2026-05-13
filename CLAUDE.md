# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A **skill-driven evidence wiki** for generic-pharma R&D. The repo holds two things only:

1. **`skills/`** — three Anthropic-style skills (`SKILL.md` + `references/`) that codify a multi-stage agentic pipeline for one INN (international non-proprietary name).
2. **`<substance>/`** folders (e.g. `apalutamide/`) — the working dataset for that pipeline: per-agency caches of raw regulatory documents, their extracted markdown, and (eventually) the Obsidian-compatible wiki vault.

There is **no Python, no build, no test runner here**. The Python reference implementation lives in a parallel project (`get_reports/`) outside this directory; the skills describe that contract well enough for Claude to execute the workflow inline using its tools (`WebFetch`, `Bash` + `curl`, `Read`/`Write`/`Edit`). When a skill says "the Python implementation lives in `core/*_tools.py`", treat that as a cross-reference, not something to run.

## The pipeline (three skills, executed in order)

```
reg-doc-fetching        pdf-doc-extraction         wiki-pharma-extraction
   (skill 1)               (skill 2)                  (skill 3)
       │                       │                          │
       ▼                       ▼                          ▼
  raw PDFs/HTML          <stem>.hybrid.md           Obsidian vault
  per agency             + <stem>.assets/           (Tier 1 evidence
  per substance          (anchored markdown,         + Tier 2 synthesis)
                          inline tables, figures)
```

Skill picker:

| User intent | Skill |
|---|---|
| "Fetch FDA/EMA/HC/PMDA/TGA docs for X" | `reg-doc-fetching` |
| "Convert these PDFs to markdown / extract figures / OCR" | `pdf-doc-extraction` |
| "Build/update the wiki for X from these sources" | `wiki-pharma-extraction` |

When the user gives an end-to-end task ("build the wiki for roxadustat from scratch"), invoke them sequentially and emit the per-stage summary report each skill defines.

## The big architectural ideas

**Karpathy-style memory, not RAG.** The wiki is the agent's updateable long-term memory: plain Obsidian markdown, deterministic merge keys, wikilinks. No vector store. Future skills should write *into* this vault, not bolt a retriever on top.

**Two-tier vault — Tier 1 isolation is the load-bearing invariant.**
- **Tier 1** (`evidence/*.md`, `studies/*/*.md`): facts only. Every fact carries `[DOC_ID | review_type | section | p.N]` + a 15–20-word verbatim snippet that literally appears in the source. This is what makes the vault auditable.
- **Tier 2** (`understanding/<substance>-<topic>.md`): LLM synthesis. Contains **zero** `[DOC_ID | ...]` brackets — only `[[wikilinks]]` back to Tier 1. Validator Rule 2 hard-fails any violation. This separation is non-negotiable; don't shortcut it.

**ALCOA in practice.** Every artifact carries provenance: the fetch skill writes `<filename>.meta.json` (URL, retrieval_date, SHA-256); the extractor writes `<stem>.meta.json` (engines used, scanned-page count, cost); the wiki writes per-fact verbatim anchors + page numbers. Don't strip these. Don't paraphrase verbatims to "clean them up" — that silently breaks audit.

**Per-substance, per-agency on-disk layout.** Every dataset folder follows the same shape:

```
<substance>/
├── FDA/      # NDA reviews, PSG, supplement letters+labels, DailyMed
├── EMA/      # EPAR Assessment / Variation / Extension / Product Info
├── HC/       # Product Monograph, SBD, Regulatory Decision Summary
├── PMDA/     # English review reports
└── TGA/      # AusPAR + PI
```

Inside each agency dir: one file per document (`*.pdf` or `*.html`), the same stem repeated as `*.md` (the `.hybrid.md` extraction output, written next to its PDF in this repo's flat layout — note the upstream Python uses sidecar dirs), and a `*.assets/` directory holding figure/table PNGs and `ir.json`. The wiki vault for the substance lives separately (typically `~/wiki_preview/<Substance>-merged/`, configurable).

## Conventions Claude must honor

- **Page anchors are the citation contract.** Every page in a `.hybrid.md` starts with `<a id="pN"></a>` followed by `## Page N`. Tier 1 facts cite `p.N` against this. Don't write extraction output without these anchors — downstream citations break silently.
- **Inline tables = HTML `<table>`**, not pipe-tables (regulatory tables routinely have rowspans / nested headers).
- **Preserve Unicode literally.** `°`, `µ`, `±`, `≤`, `≥`, `–`, `—`, `→`, and especially `☒` / `☐` checkboxes in EMA PSG fasting/fed and BCS tables. Never convert to true/false.
- **FOI/CBI redactions.** `(b)(4)` → value becomes `[CBI — FOI redacted]`; keep the verbatim showing the redaction marker as-is.
- **Cache aggressively, refetch never.** Most agencies throttle. Honour file-already-on-disk; only re-download when the user explicitly says force-refresh.
- **Don't conflate brand and INN.** `Erleada` is the brand of `apalutamide`; resolve through INN first, then fall back to brand on agency endpoints that index either.

## Model selection (read every session)

Use the cheapest / fastest model that gets the job done.

- **Default text inference** (page classification, engine routing, caption-or-skip decisions): **Haiku**.
- **OCR / vision captions:** Gemini API round-robin on Gemma 4 models (free tier). Local 2B-class models on RTX 3090 are the planned swap-in — same skill, different `--engine` flag.
- **Heavy synthesis** (Tier 2 wiki narratives only): Sonnet sparingly. Never Opus by default.
- **Escalate** only after the cheap path produces clearly wrong output twice, or on explicit user ask.

Each skill's `SKILL.md` carries its own model-selection block at the top — when you invoke a skill, that block is the local-source-of-truth and overrides this default.

## Skill structure (the pattern)

Each skill is a self-contained folder:

```
skills/<skill-name>/
├── SKILL.md           # model-agnostic prose contract, model-selection block at top
├── README.md          # install + invocation
├── requirements.txt   # system Python deps (no in-repo venv)
├── references/        # deep docs loaded only when needed
└── scripts/           # small CLI tools the agent invokes via Bash
```

Tools are language-agnostic in principle (Python first because of the PDF/vision ecosystem; a future skill might wrap a Rust or C binary, like `be-sample-size` does). What matters is they're invokable as plain CLI commands and emit JSON to stdout / files to disk — so any agent (Claude, Hermes, Pi) can use them, not just Claude Code.

## What this repo is NOT for

- **No clinical-submission use.** Data is R&D-only; not for protocol writing, regulatory submission, or any GxP-binding purpose. Output is "verifiable by a human expert/auditor" — that is the bar, not "regulatory-grade".
- **No external LLM calls from inside the wiki skill.** The whole point of `wiki-pharma-extraction` is that **Claude IS the LLM** — it replaces the `RotatingLLMAdapter` round-trip used by the parent Python project. Don't add API calls; do the per-stage work inline.
- **No editing source documents.** All writes go to extraction outputs or the vault. The raw PDFs/HTML in `<substance>/<agency>/` are immutable references.

## Sister project

A separate workflow with a Streamlit human-in-the-loop UI ("get_reports") implements the same pipeline in Python — that codebase is what the skills' "core/*_tools.py" and "evidence_wiki/" references point at. Read it for ground-truth on edge cases, but don't try to invoke it from here.

## Working with Windows / PowerShell

Default shell is PowerShell; the `Bash` tool is also available for POSIX commands.
