# Page Schemas

Twenty schemas cover the structured-evidence dimensions of a regulatory drug dossier. Each schema declares:

- **page_type** — the slug used in `evidence/<page_type>.md`
- **applicable review types** — which doc classes contribute facts to this page
- **required fields** — minimum fields per fact
- **merge key fields** — the explicit tuple that determines fact identity (two facts merge iff these match exactly)
- **typical verbatim trigger phrases** — common phrasings that signal a fact of this type

## Tier 1 — Substance characterization (CMC/quality)

### `physicochemical`

Physical and chemical properties of the API. Applies to: Chemistry Review, EPAR Assessment.

- **Required:** `field`, `value`, `verbatim`, `source`
- **Merge key:** `(property)` — e.g. `molecular_weight`, `pka`, `logp`, `melting_point`
- **Trigger phrases:** "molecular weight is X", "pKa = X", "log P of X", "melting point", "crystalline form"

### `solubility`

Aqueous and biorelevant solubility data. Applies to: Chemistry Review, EPAR Assessment.

- **Required:** `field` (always `solubility`), `value` (e.g. "0.012 mg/mL"), `verbatim`
- **Merge key:** `(medium, ph, temperature)` — e.g. `(water, 7.4, 37C)`, `(FaSSIF, 6.5, 37C)`
- **Trigger phrases:** "solubility in X is Y mg/mL", "practically insoluble in water", "FaSSIF/FeSSIF solubility"

### `polymorphism`

Crystalline forms, polymorphs, salt forms. Applies to: Chemistry Review, EPAR Assessment.

- **Required:** `field` (e.g. `form_A`, `form_B`), `value`, `verbatim`
- **Merge key:** `(form_name)`
- **Trigger phrases:** "Form A is the thermodynamically stable form", "Form B converts to Form A above 50 °C"

### `permeability`

Caco-2, PAMPA, in-vitro permeability, efflux. Applies to: Chemistry Review, ClinPharm Review, EPAR Assessment.

- **Required:** `field`, `value`, `verbatim`
- **Merge key:** `(assay, direction)` — e.g. `(Caco-2, A-B)`, `(MDCK-MDR1, B-A)`
- **Note:** BCS classification was MOVED OUT of permeability/solubility in Phase 11 — it now lives only in `understanding/bcs-classification.md` (Comprehender output)

### `stability`

Drug substance + drug product stability, accelerated/long-term, degradation. Applies to: Chemistry Review, EPAR Assessment.

- **Required:** `field`, `value`, `verbatim`
- **Merge key:** `(matrix, condition, time_point)` — e.g. `(drug_substance, 40C/75RH, 6mo)`
- **Trigger phrases:** "stable for X months at Y", "degradation observed at"

## Tier 1 — Formulation and dissolution

### `formulation`

Composition, excipients, dose strengths, manufacturing process. Applies to: Chemistry Review, EPAR Assessment, EPAR Variation.

- **Required:** `field`, `value`, `verbatim`
- **Merge key:** `(component, role)` — e.g. `(microcrystalline cellulose, filler)`
- **Trigger phrases:** "contains X mg of API", "the tablet contains", "manufactured by direct compression"

### `dissolution_method`

QC dissolution method (apparatus, medium, RPM, sampling). Applies to: Chemistry Review, EPAR Assessment, PSG.

- **Required:** `field`, `value`, `verbatim`
- **Merge key:** `(apparatus, medium, rpm)` — typically one record per QC method

### `dissolution_profile`

Dissolution Q% at time points. Applies to: Chemistry Review, EPAR Assessment, EPAR Variation.

- **Required:** `field`, `value`, `verbatim`
- **Merge key:** `(formulation_id, medium, time_min)`

### `ivivc`

In-vitro / in-vivo correlation. Applies to: Chemistry Review, ClinPharm Review, EPAR Assessment.

- **Required:** `field`, `value`, `verbatim`
- **Merge key:** `(correlation_level, formulation_id)`

## Tier 1 — Clinical PK and PD

### `pharmacokinetics`

PK parameters (Cmax, AUC, t½, Vd, CL) from healthy volunteer or patient studies. Applies to: ClinPharm Review, EPAR Assessment, Multidisciplinary Review.

- **Required:** `field` (parameter name), `value`, `verbatim`
- **Merge key:** `(parameter, dose, population, dosing_regimen)` — e.g. `(Cmax, 240 mg, healthy_volunteers, single_dose)`
- **Trigger phrases:** "Cmax of X ng/mL", "AUC was X ng·h/mL", "t½ of X hours"

### `food_effect`

Fasted vs fed PK ratios. Applies to: ClinPharm Review, EPAR Assessment, PSG.

- **Required:** `field`, `value`, `verbatim`
- **Merge key:** `(parameter, formulation, food_state_comparison)` — e.g. `(AUC, tablet, fed_vs_fasted)`
- **Note:** PSG fasting/fed checkboxes (`☒`/`☐`) must be preserved literally — see `conventions.md` §EMACheckboxes

### `bioequivalence`

BE study results (GMR, 90% CI). Applies to: ClinPharm Review, EPAR Variation, PSG.

- **Required:** `field`, `value`, `verbatim`
- **Merge key:** `(test_formulation, reference_formulation, pk_parameter, food_state)` — e.g. `(generic_tablet, reference_tablet, AUC, fed)`

### `special_populations`

Renal/hepatic impairment, age, sex, race, pregnancy. Applies to: ClinPharm Review, EPAR Assessment, Multidisciplinary Review.

- **Required:** `field`, `value`, `verbatim`
- **Merge key:** `(population_group, parameter)` — e.g. `(severe_renal_impairment, AUC_ratio)`

### `ddi_invitro`

In-vitro DDI: CYP inhibition/induction, transporter substrate/inhibitor. Applies to: ClinPharm Review, EPAR Assessment, Multidisciplinary Review.

- **Required:** `field`, `value`, `verbatim`
- **Merge key:** `(enzyme_or_transporter, interaction_type, role)` — e.g. `(CYP3A4, inhibition, substrate)`

### `ddi_clinical`

In-vivo DDI studies (AUC/Cmax ratios with perpetrators/victims). Applies to: ClinPharm Review, EPAR Assessment, Multidisciplinary Review.

- **Required:** `field`, `value`, `verbatim`
- **Merge key:** `(perpetrator, victim, pk_parameter)` — e.g. `(rifampin, apalutamide, AUC)`

### `pkpd_model`

PK/PD modeling: exposure-response, biomarkers. Applies to: ClinPharm Review, EPAR Assessment, Multidisciplinary Review.

- **Required:** `field`, `value`, `verbatim`
- **Merge key:** `(model_name, parameter)`

### `pbpk_model`

PBPK model details: software, virtual populations, predictions. Applies to: ClinPharm Review, EPAR Assessment.

- **Required:** `field`, `value`, `verbatim`
- **Merge key:** `(software, scenario)` — e.g. `(Simcyp, hepatic_impairment_simulation)`

## Tier 1 — Guideline (special)

### `guideline`

PSG-specific recommendations (FDA Product-Specific Guidance for generic development). Applies to: PSG only.

- **Required:** `field`, `value`, `verbatim`
- **Merge key:** `(topic)` — e.g. `(BE_study_design)`, `(dissolution_method)`

## Tier 1 — Studies (Phase C)

### `clinical_study`

One record per clinical trial. Applies to: ClinPharm Review, Statistical Review, Multidisciplinary Review, EPAR Assessment, EPAR Variation.

- **Required fields per record:** `study_id`, `sponsor_code` OR `nct_id`, `phase`, `design`, `population`, `n_randomized`, `primary_endpoint`
- **Optional but high-value:** `nickname` (e.g. SPARTAN, TITAN), `eudract_id`, `country_of_conduct`, `n_completed`, `gcp_compliance`, `key_results` (dict with `gmr`, `difference_ci`, `p_value`), `safety` (dict with `teae_pct`, `sae_pct`, `deaths`), `start_date`, `completion_date`, `data_cutoff`
- **Merge key:** NOT used for cross-doc dedup (resolver handles study identity). Within-doc merge by `(sponsor_code OR nct_id, phase)`.
- **Special:** the extractor outputs a single "blob" record per study; a post-processing fanout splits it into per-field facts, each with its own `verbatim_anchors[field_name]` in `extra_fields`. See `extraction-protocol.md` §PhaseC.

### `preclinical_study`

One record per preclinical (animal or in-vitro) study. Applies to: Pharmacology/Toxicology Review, Multidisciplinary Review, EPAR Assessment.

- **Required fields per record:** `study_id`, `species` (animal) OR `system` (in-vitro), `design` (e.g. "13-week oral toxicity"), `duration`, `dose_levels`
- **Optional but high-value:** `glp_status`, `noael`, `noel`, `mtd`, `lowest_observed_effect_level`, `route_of_administration`, `key_findings` (list of strings), `study_report_id`
- **Merge key:** within-doc merge by `(species, design, duration)`; cross-doc via resolver.
- **Special:** same blob+fanout as `clinical_study`.

## Schema registry quick-reference

| page_type | category | merge key |
|---|---|---|
| physicochemical | CMC | (property) |
| solubility | CMC | (medium, ph, temperature) |
| polymorphism | CMC | (form_name) |
| permeability | CMC | (assay, direction) |
| stability | CMC | (matrix, condition, time_point) |
| formulation | CMC | (component, role) |
| dissolution_method | CMC | (apparatus, medium, rpm) |
| dissolution_profile | CMC | (formulation_id, medium, time_min) |
| ivivc | CMC/PK | (correlation_level, formulation_id) |
| pharmacokinetics | PK | (parameter, dose, population, dosing_regimen) |
| food_effect | PK | (parameter, formulation, food_state_comparison) |
| bioequivalence | PK | (test_formulation, reference_formulation, pk_parameter, food_state) |
| special_populations | PK | (population_group, parameter) |
| ddi_invitro | PK | (enzyme_or_transporter, interaction_type, role) |
| ddi_clinical | PK | (perpetrator, victim, pk_parameter) |
| pkpd_model | PK/PD | (model_name, parameter) |
| pbpk_model | PK | (software, scenario) |
| guideline | PSG | (topic) |
| clinical_study | Phase C | (resolver) |
| preclinical_study | Phase C | (resolver) |

The Python `SchemaRegistry` at `evidence_wiki/schema/registry.py` is the authoritative source — read it if anything here looks ambiguous.
