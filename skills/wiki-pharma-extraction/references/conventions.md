# Conventions

Verbatim rules, FOI redaction, slug rules, normalization tables.

## Verbatim snippet rules

- **Length:** 15-20 words preferred. Floor: 8 words (Rule 6 hard-fails below).
- **Literal:** must appear verbatim in `source.md`. No paraphrasing, no "lightly edited", no inserted ellipsis.
- **Whitespace tolerance:** the validator normalises whitespace (collapses multiple spaces, normalises non-breaking spaces) before substring check.
- **Encoding:** UTF-8 — preserve `°`, `µ`, `±`, `≤`, `≥`, `–`, `—`, `→` as in source.
- **Per-field anchors:** for Phase C study records, every field in `extra_fields` gets its OWN verbatim in `verbatim_anchors[field]`. See `extraction-protocol.md` §PhaseC.

**Good verbatim:**
- "Apalutamide is practically insoluble in water (0.012 mg/mL at pH 7.4 at 37 °C)." (16 words)
- "The NOAEL was determined to be 10 mg/kg/day in male rats based on absence of effects." (15 words)

**Bad verbatim (paraphrased):**
- "Apalutamide has low water solubility" (paraphrased; not in source)

**Bad verbatim (too short, no expansion):**
- "NOAEL = 10 mg/kg" (5 words; even if literally in source, expand to surrounding sentence)

## FOI / CBI redaction

FDA review PDFs use `(b)(4)` markers to redact Confidential Business Information (CBI). Other patterns: `(b)(5)`, `(b)(6)`. EMA EPARs may use `[redacted]` or `(CBI)`.

**Rule:** when a value or verbatim contains a redaction marker, replace with literal `[CBI — FOI redacted]` in the value. Keep the verbatim as-is (showing the redaction marker is informative).

Example:

```json
{
  "field": "manufacturing_site",
  "value": "[CBI — FOI redacted]",
  "verbatim": "The drug substance is manufactured at (b)(4) under GMP conditions."
}
```

## Slug rules

### Document slug (for `sources/<doc-slug>/`)

- Take the filename stem (without `.hybrid.md` or `.extracted.txt`)
- Lowercase
- Replace any character that is not `[a-z0-9-]` with `-`
- Collapse multiple `-` to single
- Trim leading/trailing `-`

Examples:
- `210951Orig1s000MultidisciplineR.hybrid.md` → `210951orig1s000multidiscipliner-hybrid`
- `Erleada_-_Erleada___EPAR_-_Public_assessment_report.hybrid.md` → `erleada-erleada-epar-public-assessment-report-hybrid`

### Study canonical slug

Priority order:
1. NCT id (lowercased): `NCT01946204` → `nct01946204`
2. EudraCT id (collapsed): `2018-001234-12` → `eudract-2018-001234-12`
3. Sponsor code (lowercased, slug-normalized): `ARN-509-003` → `arn-509-003`
4. Nickname (lowercased): `SPARTAN` → `spartan`
5. Content-hashed fallback: `clinical-p3-<sha1_of_design_summary>[:10]` → `clinical-p3-399e1d5638`

Prefer the first that is non-empty. If only nickname is available, sluggify it.

### Substance INN

Always lowercase, no spaces. `apalutamide`, `roxadustat`, `fidaxomicin`. Used as filename prefix for understanding pages.

## Normalization tables

### Dose units (DOSE_UNITS canonical set)

| Input | Canonical |
|---|---|
| `mg/kg/d`, `mg/kg/day`, `mg per kg per day`, `mg·kg⁻¹·day⁻¹` | `mg/kg/day` |
| `mg/kg/dose`, `mg/kg single dose` | `mg/kg/dose` |
| `mg/m²/d`, `mg/m^2/day` | `mg/m²/day` |
| `mg/day`, `mg/d`, `mg per day`, `mg QD` | `mg/day` |
| `mg BID` (twice daily) | preserved literally (`mg BID`) — don't convert to `mg/day` |
| `ug/kg/day`, `mcg/kg/d` | `µg/kg/day` |
| `g/kg`, `gram/kg` | `g/kg` |

### Duration units (DURATION_UNITS canonical set)

| Input | Canonical |
|---|---|
| `1 month`, `30 days` | `30 days` |
| `3 weeks`, `21 days` | `21 days` |
| `13-week`, `13 weeks`, `91 days` | `91 days` |
| `1 year`, `12 months`, `52 weeks` | `52 weeks` |
| `single dose`, `single-dose` | `single dose` |
| `subchronic`, `subacute` | preserved literally (qualitative term) |

When mapping, log to `.wiki_state/normalisation_log.json` with `rule: duration_canonical` so Rule 18 can detect drift.

### Dates

All dates to ISO `YYYY-MM-DD`.

| Input | Canonical |
|---|---|
| `14 February 2018`, `February 14, 2018`, `Feb 14 2018` | `2018-02-14` |
| `2018-02` (month only) | `2018-02-01` (default day = 1) |
| `Q1 2018` | `2018-03-31` (default end-of-quarter) |
| `2018` (year only) | `2018-01-01` |

### Study phase

Canonical: `1`, `1/2`, `2`, `2/3`, `3`, `3/4`, `4`. Hybrid phases (like `2b/3`) are preserved as-is but tagged as hybrid in `clinical_studies_index.md` (gets a "hybrid" tag in the row).

### Population shorthand

Don't normalise — preserve the source's terminology. `mCRPC`, `NM-CRPC`, `mHSPC`, `nmCSPC` are all distinct clinical phenotypes; don't collapse them.

## EMA PSG checkbox preservation

EMA Product-Specific Guidance PDFs encode design choices as checkbox glyphs: `☒` (checked, U+2612) and `☐` (unchecked, U+2610). These usually appear in tables for fasting vs fed, BCS class, recommended BE study design, etc.

**Rule:** preserve the glyphs literally in `verbatim` and `value`. Do NOT convert to "checked"/"unchecked" or `true`/`false`.

Example:

```
| Fasting | Fed |
| ☒       | ☐   |
```

→ `value: "fasting: ☒, fed: ☐"`, verbatim preserves the row.

## Multi-source merge identity

Two facts merge into one bucket on a page iff:
- Same `field` (the schema's primary field name)
- Same `merge_key_fields` dict (key-for-key, value-for-value match)

The merge key is **schema-declared and explicit**. Do NOT merge on semantic similarity, fuzzy units, or "looks like the same thing". Better to under-merge (page shows two near-duplicate facts) than to over-merge (lost a real disagreement).

Conflicts within a merged bucket (same merge key, different `value`) → emit a ConflictStub in `conflicts/`. Validator Rule 4 + Rule 11 keep the bucket coherent.

## Per-role retrieval evidence (Theme C)

Source cards may carry retrieval-evidence frontmatter:

```yaml
source_doc_sha256: a1b2c3...
retrieval_url: https://www.accessdata.fda.gov/drugsatfda_docs/nda/2018/...
retrieval_date: 2026-05-12
retrieval_tool: get_reports/scripts/extract_apalutamide.py
```

Only emit these fields when at least one is populated. Conditional emission preserves idempotency for older runs that lack the metadata.
