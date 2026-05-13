# Output Format

Exact directory layout, file shapes, frontmatter, and markdown templates for everything the pipeline writes.

## Vault directory layout

```
<vault>/
├── <substance>_index.md                  # Substance hub
├── clinical_studies_index.md             # Phase C hub (always all four phase headers)
├── preclinical_studies_index.md          # Phase C hub (in-vitro + animal)
├── log.md                                # Run log with validator findings
├── .wiki_state.json                      # Per-doc ingest state (sha256, mtime)
├── .wiki_state/
│   └── normalisation_log.json            # Stage 5a output for Rule 18
├── .obsidian/                            # Optional Obsidian config (not regenerated)
│
├── evidence/                             # Tier 1 evidence pages
│   ├── physicochemical.md
│   ├── solubility.md
│   ├── polymorphism.md
│   ├── permeability.md
│   ├── stability.md
│   ├── formulation.md
│   ├── pharmacokinetics.md
│   ├── food_effect.md
│   ├── bioequivalence.md
│   ├── special_populations.md
│   ├── ddi_invitro.md
│   ├── ddi_clinical.md
│   ├── pkpd_model.md
│   ├── pbpk_model.md
│   ├── dissolution_method.md
│   ├── dissolution_profile.md
│   ├── ivivc.md
│   └── guideline.md
│
├── studies/                              # Phase C Tier 1
│   ├── clinical/
│   │   ├── <slug>.md                     # one per canonical clinical study
│   │   └── ...
│   ├── preclinical/
│   │   ├── <slug>.md
│   │   └── ...
│   └── _review/
│       ├── match_candidates.md           # resolver review-band pairs
│       ├── match_candidates_archive.md   # decided pairs that re-disappeared
│       └── quarantine.md                 # Rule 16 verifier rejections
│
├── understanding/                        # Tier 2 synthesis pages
│   ├── <substance>-bioequivalence.md
│   ├── <substance>-pharmacokinetics.md
│   ├── <substance>-solubility.md
│   ├── <substance>-formulation.md
│   ├── <substance>-formulation-evidence.md  # special — evidence-flavored synthesis
│   ├── <substance>-ddi_clinical.md
│   ├── <substance>-ddi_invitro.md
│   ├── <substance>-food_effect.md
│   ├── <substance>-dissolution_method.md
│   ├── <substance>-ivivc.md
│   ├── <substance>-pbpk_model.md
│   ├── <substance>-permeability.md
│   ├── <substance>-physicochemical.md
│   ├── <substance>-pkpd_model.md
│   ├── <substance>-polymorphism.md
│   ├── <substance>-special_populations.md
│   ├── <substance>-stability.md
│   └── bcs-classification.md             # singleton — Comprehender output
│
├── conflicts/                            # Open conflict stubs
│   └── <field>__<merge_key_hash>.md
│
└── sources/                              # Staged sources, one dir per doc
    └── <doc-slug>/
        ├── card.md                       # Source metadata + retrieval evidence
        ├── source.md                     # Copy/symlink of .hybrid.md
        ├── source_hash.txt               # SHA-256 of source.md
        └── assets/
            ├── figure_p23_f01.png
            └── ...
```

## §UnderstandingTopics

The Comprehender writes one understanding page per substance-topic. Topics are 1:1 with evidence pages plus two singletons:

- `<substance>-bcs-classification.md` — synthesized from permeability + solubility evidence
- `<substance>-formulation-evidence.md` — synthesized from formulation + dissolution_method + dissolution_profile

`bcs-classification.md` (without substance prefix) is also a singleton page at the same level — it's the canonical "what is BCS" reference page.

## Evidence page template

```markdown
---
page_type: solubility
substance: apalutamide
confidence: multi-source
source_count: 3
last_updated: 2026-05-13
staled: false
---

# Solubility — apalutamide

<!-- Body is a series of merge-key-grouped bullets, one per fact. -->

## Aqueous solubility

- **Water (pH 7.4, 37 °C):** 0.012 mg/mL.
  - [[sources/210951orig1s000chemr-hybrid|Chemistry Review]] [NDA-210951 | Chemistry/Product Quality Review | Drug Substance | p.23]
  - Verbatim: "Apalutamide is practically insoluble in water (0.012 mg/mL at pH 7.4 at 37 °C)."
- **FaSSIF (pH 6.5, 37 °C):** 0.032 mg/mL.
  - [[sources/ema-004452-0000|EMA EPAR]] [EMEA/H/C/004452/0000 | EPAR Assessment | Drug Substance | p.15]
  - Verbatim: "Solubility in FaSSIF buffer at pH 6.5 and 37 °C was determined to be 0.032 mg/mL."

## Polymorph-specific solubility
- ...
```

**Notes:**
- The body groups facts by sub-topic where natural; otherwise just lists merge-key buckets.
- Each fact is one bullet with: bolded merge-key summary, bullet-indented `[[source-card-wikilink]]` + bracketed source ref, bullet-indented `Verbatim: "..."`.
- The source-card wikilink uses the doc-slug.

## Source card template

```markdown
---
page_type: source
doc_id: NDA-210951
agency: FDA
review_type: Multidisciplinary Review
substance: apalutamide
indication: Non-metastatic castration-resistant prostate cancer
sponsor: Janssen Biotech, Inc.
approval_date: 2018-02-14
trade_names: [Erleada]
source_doc_sha256: a1b2c3...
retrieval_url: https://www.accessdata.fda.gov/drugsatfda_docs/nda/2018/210951Orig1s000MultidisciplineR.pdf
retrieval_date: 2026-05-12
retrieval_tool: get_reports/scripts/extract_apalutamide.py
last_updated: 2026-05-13
---

# NDA 210951 — Multidisciplinary Review

## Document summary

The Multidisciplinary Review for apalutamide (Erleada) supporting NDA 210951
includes Pharmacology/Toxicology, Clinical Pharmacology, Clinical, Statistical,
and Office of Translational Sciences contributions. Approved 2018-02-14 for
non-metastatic castration-resistant prostate cancer.

## Retrieval evidence

- **SHA-256:** `a1b2c3...`
- **Source URL:** [accessdata.fda.gov/.../210951Orig1s000MultidisciplineR.pdf](https://www.accessdata.fda.gov/drugsatfda_docs/nda/2018/210951Orig1s000MultidisciplineR.pdf)
- **Retrieved:** 2026-05-12 via `extract_apalutamide.py`

## Backlinks
<!-- Implicit via Obsidian graph; no PageWriter-maintained list. -->
```

## Study page template

```markdown
---
page_type: clinical_study
substance: apalutamide
study_type: clinical
phase: "3"
canonical_slug: spartan
aliases:
  sponsor_code: ARN-509-003
  nct_id: NCT01946204
  nickname: SPARTAN
  eudract_id: ""
  study_report_id: ""
last_updated: 2026-05-13
---

# SPARTAN — apalutamide Phase 3 in NM-CRPC

## Overview

SPARTAN (ARN-509-003, NCT01946204) was a randomized, double-blind, placebo-controlled
Phase 3 trial in 1207 men with high-risk non-metastatic castration-resistant prostate
cancer. Primary endpoint: metastasis-free survival.

## Data by source

### From NDA 210951 Multidisciplinary Review

- **Phase:** 3
- **Design:** Randomized, double-blind, placebo-controlled
- **Population:** Non-metastatic castration-resistant prostate cancer
- **n_randomized:** 1207
- **Primary endpoint:** Metastasis-free survival

<details><summary>Audit footer — NDA-210951</summary>

| Field | Value | Verbatim | Page | Verifier |
|---|---|---|---|---|
| design | Randomized, double-blind... | "The trial was a randomized, double-blind, placebo-controlled Phase 3 study..." | p.134 | ✓ grounded |
| population | NM-CRPC | "Men with non-metastatic castration-resistant prostate cancer..." | p.134 | ✓ grounded |
| n_randomized | 1207 | "A total of 1207 patients were randomized 2:1..." | p.135 | ✓ grounded |
| primary_endpoint | MFS | "The primary endpoint was metastasis-free survival..." | p.135 | ✓ grounded |
| ... | | | | |

**ALCOA+ metadata:**
- sponsor: Janssen Biotech
- assessment_round: original NDA
- extracted_at: 2026-05-13
- extracted_by: claude (via wiki-pharma-extraction skill)
- prompt_version: extraction-protocol.md v2
- source_doc_sha256: a1b2c3...

</details>

### From EMA EPAR EMEA/H/C/004452/0000

...

## Related evidence-layer data

- [[evidence/special_populations]] — SPARTAN subgroup AUC ratios by renal function
- [[evidence/pharmacokinetics]] — SPARTAN PK substudy data

## Cross-references

<!-- linker: cross-references-start -->
- [[understanding/apalutamide-bioequivalence]] — SPARTAN dose justification
- [[understanding/apalutamide-special_populations]] — subgroup analyses
<!-- linker: cross-references-end -->
```

## Hub page template — `<substance>_index.md`

```markdown
---
page_type: hub
substance: apalutamide
last_updated: 2026-05-13
---

# Apalutamide — Evidence Wiki

## Evidence pages (Tier 1)

### Substance characterization
- [[evidence/physicochemical]] — 28 facts from 3 sources
- [[evidence/solubility]] — 18 facts from 3 sources
- [[evidence/polymorphism]] — 1 fact from 1 source

### Formulation and dissolution
- [[evidence/formulation]] — 151 facts from 4 sources
- [[evidence/dissolution_method]] — 8 facts from 2 sources
- ...

### Clinical PK and PD
- [[evidence/pharmacokinetics]] — ...
- ...

## Understanding pages (Tier 2)

- [[understanding/apalutamide-bioequivalence]]
- [[understanding/apalutamide-bcs-classification]]
- ...

## Studies

- [[clinical_studies_index]] — 14 canonical clinical studies
- [[preclinical_studies_index]] — 24 canonical preclinical studies

## Sources

- [[sources/210951orig1s000multidiscipliner-hybrid|NDA 210951 Multidisciplinary Review]]
- [[sources/ema-004452-0000|EMEA/H/C/004452/0000 EPAR Assessment]]
- ...
```

## Hub page template — `clinical_studies_index.md`

```markdown
---
page_type: hub
substance: apalutamide
last_updated: 2026-05-13
---

# Apalutamide — Clinical Studies

## Phase 1

| Study | Sponsor Code | NCT | Nickname | Population | n_randomized |
|---|---|---|---|---|---|
| [[studies/clinical/arn-509-001]] | ARN-509-001 | — | — | Healthy volunteers | 24 |

## Phase 2

| Study | Sponsor Code | NCT | Nickname | Population | n_randomized |
|---|---|---|---|---|---|
| ... | | | | | |

## Phase 3

| Study | Sponsor Code | NCT | Nickname | Population | n_randomized |
|---|---|---|---|---|---|
| [[studies/clinical/spartan]] | ARN-509-003 | NCT01946204 | SPARTAN | NM-CRPC | 1207 |
| [[studies/clinical/titan]] | PCR3002 | NCT02489318 | TITAN | mHSPC | 1052 |

## Phase 4 / Hybrid

| Study | Sponsor Code | NCT | Nickname | Phase Tag | Population | n_randomized |
|---|---|---|---|---|---|---|
| ... | | | | (hybrid 3/4) | | |
```

## Log file template — `log.md`

Appended per run (new section at top), oldest at the bottom.

```markdown
## [2026-05-13 10:42] ingest | 16 docs | ⚠ partial

- ✓ NDA 210951 | Multidisciplinary Review
  - Updated: evidence/physicochemical.md (+17 facts)
  ...
- ✗ NDA 210951 | Chemistry Review | failed at PageWriter
  - Error: could not convert string to float: 'None'

- Syntheses regenerated: 16
- Summaries regenerated: 16
- Wikilinks inserted: 142
- Hub updated

Validation: 0 hard fails, 4 errors, 12 warnings

### Errors (4)
- Rule 12 unresolved wikilink: understanding/apalutamide-pkpd_model.md — [[evidence/pkpd_model_phase3]] not found
- ...

### Warnings (top 5)
- Rule 20 p.0 citation: evidence/formulation.md:103 (NDA-210951 source-doc, OCR failed page anchor)
- ...

---

## [2026-05-12 21:18] ingest | ...
...
```

## ExtractedFact JSON shape (intermediate, Stage 3 output)

This is the format extracted facts use in memory between Stages 3 and 4. Used to wire the pipeline back together if you persist intermediate state.

```json
{
  "field": "noael",
  "value": "10 mg/kg/day",
  "source": {
    "doc_id": "NDA-210951",
    "review_type": "Pharmacology/Toxicology Review",
    "section": "Repeated-dose toxicity",
    "page": 87,
    "asset": null
  },
  "verbatim": "The NOAEL was determined to be 10 mg/kg/day in male rats based on absence of effects.",
  "confidence": "high",
  "has_verbatim": true,
  "merge_key_fields": {
    "species": "rat",
    "design": "13-week oral toxicity",
    "duration": "13 weeks"
  },
  "extra_fields": {
    "study_id": "preclinical-13wk-rat-tox",
    "verbatim_anchors": {
      "design": "...",
      "noael": "..."
    }
  },
  "asset_ref": null
}
```

## Frontmatter cheat sheet

| page_type | required frontmatter beyond `last_updated`, `substance` |
|---|---|
| evidence/* | confidence, source_count, staled |
| source | doc_id, agency, review_type, indication, sponsor, approval_date, trade_names, [source_doc_sha256, retrieval_url, retrieval_date, retrieval_tool] |
| clinical_study | study_type=clinical, phase, canonical_slug, aliases (dict) |
| preclinical_study | study_type=preclinical, canonical_slug, aliases (dict) |
| hub | (none beyond defaults) |
| understanding | summary_stale (bool) |
| conflict | kind, status |
