# Extraction Protocol

How Claude does each LLM-shaped step. These protocols replace the prompts that the external pipeline sends to GPT-OSS / GLM / Gemma — you (Claude) follow them inline.

## Classification

**Task:** identify the source doc's agency, review type, substance, and document id.

**Procedure:**
1. Read the first 3-5K chars of `source.md` (or the head of the .hybrid.md if not yet staged). Most regulatory docs identify themselves on page 1: "Multidisciplinary Review for NDA 210951 (apalutamide)", or "CHMP assessment report — Erleada (apalutamide) — EMEA/H/C/004452/0000".
2. Look at the filename for confirmation. Filenames like `210951Orig1s000MultidisciplineR.hybrid.md` → `Multidisciplinary Review` for NDA 210951. EMA files have `Erleada_-_Erleada___EPAR_-_Public_assessment_report.hybrid.md` shape.
3. Apply heuristics in `pipeline-stages.md` §Classification.
4. Emit JSON:

```json
{
  "source_agency": "FDA",
  "review_type": "Multidisciplinary Review",
  "substance_inn": "apalutamide",
  "product_names": ["Erleada"],
  "document_id": "NDA-210951"
}
```

**Common pitfalls:**
- Don't classify based on directory path alone — the file content is authoritative
- "Integrated Review — Pharmacology/Toxicology" is a real FDA review type (NOT "Multidisciplinary Review") for some applications
- EMA Variations are CHMP assessment reports for post-approval changes — distinguish from initial EPAR

## Per-schema extraction

For each schema in `SchemaRegistry.schemas_for_review_type(classification.review_type)`:

### Step A — Determine if this schema applies to this doc

Each schema declares `applicable_review_types`. For example, `solubility` applies to Chemistry Review and EPAR Assessment but not to Statistical Review. If the schema doesn't apply, skip it (zero facts).

### Step B — Find the relevant section(s)

Source docs are typically 50-600 KB markdown with section headers. For `solubility`, search for sections titled "Solubility", "Physicochemical Properties", "Drug Substance Characteristics". For `pharmacokinetics`, search for "Clinical Pharmacology", "Pharmacokinetics", "PK Profile". For `clinical_study`, search for "Clinical Studies", "Phase 3 Trial", trial nicknames in caps (SPARTAN, TITAN), or numbered references like "Study ARN-509-003".

### Step C — Extract facts

For each fact you find:

1. Identify the `field` name (use schema-declared field names).
2. Capture the `value` (the actual datum — number, string, or short phrase).
3. Lift a **literal 15-20-word snippet** from the source. This is the `verbatim`. Do NOT paraphrase. Hard-fail floor: 8 words. If a single phrase under 8 words is the only mention, expand the snippet to include the surrounding sentence.
4. Identify `source.page` from the HTML page anchor `<a id="pN"></a>` immediately preceding the sentence (the pdf_hybrid_pipeline injects these anchors). If the source.md has page markers like `## Page 23`, use that. If neither, use `0` (Rule 20 will warn).
5. Identify `source.section` — the most recent `##` or `###` heading.
6. Compute `merge_key_fields` per the schema's declared merge tuple. Lowercase, normalise units (see `conventions.md`).
7. Set `confidence`:
   - `high` — explicit, unambiguous statement
   - `medium` — implied or tabular reference
   - `low` — only mentioned in passing or in a table caption
8. Emit as JSON per the shape in `pipeline-stages.md` §Stage 3.

### Step D — Validate before returning

For each fact:
- `verbatim` word count ≥ 8
- `verbatim` literally appears in `source.md` (you should be able to grep-find it)
- All required fields present
- `merge_key_fields` keys match the schema's declared tuple

Drop any fact that fails these checks. Better to under-extract than to write bad data.

## §PhaseC — Clinical / preclinical study extraction

Phase C uses a **blob + fanout** pattern because studies have many fields and we need per-field verbatim grounding.

### Step 1 — Find studies in the doc

Scan for trial mentions:
- All-caps nicknames in pharma context: SPARTAN, TITAN, HIMALAYAS, PYRENEES, etc.
- Sponsor study codes: `ARN-509-001`, `56021927PCR3002`, `FGCL-45-064`, `Study 1018`
- NCT registrations: `NCT03683498`, `NCT02489318`
- EudraCT: `2018-001234-12`
- Generic phrasing: "the Phase 3 trial", "in the pivotal study", "single-dose study in healthy volunteers"

For each unique study reference, gather ALL information about it from across the doc — studies are often discussed in multiple sections.

### Step 2 — Emit a single blob record per study

```json
{
  "field": "clinical_study",
  "value": "SPARTAN",
  "source": {"doc_id": "...", "review_type": "...", "section": "Clinical Studies", "page": 134, "asset": null},
  "verbatim": "SPARTAN (ARN-509-003) was a randomized, double-blind, placebo-controlled Phase 3 trial in 1207 patients with NM-CRPC.",
  "confidence": "high",
  "has_verbatim": true,
  "merge_key_fields": {"sponsor_code": "ARN-509-003", "phase": "3"},
  "extra_fields": {
    "nickname": "SPARTAN",
    "nct_id": "NCT01946204",
    "phase": "3",
    "design": "Randomized, double-blind, placebo-controlled",
    "population": "Non-metastatic castration-resistant prostate cancer",
    "n_randomized": "1207",
    "primary_endpoint": "Metastasis-free survival",
    "gcp_compliance": "GCP",
    "verbatim_anchors": {
      "design": "The trial was a randomized, double-blind, placebo-controlled Phase 3 study in NM-CRPC patients.",
      "population": "1207 men with non-metastatic castration-resistant prostate cancer were enrolled in SPARTAN.",
      "n_randomized": "A total of 1207 patients were randomized 2:1 to apalutamide or placebo.",
      "primary_endpoint": "The primary endpoint was metastasis-free survival as assessed by blinded independent central review.",
      "gcp_compliance": "The study was conducted in accordance with Good Clinical Practice (GCP) guidelines."
    }
  },
  "asset_ref": null
}
```

**Key:** `extra_fields.verbatim_anchors` is a dict mapping every field listed in `extra_fields` (except `verbatim_anchors` itself and any pure passthroughs like `nickname` / `nct_id`) to its own literal 15-20-word snippet. Same field → same value? Anchor must support BOTH. Anchor not found in source → that field gets quarantined post-fanout.

This is the **load-bearing fix** for the 132-quarantine bug from May 2026: previously the extractor reused one headline snippet across all fields, and the verifier (correctly) rejected most because the snippet didn't actually mention NOAEL, GLP, etc.

### Step 3 — Fanout (handled in post-processing)

The post-processor (you don't do this step manually — it runs after Stage 3) splits the blob into per-field facts:

```
clinical_study blob with verbatim_anchors{design, population, n_randomized, ...}
   ↓ fanout
fact{field=design, value="Randomized, double-blind...", verbatim=verbatim_anchors[design]}
fact{field=population, value="NM-CRPC", verbatim=verbatim_anchors[population]}
fact{field=n_randomized, value="1207", verbatim=verbatim_anchors[n_randomized]}
...
```

You just need to ensure every field in `extra_fields` is covered in `verbatim_anchors`. If you can't ground a field, OMIT IT from `extra_fields` rather than emit it with a bad anchor.

## Verification (Stage 5b)

For each high-risk-field fact (see `pipeline-stages.md` §Stage 5b for the field list):

**Procedure:**
1. Read `fact.verbatim`.
2. Read `fact.value` and `fact.field`.
3. Ask: does the verbatim **specifically** mention this fact's claim, in this fact's terminology?

**Examples:**

| field | value | verbatim | Verdict |
|---|---|---|---|
| `noael` | `10 mg/kg/day` | "The NOAEL was determined to be 10 mg/kg/day in male rats based on absence of effects." | ✅ Grounded |
| `noael` | `10 mg/kg/day` | "Doses up to 100 mg/kg/day were administered to rats over 13 weeks." | ❌ No NOAEL mention |
| `glp_status` | `GLP` | "The study was conducted in compliance with GLP guidelines under 21 CFR 58." | ✅ Grounded |
| `glp_status` | `GLP` | "Apalutamide 240 mg daily was tested in a pivotal Phase 3 trial." | ❌ No GLP mention |
| `primary_endpoint` | `MFS` | "The primary endpoint of SPARTAN was metastasis-free survival." | ✅ Grounded |
| `n_randomized` | `1207` | "1207 patients were randomized in SPARTAN to apalutamide (n=806) or placebo (n=401)." | ✅ Grounded |
| `population` | `NM-CRPC` | "Men with high-risk non-metastatic castration-resistant prostate cancer were eligible." | ✅ Grounded |

When grounded → keep the fact. When not grounded → move to `studies/_review/quarantine.md` with reason "verifier rejected: verbatim contains no mention of <field>".

## Resolver (Stage 6)

See `pipeline-stages.md` §Stage 6 for the algorithm. The LLM-shaped part is only the borderline-pair confidence judgment:

For each pair of clusters (each with its own facts), compare:
- Trial nicknames (if both have nicknames)
- Phase
- Design summary
- Population (1-2 sentence summary)
- Sponsor (Janssen vs FibroGen vs ...)

If they look like the SAME trial described in different sources → confidence 0.85-1.0. Write to `match_candidates.md` if 0.5-0.85, auto-merge if >0.85.

**Disambiguation heuristics for sponsor-code:**
- `56021927PCR3002` and `PCR3002` — same study (Johnson & Johnson prepends sponsor-org numeric code)
- `Study 1018` and `56021927PCR1018` — same study (short-form vs full-form)
- `FGCL-45-064` and `Study 064` — likely same study (sponsor + suffix vs short-form)

Confidence rationale must be specific: state what aliases overlap, what differs, why you concluded merge or not.

## Comprehender (Stage 8) — understanding pages

For each `understanding/<substance>-<topic>.md`:

1. **Identify the topic.** Topics map to evidence pages: `solubility`, `permeability`, `dissolution_method`, `formulation`, `bioequivalence`, `food_effect`, `pharmacokinetics`, `special_populations`, `ddi_invitro`, `ddi_clinical`, `pkpd_model`, `pbpk_model`, `ivivc`, `polymorphism`, `stability`. Plus the synthesized: `bcs-classification`, `formulation-evidence`. See `output-format.md` §UnderstandingTopics.
2. **Read the Tier 1 evidence pages** that feed this topic.
3. **Synthesise** a 200-500 word narrative. Style: a knowledgeable pharma generic-development team-member explaining the data, calling out gaps and disagreements.
4. **Tier 2 isolation:** every reference to a specific number or finding gets a `[[evidence/<page>]]` or `[[studies/<type>/<slug>]]` wikilink. ZERO `[DOC_ID | type | section | p.N]` direct refs. If you need to point at a specific source-doc, put it in the corresponding evidence page; understanding pages reference the evidence page, not the source.

**Example — apalutamide-bcs-classification.md:**

```markdown
# BCS Classification — apalutamide

Apalutamide is a [[evidence/permeability|highly permeable]] (Caco-2 Papp A-B ~25 × 10⁻⁶ cm/s) and
[[evidence/solubility|low-solubility]] compound (water solubility 0.012 mg/mL at pH 7.4). Based on
the FDA's biopharmaceutics classification system, this places apalutamide in [[bcs-classification|BCS Class II]] —
high permeability, low solubility. The poor aqueous solubility is the rate-limiting factor for absorption,
and the commercial formulation employs amorphous solid dispersion technology to enhance dissolution
(see [[evidence/formulation]]). The [[evidence/food_effect|food effect]] data corroborate this: a high-fat meal
increased apalutamide AUC by ~14% with no clinically meaningful effect on Cmax, consistent with
solubility-limited absorption in the GI tract.
```

Notice: ZERO `[DOC | review | section | p.N]` brackets. All references go through `[[wikilinks]]` to Tier 1 evidence pages.

## What to do when you're unsure

- **Don't fabricate.** If a fact's verbatim doesn't clearly support the value, drop the fact.
- **Don't over-claim.** "Probably" or "may have" qualifiers in the source → confidence=`medium` or `low`, not `high`.
- **Don't compress redacted content.** `(b)(4)` markers → literal `[CBI — FOI redacted]` in value. Don't speculate.
- **Don't fill in missing study fields.** Better to leave `nct_id` empty than guess. The resolver tolerates missing aliases.
- **When schemas conflict** (rare — same doc says two different solubilities for the same medium/pH/temp): emit BOTH facts. The validator's conflict detection (Rule 4 / Rule 11) will surface them in `conflicts/`.
