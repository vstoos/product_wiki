---
name: wiki-pharma-extraction
description: Use when the user wants to build (or update) a structured evidence wiki vault from regulatory drug-review source documents (FDA reviews, EMA EPARs, Health Canada monographs, PMDA review reports, TGA AusPARs). The skill runs the full pipeline that today is implemented in evidence_wiki/ but with you (Claude) doing the LLM-shaped steps (classify, extract, normalize, verify, resolve, comprehend, link) directly in-conversation — no external API calls. The output is a Markdown vault optimised for Obsidian with strict tier-1/tier-2 separation and audit footers. Trigger phrases include "generate the wiki", "ingest these reviews", "build the apalutamide vault", "extract evidence from this EPAR", "update the wiki with new sources".
---

# Wiki Pharma Extraction

You are operating as the LLM brain of the `evidence_wiki/` pipeline. The pipeline is normally driven by external models via `core/wiki_adapter.py`; this skill replaces that adapter with **you** doing the same per-stage work but inline. Inputs and outputs are unchanged.

## What you are building

A two-tier knowledge base ("vault") for one substance:

- **Tier 1 — Evidence pages** (`evidence/*.md`, `studies/*/*.md`). Raw, verbatim-anchored facts from source documents. Every fact carries a 15-20-word literal snippet, a page reference, and a merge key. Multi-source facts are de-duplicated by deterministic merge keys, never by semantic similarity.
- **Tier 2 — Understanding pages** (`understanding/<substance>-<topic>.md`). LLM-written synthesis paragraphs that link back to Tier 1 via `[[wikilinks]]` only — **never** via `[DOC_ID | type | section | p.N]` direct refs. Tier 2 isolation is enforced by the validator (Rule 2).

Plus: source cards (`sources/<doc-slug>/card.md`), hub indexes (`<substance>_index.md`, `clinical_studies_index.md`, `preclinical_studies_index.md`), conflicts (`conflicts/*.md`), and a quarantine queue (`studies/_review/quarantine.md`) for facts that fail Rule 16 verification.

The vault is Obsidian-friendly: frontmatter metadata, `[[wikilinks]]`, `![[asset embeds]]`, folded `<details>` audit footers.

## When to use this skill

Use it whenever the user wants to ingest one or more regulatory source documents for a substance, OR to update an existing vault with new sources. Specifically:

- New substance: build vault from scratch
- Existing substance: append new docs (idempotent — already-ingested content with unchanged hash is skipped)
- Schema or prompt change: re-extract all docs and rebuild

Do NOT use this skill for general FDA scraping, Streamlit-app reports, or single-document summarization. It's only for the structured wiki path.

## Setup before running

1. Read `references/pipeline-stages.md` end to end. The 9-stage flow is non-negotiable; deviation breaks the validator.
2. Read `references/page-schemas.md` to know the 20 page types, their required fields, and merge keys.
3. Read `references/output-format.md` to know what files to write where, and the exact frontmatter / markdown shape.
4. Read `references/validator-rules.md` to know what to avoid producing (21 rules — Rules 1, 2, 6, 16, 17, 19 are the most common failure modes).
5. Skim `references/conventions.md` — verbatim snippet rules, FOI redaction, sponsor-code slug rules.

Then ask the user for:

- **Substance INN** (e.g. "apalutamide")
- **Source documents path(s)** — usually a directory with `<stem>.hybrid.md` files per source (already converted from PDF by an upstream pipeline)
- **Output vault path** — usually `~/wiki_preview/<Substance>-merged/` or as configured
- **Mode** — `clean` (delete vault first) or `append` (incremental update)

## The 9 stages (you execute them sequentially per doc, then once globally)

For each source document:

1. **Stage 1 — Source staging.** Copy/symlink the source `.hybrid.md` + its `.assets/` into `<vault>/sources/<doc-slug>/`. Compute SHA-256. Skip if hash matches a previous ingest.
2. **Stage 2 — Classification.** Output a single JSON with `source_agency`, `review_type`, `substance_inn`, `product_names`, `document_id`. Use the rules in `references/extraction-protocol.md` §Classification.
3. **Stage 3 — Per-schema extraction.** For each schema in `SchemaRegistry.schemas_for_review_type()`: read the relevant text slice, produce a JSON array of facts conforming to that schema. Phase C schemas (`clinical_study`, `preclinical_study`) follow special blob+fanout rules in `references/extraction-protocol.md` §PhaseC.

After all docs are extracted (pass 1 collects facts in memory):

4. **Stage 5a — Normalize.** Apply dose-unit / duration / date canonicalisers (see `references/conventions.md` §Normalization). Append entries to `normalisation_log.json` for the validator.
5. **Stage 5b — Verify.** For each fact whose `field_name` is in `HIGH_RISK_FIELDS` (Tier 1: `noael`, `glp_status`, `species`, `design`, `population`, `primary_endpoint`, `n_randomized`, `gcp_compliance`; Tier 2: `noel`, `mtd`, `blinding`, `n_completed`, `secondary_endpoints`, `key_results.*`, `safety.*`), check whether the verbatim snippet actually grounds the value. If not, move to quarantine queue.
6. **Stage 6 — Resolver.** Cross-doc study identity. Build alias graph (sponsor_code, nct_id, eudract_id, ctis_id, jrct_id, japicCTI_id, ctri_id, who_id, publication_doi, publication_pmid, nickname, study_report_id, regulatory_dossier_id). Cluster by strong-equivalent alias matches first; for borderline pairs (0.5 ≤ confidence < 0.85) put them in `studies/_review/match_candidates.md` for human review. Rewrite `study_id` on merged facts.

Then (pass 2 writes pages):

7. **Stage 4/7 — Page writing.** Write `evidence/<page_type>.md`, `studies/{clinical,preclinical}/<slug>.md`, source cards under `sources/<doc-slug>/card.md`. See `references/output-format.md` for exact shapes.
8. **Stage 8 — Comprehender + Summary.** Write `understanding/<substance>-<topic>.md` pages that synthesise across Tier 1 evidence. **Tier 2 isolation is non-negotiable**: no `[DOC_ID | ...]` refs, only `[[wikilinks]]`.
9. **Stage 9 — Wiki linking + Hubs + Validator.**
    - WikiLinker: insert `[[evidence/<page>]]`, `[[studies/<type>/<slug>]]` references throughout body text where the alias appears.
    - HubWriter: regenerate `<substance>_index.md`, `clinical_studies_index.md`, `preclinical_studies_index.md`.
    - PageValidator: run all 21 rules. Emit `log.md` with hard fails / errors / warnings. **Hard fails block; errors warn; warnings inform.**

If you complete all 9 stages with zero hard fails, you're done. Report counts: documents_processed, pages_created, pages_updated, links_inserted, quarantined, match_candidates, validator findings.

## Key invariants (you will violate these by accident if you don't internalise them)

- **Every Tier-1 fact carries a 15-20-word verbatim snippet.** Hard-fail floor is 8 words. The snippet must literally appear in the source doc text. No paraphrasing. No summary.
- **Verbatim snippets are PER-FIELD.** When extracting a study record with `noael`, `glp_status`, `population`, etc. — each field gets its OWN snippet in a `verbatim_anchors` dict. Do NOT reuse the same headline snippet for every field; that's exactly the bug that quarantined 132 facts in May 2026.
- **Merge keys are EXPLICIT and SCHEMA-DECLARED.** Two facts merge only when their `merge_key_fields` match exactly. No semantic similarity. No fuzzy matching. The merge key for `solubility` is e.g. `(medium, ph, condition)` — see each schema.
- **Tier 2 pages have ZERO `[DOC_ID | ...]` refs.** Only `[[wikilinks]]` to Tier 1. Rule 2 hard-fails this.
- **Page slugs use the canonical study identifier.** For studies, prefer NCT id, then EudraCT, then sponsor_code, then content-hashed fallback. Phase C resolver decides the canonical slug; don't second-guess it from extraction time.
- **FOI redactions.** When you see `(b)(4)` or similar redaction markers, replace with literal `[CBI — FOI redacted]` in the value. Don't try to guess the redacted content.
- **Page anchors.** Every fact's `source.page` is the PDF page number from the HTML anchor `<a id="pN"></a>` in the `.hybrid.md` source. If absent, use `0` (Rule 20 will warn but not fail). Never invent page numbers.

## Output report format

After the run, give the user a concise summary in this exact shape:

```
## Wiki ingest summary (<substance>)

- Documents processed: N (of M source files)
- Documents skipped (hash unchanged): K
- Documents failed: F (with reasons)

### Pages
- Evidence: created A, updated B, staled C
- Studies: A clinical, B preclinical
- Understanding: regenerated N
- Source cards: written A, skipped B

### Resolver
- Clusters: N studies (was M before merging)
- Match candidates pending review: K (in studies/_review/match_candidates.md)
- Quarantined facts (Rule 16): Q (in studies/_review/quarantine.md)

### Validator
- Hard fails: F
- Errors: E
- Warnings: W
- (List the top 5 of each, by frequency)

### Next steps
- (If any hard fails) Review the listed pages; the run is incomplete.
- (If match candidates) Open studies/_review/match_candidates.md and set Decision column.
- (Otherwise) Vault is ready for Obsidian.
```

## What NOT to do

- Don't call any external LLM API. You ARE the LLM. The whole point of this skill is to remove the `RotatingLLMAdapter` round-trip.
- Don't paraphrase verbatim snippets to "clean them up". They must match the source text exactly.
- Don't merge studies semantically. Only via explicit alias overlap (resolver Stage 6 has rules).
- Don't fabricate fields the schema doesn't declare. If `clinical_study` schema doesn't have `protocol_version`, you can't add it.
- Don't write Tier 2 understanding pages until Tier 1 evidence pages exist. They reference Tier 1 by `[[wikilink]]`.
- Don't skip the validator. The vault is broken if validator hard-fails are ignored.
- Don't write to the source docs directory. All writes go under the output vault path.

## Resources

References (read these as you work):

- `references/pipeline-stages.md` — full 9-stage detail with what each stage consumes and produces
- `references/page-schemas.md` — all 20 page types with fields and merge keys
- `references/extraction-protocol.md` — exactly how to do classify + extract + verify + resolve as Claude
- `references/validator-rules.md` — all 21 rules with examples of what passes and what fails
- `references/output-format.md` — frontmatter shape, markdown templates, vault directory layout
- `references/conventions.md` — verbatim rules, FOI redaction, slug rules, normalization tables

The original Python implementation (for cross-reference if something is unclear): `/home/vstoos/projects/get_reports/evidence_wiki/`. Do not run any of it; only read it to understand the contract.
