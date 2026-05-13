# Pipeline Stages

The wiki ingest is a two-pass pipeline over a list of source documents for one substance. Each stage has a strict contract — input, output, and idempotency rules.

## Pass 1 — Per-document collection (Stages 1, 2, 3)

These run once per source document. Facts accumulate in memory; nothing is written to disk yet except staged source files.

### Stage 1 — Source staging

**Input:** path to `<stem>.hybrid.md` (a single source doc, already PDF-extracted), optionally with a sibling `.assets/` directory containing figure PNGs.

**Output:**
- `<vault>/sources/<doc-slug>/source.md` (copy or symlink of the .hybrid.md)
- `<vault>/sources/<doc-slug>/assets/*.png` (copy of the .assets/ children)
- `<vault>/sources/<doc-slug>/source_hash.txt` (SHA-256 of source.md content)
- `<vault>/.wiki_state.json` updated with `{<doc-path>: {sha256, mtime, last_ingested}}`

**Doc slug** = filename stem, lowercased, non-alphanumeric → `-`, trimmed.

**Idempotency:** if `.wiki_state.json` already has this doc with matching SHA-256, skip the whole document (return early — no extraction, no page writes).

### Stage 2 — Classification

**Input:** the staged `source.md` text (full or first 30K chars — head usually identifies the doc).

**Output:** a single JSON object:

```json
{
  "source_agency": "FDA",
  "review_type": "Multidisciplinary Review",
  "substance_inn": "apalutamide",
  "product_names": ["Erleada"],
  "document_id": "NDA-210951"
}
```

**Allowed values for `source_agency`:** `FDA`, `EMA`, `HC` (Health Canada), `PMDA`, `TGA`, `HMA` (Heads of Medicines Agencies via MRI/DCP), `WHO`.

**Allowed values for `review_type`** (sample, not exhaustive):
- FDA: `Approval Letter`, `Chemistry/Product Quality Review`, `Clinical Pharmacology Review`, `Statistical Review`, `Pharmacology/Toxicology Review`, `Multidisciplinary Review`, `Integrated Review — Pharmacology/Toxicology`, `Risk Assessment Review`, `Product-Specific Guidance`, `Labeling`, `Other`
- EMA: `EPAR Assessment`, `EPAR Assessment — Variation`, `EPAR Assessment — Extension`, `EPAR Product Information`, `SmPC`, `All Authorised Presentations`, `Other`
- HC: `Product Monograph`, `Summary Basis of Decision`, `Regulatory Decision Summary`
- PMDA: `Review Report`
- TGA: `AusPAR`, `PI` (Product Information)

If you can't determine, use `Other` for review_type, but you MUST set source_agency to one of the allowed values.

**Filename heuristics:** if the filename contains `ChemR`, classify as `Chemistry/Product Quality Review`. `MultidisciplineR` → `Multidisciplinary Review`. `RiskR` → `Risk Assessment Review`. `PSG_` → `Product-Specific Guidance`. `Approv` → `Approval Letter`. EMA filenames usually have `EPAR` in them and Variation/Extension as suffix.

### Stage 3 — Per-schema extraction

**Input:** classification + source text.

**Output:** a dict `{page_type: [list of ExtractedFact JSON objects]}`. For each page_type whose schema is in `schemas_for_review_type(classification.review_type)`, extract a list of facts matching that schema.

**Per-fact shape:**

```json
{
  "field": "solubility_aqueous",
  "value": "0.012 mg/mL",
  "source": {
    "doc_id": "NDA-210951",
    "review_type": "Chemistry/Product Quality Review",
    "section": "Drug Substance",
    "page": 23,
    "asset": null
  },
  "verbatim": "Apalutamide is practically insoluble in water (0.012 mg/mL at pH 7.4 at 37 °C).",
  "confidence": "high",
  "has_verbatim": true,
  "merge_key_fields": {"medium": "water", "ph": "7.4", "temperature": "37C"},
  "extra_fields": {},
  "asset_ref": null
}
```

See `extraction-protocol.md` for the exact instruction template Claude follows per schema.

**Important:**
- `verbatim` must be 15-20 words literally from the source (8 words minimum, hard-fail below)
- `merge_key_fields` must match the schema's declared merge key tuple exactly
- For Phase C schemas (`clinical_study`, `preclinical_study`), the extractor returns a blob record that gets fanned out in a post-step into per-field facts each with its own `verbatim_anchors[field_name]` — see `extraction-protocol.md` §PhaseC

## Pass 1.5 — Cross-doc operations (Stages 5a, 5b, 6)

These run after ALL docs are extracted, before any pages are written. Operate on the in-memory pool of facts.

### Stage 5a — Normalize

For every fact, apply canonical-form conversions:

- **Dose units:** mg → mg, ug → µg, mcg → µg, etc. (see `conventions.md` §DoseUnits)
- **Duration:** "1 month" → "30 days", "3 weeks" → "21 days" (only when explicit; "subchronic" stays as-is)
- **Dates:** any format → ISO `YYYY-MM-DD`

Write each transformation to `<vault>/.wiki_state/normalisation_log.json`:

```json
{
  "study_id": "...",
  "source_doc_id": "NDA-210951",
  "field": "dose",
  "before": "240 mg/d",
  "after": "240 mg/day",
  "rule": "dose_unit_canonical"
}
```

The log feeds Validator Rule 18 (drift detection).

### Stage 5b — High-risk verifier

For every fact whose `field_name` (or `field` path for nested) is in:

- **Tier 1 (always verified):** `noael`, `glp_status`, `species`, `design`, `population`, `primary_endpoint`, `n_randomized`, `gcp_compliance`
- **Tier 2 (verified if budget remains):** `noel`, `mtd`, `blinding`, `n_completed`, `secondary_endpoints`, `key_results.difference_ci`, `key_results.gmr`, `key_results.p_value`, `safety.teae_pct`, `safety.sae_pct`, `safety.deaths`

Check: does `fact.verbatim` literally ground the claim in `fact.value`? Acceptable groundings:
- Direct mention: "NOAEL of 10 mg/kg/day" supports value=`10 mg/kg/day`, field=`noael`
- Synonymous mention: "no observed adverse effect level was 10 mg/kg" supports same
- Tabular reference: "Table 4 shows NOAEL 10 mg/kg" supports same

Not grounded:
- Different value: verbatim says "100 mg/kg" but value claims "10 mg/kg"
- Topic mismatch: verbatim discusses MTD or LD50 but value field is `noael`
- Generic: verbatim is just the section header with no specific number

If not grounded, move to `<vault>/studies/_review/quarantine.md` with columns: Rule | Field | Value | Source | Page | Verbatim | Reason. Do NOT write to the evidence page.

Max verifications per study: 12 calls (tier 1 first, then tier 2 if budget remains).

### Stage 6 — Study resolver (Phase C only)

For `clinical_study` and `preclinical_study` facts only.

**Build alias graph.** For each study, extract all of: `sponsor_code`, `nct_id`, `eudract_id`, `ctis_id`, `jrct_id`, `japicCTI_id`, `ctri_id`, `who_id`, `publication_doi`, `publication_pmid`, `nickname`, `study_report_id`, `regulatory_dossier_id`. Add edges between studies sharing any non-stub alias.

**Sponsor-code variants.** Treat as equivalent: `56021927PCR3002` ↔ `PCR3002` (extension match if ≥6 alphanum overlap). Also generate suffix variants: `56021927PCR1018` → `PCR1018`, `1018`. If a suffix variant collides between two studies, DROP the variant from the alias graph (it's ambiguous).

**Cluster.** Union-find on the alias graph. Each connected component is one canonical study.

**Borderline pairs.** For pairs that DON'T share an alias but look structurally similar (same trial nickname OR same phase + same design + same population summary), assign a confidence score 0-1. If 0.85+ → auto-merge. If 0.5-0.85 → write to `studies/_review/match_candidates.md` with Decision column blank for user. If <0.5 → don't merge.

**Canonical slug.** For each cluster, pick the most stable id (NCT > EudraCT > sponsor_code > content-hashed). Slug = `<id>` lowercased, non-alphanumeric → `-`.

**Rewrite.** Update every fact's `study_id` field to the canonical slug, in-memory.

## Pass 2 — Page writing (Stages 4, 7, 8, 9)

### Stage 4/7 — Evidence pages, source cards, studies pages

For each `page_type` with at least one fact:
- Write `<vault>/evidence/<page_type>.md` (or update if it exists)
- Compute frontmatter: `confidence`, `source_count`, `last_updated`, `staled` (any false)
- Body: render each fact as a bullet with `[[<source-card-slug>]]` link and inline source ref `[DOC_ID | type | section | p.N]`

For each source doc:
- Write `<vault>/sources/<doc-slug>/card.md` with metadata (sponsor, approval date, indication, retrieval_url, retrieval_date, retrieval_tool, source_doc_sha256)

For each canonical study (Phase C):
- Write `<vault>/studies/{clinical|preclinical}/<slug>.md`
- Include aliases dict in frontmatter
- Section per source-doc with the doc's contribution + audit footer in folded `<details>`
- Include "Related evidence-layer data" section pointing at non-Phase-C facts that share the same `study_id`

### Stage 8 — Comprehender (understanding pages)

For each `understanding/<substance>-<topic>.md` topic (one per page_type that has cross-cuttable narrative — see `output-format.md` §UnderstandingTopics):
- Read all Tier 1 evidence pages relevant to the topic
- Synthesise a 200-500 word narrative paragraph
- Reference Tier 1 only via `[[wikilinks]]` (e.g. `[[evidence/solubility]]`, `[[studies/clinical/spartan]]`)
- **NO `[DOC_ID | type | section | p.N]` refs**. Rule 2 hard-fails on this.
- If you cite a specific number, link to the evidence page; that page has the source-ref bracket.

### Stage 9 — WikiLinker + Hubs + Validator

**WikiLinker.** Scan every page body. For each known alias (registered from studies/<slug>.md frontmatter `aliases:`), replace plaintext occurrences with `[[studies/<type>/<slug>]]`. Skip occurrences inside source-ref brackets `[DOC | ...]` (protected regex). Idempotent.

**Hubs.** Regenerate:
- `<vault>/<substance>_index.md` — TOC of evidence pages + study counts + freshness markers
- `<vault>/clinical_studies_index.md` — table of canonical clinical studies, one row per study, columns: Phase, Sponsor code, NCT, Nickname, Population, n_randomized
- `<vault>/preclinical_studies_index.md` — table of canonical preclinical studies, columns: Species, Duration, GLP, NOAEL, Effects

**Validator.** Run all 21 rules. See `validator-rules.md`. Write `<vault>/log.md` with run timestamp, doc-by-doc summary, hard fails (with file:line), errors, warnings.

## Idempotency contract

The pipeline must be re-runnable. If the user runs ingest twice on unchanged sources:
- Stage 1 returns "skip" for every doc (hash match)
- Stages 5-9 still run (to pick up code changes), but produce identical output → no diff
- Validator outcome unchanged

If the user adds a new source doc:
- That doc goes through Stages 1-3
- Existing docs are skipped in Stage 1 (hash match)
- Stages 5-9 run over the union of in-memory existing facts + new-doc facts
- Pages get UPDATED (not recreated); evidence pages append the new doc's facts to the existing body
