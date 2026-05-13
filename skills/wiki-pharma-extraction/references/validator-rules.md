# Validator Rules

All 21 rules with severity, what they check, and how to avoid violating them.

## Severity levels

- **hard_fail** — vault is broken; the run is incomplete. Block.
- **error** — significant problem; pages may render but data has integrity issues. Warn.
- **warning** — cosmetic or future-risk issues. Inform.

## Rule 1 — Source ref format (hard_fail)

Every Tier-1 source reference must match exactly: `[DOC_ID | review_type | section | p.N]`.

**Pass:** `[NDA-210951 | Multidisciplinary Review | Clinical Pharmacology | p.45]`

**Fail:** `[NDA-210951, p.45]`, `(NDA-210951 | ... | p.45)`, `[NDA-210951 | ... | p.0]` (use `p.0` only when truly unknown — Rule 20 separately warns on `p.0`).

## Rule 2 — Tier 2 isolation (hard_fail)

Understanding pages (`understanding/*.md`) and synthesized pages must contain **ZERO** `[DOC_ID | ...]` brackets. Only `[[wikilinks]]` to Tier 1.

**Pass:**

```markdown
Apalutamide demonstrates [[evidence/permeability|high permeability]] with Caco-2 Papp values...
```

**Fail:**

```markdown
Apalutamide demonstrates high permeability [NDA-210951 | Multidisciplinary Review | ClinPharm | p.45] with...
```

This is the most common Tier-2 violation. When in doubt, route specific evidence through the relevant `evidence/*.md` page (which CAN carry the bracket) and reference that page via `[[wikilink]]`.

## Rule 3 — Required frontmatter (hard_fail)

Every page must have YAML frontmatter with:
- `page_type` (one of the 20 schemas, or `source`, `hub`, `understanding`, `conflict`)
- `substance` (lowercase INN)
- `last_updated` (ISO date)
- For evidence pages: `confidence` (single-source | multi-source | conflict-pending | resolved-conflict), `source_count` (int)
- For source cards: `doc_id`, `agency`, `review_type`, plus optional retrieval evidence

## Rule 4 — Conflict resolution status (error)

Every `conflicts/*.md` page must have `status:` in {pending, resolved-merge, resolved-keep-both, escalated} and a written rationale.

## Rule 5 — Asset embed targets exist (error)

Every `![[assets/...]]` embed must resolve to an existing file on disk. Common failure: embeds reference `../sources/.../assets/fig_p23_f01.png` but the file is at `../sources/.../assets/figure_p23_f01.png` (name mismatch from Stage 1 staging).

## Rule 6 — Verbatim snippets (hard_fail)

Every fact (Tier 1) must have a verbatim snippet ≥ 8 words. The snippet must appear literally in the source doc text — no paraphrasing.

Validator does substring match: `fact.verbatim in source_text` (with whitespace normalization). If false → hard_fail with reason "verbatim not found in source".

## Rule 7 — Conflict schema validation (error)

ConflictStub objects must have all required fields: `kind` (`value` | `unit` | `presence`), `field`, `values` (list of `{source, value, verbatim}`), `merge_key`, `status`.

## Rule 8 — Summary stale lifecycle (warning)

Understanding pages have a `summary_stale: true|false` frontmatter flag. When `false`, the page must have body content. When `true`, the body may be empty (waiting for regeneration).

## Rule 9 — Staged source asset integrity (error)

Every `[[sources/<doc>/card.md]]` link must point at an existing staged source. Embeds within source cards (like `![[../sources/<doc>/assets/fig.png]]`) must resolve.

## Rule 10 — Evidence pages linked from a hub (error)

Every `evidence/*.md` must be referenced from at least one hub page (`<substance>_index.md` or a study hub). Orphan evidence pages indicate a hub-writer bug.

## Rule 11 — Confidence / source_count coherence (error)

Frontmatter must satisfy:
- `source_count == 1` → `confidence == single-source`
- `source_count >= 2` and no conflict → `confidence == multi-source`
- Any open conflict on this page → `confidence == conflict-pending`
- Resolved conflict → `confidence == resolved-conflict`

## Rule 12 — Unresolved wikilinks (warning)

Every `[[target]]` should resolve to an existing page or a known alias. Unresolved links (typos, removed pages) get flagged as warnings. Aliases registered in studies' frontmatter `aliases:` count as resolved targets.

## Rule 13 — Aliases referenced in body must resolve (error, Phase C)

In evidence pages and understanding pages, every alias mention (e.g. "SPARTAN", "ARN-509-003") must correspond to a registered alias on some `studies/<type>/<slug>.md`. If you mention an alias not in any study's frontmatter, that's an extraction error.

## Rule 14 — Phase + slug uniqueness (hard_fail, Phase C)

Every `clinical_study` and `preclinical_study` page must have `phase:` (clinical) or `study_type:` (preclinical) in frontmatter and a canonical slug. Two studies cannot share the same slug; if a slug collision happens, the resolver should have merged them — flag as a resolver bug.

## Rule 15 — Match candidates not also a slug (warning, Phase C)

If a candidate pair `(slug_A, slug_B)` is in `match_candidates.md` (review band), but one of the slugs has already been merged via a different cluster, the candidate is stale and should be archived (move row to `match_candidates_archive.md`).

## Rule 16 — High-risk field grounding (verifier, error/quarantine)

For high-risk fields (see `pipeline-stages.md` §Stage 5b for the field list), the verifier asks "does verbatim ground value?" — if not, the fact is quarantined. Validator post-pass just checks that quarantine.md doesn't have entries that survived into the rendered pages — they should have been filtered out.

## Rule 17a — Cross-field consistency (error, Phase C)

Within a single study record:
- `n_completed ≤ n_randomized`
- `study_start ≤ completion_date ≤ data_cutoff`

Inconsistencies flag the study for review.

## Rule 17b — Canonical form (error)

Dose units must be in `DOSE_UNITS` (`mg/kg/day`, `mg/kg/d`, `mg/m²/day`, `mg/day`, `mg/kg`, `µg/kg/day`, etc.). Date strings must be ISO `YYYY-MM-DD`. After normalization in Stage 5a, no fact should have a non-canonical form left.

## Rule 18 — Normalization drift (warning)

Uses `normalisation_log.json` from Stage 5a. Flags two patterns:
- **Split drift:** same before-token (e.g. "10 mg/kg") normalized to MULTIPLE after-tokens within one study → ambiguity
- **Suspicious collision:** different before-tokens normalized to the SAME after-token despite different units or magnitudes → potential information loss

## Rule 19 — Missing alias breaks reverse index (error, Phase C)

`WikiLinker` builds a reverse index from study aliases to study pages. If an alias is registered in `studies/<slug>.md` frontmatter but doesn't appear in the alias graph (sponsor_code, nct_id, etc. fields), the link won't be inserted. Promoted to error because data integrity matters.

## Rule 20 — p.0 citations (warning)

Source refs using `p.0` are placeholder for unknown page. They should be rare; if many show up, the upstream pipeline failed to inject page anchors. Flag as warning to motivate fixing the source-extraction stage.

## Rule 21 — Sponsor-code substance ownership (error, Phase C)

Sponsor codes have prefix conventions tied to companies. Validator maintains a known-prefix map (e.g. `ARN-509-*` belongs to apalutamide, `FGCL-*` belongs to roxadustat). If a study page on substance X has a sponsor_code belonging to substance Y, flag — likely a misattribution.

False-positive escape hatch: prefixes we're confident about. New prefixes can be added.

## How to read validator output

`log.md` after a run looks like:

```markdown
## [2026-05-13] ingest | 16 docs | ⚠ partial

- ✓ NDA 210951 | Multidisciplinary Review
  - Updated: evidence/physicochemical.md (+17 facts)
  ...
- ✗ NDA 210951 | Chemistry Review | failed at PageWriter
  - Error: ...

Validation: 6 hard fails, 22 errors, 0 warnings

### Hard fails (top 5)
- Rule 6 verbatim missing: evidence/solubility.md:43 — fact "0.012 mg/mL" verbatim not found in source
- Rule 2 Tier 2 isolation: understanding/apalutamide-bcs.md:12 — direct ref [NDA-210951 | ...] found
- ...
```

Hard fails are blocking — the run is incomplete. Surface them to the user and fix before declaring success.

## What to do when violations fire

| Rule violated | Fix |
|---|---|
| 1 (source ref format) | The page writer has a bug. Check the inline-source-ref template. |
| 2 (Tier 2 isolation) | The Comprehender wrote a `[DOC \| ...]` direct ref. Rewrite the offending sentence using `[[evidence/page]]` and let evidence carry the source ref. |
| 3 (frontmatter) | Page writer is missing a required field. Check the YAML emission. |
| 6 (verbatim) | Extractor paraphrased or fabricated. Quarantine the fact and re-extract with stricter literal-match instruction. |
| 11 (confidence) | Frontmatter is out of sync with body. Recompute. |
| 12 (wikilinks) | Either typo in body or target page was deleted. Investigate. |
| 13 (alias resolution) | Body mentions a study not registered. Add it to `studies/<slug>.md` frontmatter or remove the mention. |
| 16 (verifier) | Verifier already moved the fact to quarantine. Review and either accept (fix verbatim and rerun) or reject (delete from source extraction). |
| 17a (cross-field) | Study record is internally inconsistent. Re-extract or mark needs-review. |
| 19 (alias not in graph) | Add the alias to the corresponding field in the study's frontmatter or in the fanout extra_fields. |
| 21 (sponsor-code substance) | Likely a misclassified doc. Check Stage 2 output. |
