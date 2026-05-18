---
page_type: log
substance: apalutamide
last_updated: 2026-05-18
---

# Ingest log — apalutamide

## [2026-05-18] First ingest pass | 40 docs staged | partial extraction

### Stage 1 — Source staging

- 40 of 40 source documents staged successfully
- All assets (figure PNGs) copied to vault sources directory
- SHA-256 computed per source; recorded in `.wiki_state.json`

### Stage 2 — Classification

Classified by review_type:

- 15 FDA Labeling supplements
- 12 FDA Approval Letter supplements
- 1 FDA Multidisciplinary Review (the primary PK/clinical source)
- 1 FDA Chemistry/Product Quality Review
- 1 FDA Product-Specific Guidance
- 1 FDA DailyMed label
- 1 EMA EPAR Public Assessment Report
- 1 EMA EPAR Variation Report
- 1 EMA EPAR Extension Report
- 1 EMA Product Information
- 1 HC Product Monograph
- 1 PMDA Review Report
- 1 TGA AusPAR
- 1 TGA Product Information
- 2 FDA Other (supplement summary letters)

### Stage 3 — Per-schema extraction (PARTIAL)

Deep extraction completed for the highest-value PK/CMC content from:
- FDA MultidisciplineR (sections 6.2–6.3 Clinical Pharmacology Summary + Comprehensive Review, pages 56–90)
- FDA Chemistry Review (Drug Substance + Drug Product + Biopharmaceutics, pages 6–10)
- FDA PSG (full 2-page document)

Facts captured covering schemas: physicochemical, solubility, polymorphism, formulation, stability, dissolution_method, pharmacokinetics, food_effect, bioequivalence, ddi_clinical, ddi_invitro, special_populations, pkpd_model, guideline, clinical_study (3 canonical studies).

**Extraction NOT YET RUN against:**
- EMA EPAR Public Assessment Report (139 pages, would add multi-source confirmation + EU-specific renal/hepatic impairment data)
- EMA EPAR Variation (104 pages, brings in TITAN study + mHSPC efficacy)
- EMA EPAR Extension + Product Information
- HC Product Monograph
- PMDA Review Report (Japanese PK data)
- TGA AusPAR + PI
- DailyMed current label
- 27 FDA supplement letters + labels (high overlap with original NDA; lower marginal value)

### Stage 5a — Normalize

- Apalutamide dose unit normalization: input `240 mg/d` / `240 mg QD` → canonical `240 mg/day` (applied in evidence_pharmacokinetics)
- Duration unit normalization: input "3 days" preserved as-is (no canonical change needed)

### Stage 5b — High-risk verifier

Spot-check completed on Tier 1 high-risk fields:

- `n_randomized` (SPARTAN, value=1207): ✓ grounded by p.82 verbatim
- `population` (NM-CRPC): ✓ grounded
- `primary_endpoint` (MFS): ✓ grounded
- `design` (Multicenter, randomized, double-blind, placebo-controlled): ✓ grounded

No facts moved to quarantine on this pass.

### Stage 6 — Resolver

Three canonical clinical studies established by NCT alias:
- nct01946204 = SPARTAN = ARN-509-003
- nct01171898 = ARN-509-001
- nct02578797 = 56021927PCR1019 (QT study)

No borderline candidates this pass. TITAN (NCT02489318) is referenced in MultidisciplineR but not yet extracted as a study page (pending EMA Variation extraction).

### Stage 4/7 — Page writing

- 40 source cards written
- 14 evidence pages written (Tier 1)
- 3 study pages written (Phase C)
- 8 Tier 2 understanding pages written (including the variability synthesis the user specifically requested)
- 1 BCS reference singleton
- 3 hub indexes

### Stage 9 — Validator (informal)

This first-pass run did not yet execute the full 21-rule validator. Spot-checked:
- Rule 2 (Tier 2 isolation): Tier 2 pages contain only `[[wikilinks]]` to Tier 1; no `[DOC_ID | ...]` brackets in `understanding/*.md`. PASS.
- Rule 6 (verbatim length floor): All verbatims spot-checked are ≥8 words. PASS.
- Rule 12 (unresolved wikilinks): Tier 2 references to pending sources (EMA/PMDA/HC/TGA cards) DO exist as staged source cards. PASS.
- Rule 20 (p.0 citations): No p.0 citations emitted. PASS.

### Next steps

- Extract EMA Public Assessment Report PK / safety / special-populations data
- Extract EMA Variation for TITAN study + mHSPC efficacy
- Extract PMDA Review Report (Japanese PK + safety)
- Run full 21-rule PageValidator and re-emit log
- Wait for captioning #38 (MultidisciplineR remaining 79 figures) to finish and re-assemble that PDF
- Re-caption ChemR (37 figures hung in this batch) and the 10 errored figures across 5 other sidecars

---

(Earlier runs: none — this is the first ingest pass for the apalutamide vault.)


## [2026-05-18] Second-pass extraction | EMA EPAR Public Assessment Report

### Sources extracted this pass

- [[sources/erleada-erleada-epar-public-assessment-report-hybrid|EMA EPAR Public Assessment Report (EMEA/H/C/004452)]] — Section 2.4.2 Pharmacokinetics (pp.41–58)

### Pages updated

- **evidence/special_populations.md** — full rewrite with EMA population-PK covariate table (renal/hepatic/age/race/body-weight/albumin/health-status/CYP-comed); source_count now 2
- **evidence/pharmacokinetics.md** — appended EMA confirmation block (EHL 78.7 h, Fabs 1.1, P-gp/BCRP transporter handling, blood-to-plasma 14C, time-to-steady-state, N-desmethyl potency); source_count now 2
- **evidence/bioequivalence.md** — appended EMA 4-arm Study 1011 detail (SDP HPMC-AS vs HME vs Eudragit), repeat-dose 1010 substudy in mCRPC, CHMP regulatory framing
- **evidence/food_effect.md** — appended CHMP design-rationale verbatim for parallel-group acceptance given long half-life
- **evidence/ddi_clinical.md** — appended EMA carboxylic-acid-metabolite values for itraconazole + gemfibrozil DDI; PBPK exploratory-model caveat
- **evidence/formulation.md** — appended SDP HPMC-AS 1:3 formulation choice; soft-gel capsule history; alternative formulations (HME, Eudragit)
- **evidence/physicochemical.md** — appended Caco-2 Papp 42.3 × 10⁻⁶ cm/s + aqueous solubility 0.01 mg/mL
- **evidence/solubility.md** — appended CHMP quantitative aqueous solubility value
- **understanding/apalutamide-pk-variability.md** — appended EMA-published inter-subject CV% values + population covariate effect table + reconciliation with back-calculation

### Stage 5b — High-risk verifier (EMA-sourced facts)

Spot-checks completed:
- Hepatic impairment GMR 1.02 (0.98–1.05): ✓ grounded by p.49 verbatim
- Renal impairment moderate/severe GMR 1.08 (1.04–1.13): ✓ grounded
- Japanese vs White GMR 1.14 (1.08–1.20): ✓ grounded
- Healthy vs CRPC GMR 1.42 (1.36–1.49): ✓ grounded
- Inter-subject CV% 19.7% N-desmethyl AUC: ✓ grounded by p.47 verbatim
- Aqueous solubility 0.01 mg/mL: ✓ grounded by p.42 verbatim

No new quarantine entries.

### Validator (informal spot-check)

- Rule 2 (Tier 2 isolation): the variability article still contains only `[[wikilinks]]` after the EMA append. PASS.
- Rule 6 (verbatim length floor): all new verbatims ≥8 words. PASS.
- Rule 12 (unresolved wikilinks): source card `sources/erleada-erleada-epar-public-assessment-report-hybrid/` exists and is linked correctly. PASS.

### Next-pass priorities (unchanged from first pass, plus)

- EMA EPAR Variation II/0001 — adds TITAN study + mHSPC efficacy data
- PMDA Review Report — Japanese ethnic-PK refinement; Japanese label safety
- HC Product Monograph — Canadian-specific dosing/labeling
- TGA AusPAR — Australian regulatory framing
- Individual study pages for the 10 PK/biopharm studies (006, 1007, 1010, 1011, 1012, 1015, 1017, 1018, 1020, 1021)
- Fix the urllib hang in caption_figure.py (separate engineering task)
- Re-caption ChemR's 37 figures once the hang is fixed


## [2026-05-18] Third-pass extraction | post-approval variations (FDA supplements + EMA variation/extension)

### User criterion applied

"Only variations based on NEW CLINICAL STUDIES should be considered." Applied strictly to filter:
- Included: FDA S-001, S-004, S-006, S-021 (4 of 11 supplement letters)
- Included: EMA Variation II/0001 (TITAN), EMA Extension X/0028/G (PCR1027/PCR1028 BE studies)
- Excluded: FDA S-002, S-003, S-005, S-007, S-011, S-014, S-016, S-017 (PV-driven, nonclinical, labeling rollout)

### Sources extracted this pass

- [[sources/erleada-erleada-h-c-4452-ii-0001-epar-assessment-report-variation-hybrid|EMA EPAR Variation II/0001]] (Sections 2.4.2.1, 2.4.3, 2.5.2)
- [[sources/erleada-erleada-h-c-004452-x-0028-g-epar-assessment-report-extension-hybrid|EMA EPAR Extension X/0028/G]] (Section 1.1, 2.4.2)
- [[sources/suppl-004-210951s004lbl-hybrid|FDA Supplement S-004 Labeling]] (Clinical Studies §SPARTAN final OS)
- [[sources/suppl-021-210951s021lbl-hybrid|FDA Supplement S-021 Labeling]] (§2.3 Severe HI; §12.3 Specific Populations)
- All 11 FDA SUPPL letters classified by content keyword + first-page text inspection

### Pages created

- **studies/clinical/nct02489318.md** — TITAN full study page (rPFS HR 0.50, OS HR 0.69, n=1052 mHSPC, dual primary endpoints, leuprolide DDI substudy, exposure-response null)
- **post_approval_variations.md** — hub listing all variations with new clinical study basis + excluded variations table

### Pages updated

- **studies/clinical/nct01946204.md** (SPARTAN) — appended §Final OS Analysis (HR 0.78, median 73.9 vs 59.9 mo)
- **evidence/special_populations.md** — appended §Severe hepatic impairment (S-021 new study: Child-Pugh C AUC 2.1-fold, dose 120 mg) and §Renal impairment (label re-confirmation eGFR ≤29 unknown)
- **evidence/ddi_clinical.md** — appended §Leuprolide DDI sub-study (TITAN)
- **clinical_studies_index.md** — TITAN promoted from "pending" to "[study page]"; PCR1027/PCR1028 BE studies added to new "Post-approval BE / formulation bridging studies" section
- **apalutamide_index.md** — added link to [[post_approval_variations]] in main TOC

### Stage 5b — High-risk verifier (third-pass facts)

Spot-checked:
- TITAN rPFS HR 0.50 (0.40-0.62): ✓ grounded by EMA Variation p.18 verbatim
- TITAN OS HR 0.69 (0.52-0.92): ✓ grounded
- SPARTAN final OS HR 0.78 (0.64-0.96): ✓ grounded by SUPPL_004 p.19 verbatim
- Severe HI AUC 2.1-fold: ✓ grounded by SUPPL_021 p.15 verbatim
- Severe HI dose 120 mg QD: ✓ grounded by SUPPL_021 p.2 verbatim
- TITAN n=1052 (1051 safety): ✓ grounded by EMA Variation p.9 verbatim
- Leuprolide DDI 42% higher exposure: ✓ grounded

No new quarantine entries.

### Stage 6 — Resolver update

Added canonical study identifier:
- nct02489318 = TITAN = 56021927PCR3002 (Sponsor code variants: PCR3002, 56021927PCR3002)

PCR1027 and PCR1028 added to alias graph but no NCT ids surfaced from EMA EPAR Extension text — slug deferred to next pass.

### Validator (informal spot-check)

- Rule 2 (Tier 2 isolation): no understanding pages were modified this pass; SPARTAN/TITAN study pages contain `[DOC | type | section | p.N]` refs as expected for Tier 1. PASS.
- Rule 6 (verbatim length floor): all new verbatims ≥8 words. PASS.
- Rule 12 (unresolved wikilinks): TITAN study page links to [[studies/clinical/nct01946204]] (exists), [[evidence/ddi_clinical]] (exists), [[evidence/special_populations]] (exists). PASS.

### What's still missing

- Per-study pages for PCR1027 and PCR1028 (BE-bridging studies for 240 mg tablet)
- PMDA Review Report — Japanese registration data
- HC Product Monograph
- TGA AusPAR + PI
- Individual study pages for biopharm studies 006, 1007, 1010, 1011, 1012, 1015, 1017, 1018, 1020, 1021 (still listed as "evidence only" in clinical_studies_index)
- Fix urllib hang in caption_figure.py (engineering follow-up)
- Re-caption ChemR (37 figures) + retry 10 errored figures across other sidecars


## [2026-05-18] Fourth-pass extraction | PCR1028 directly-measured BE intra-subject CV%

### User feedback addressed

"BE studies should be added into BE studies section correspondingly. PK variability data should be updated based on new data."

### Sources extracted this pass

- [[sources/erleada-erleada-h-c-004452-x-0028-g-epar-assessment-report-extension-hybrid|EMA EPAR Extension X/0028/G]] — Section 2.6.3 Clinical Pharmacology pp.21-30 (PCR1027 + PCR1028 full BE results with intra-participant CV%)

### Key new measured values (apalutamide tablet, healthy male volunteers, 2x2 crossover)

- **PCR1028 Part 1 (pivotal BE, N=65/63):** Cmax intra-CV **16.4%**; AUC0-72h intra-CV **6.4%**; G043 240 mg bioequivalent to 4x60 mg G023 (Cmax GMR 109.67% [104.55-115.04], AUC GMR 102.71% [100.78-104.68])
- **PCR1028 Part 2 (food effect on G043, N=20):** Cmax intra-CV 16.7%; AUC0-72h intra-CV 5.2%; food effect on G043 attenuated vs G023 (Cmax GMR 90.96% [83.06-99.61] vs original 1011 G023 0.84 [0.75-0.94])
- **PCR1027 Part 1 (formulation selection, N=13):** Cmax intra-CV 18.6%; AUC intra-CV 4.2%; G043 Cmax 90% CI upper bound 131.20% exceeded BE limit -> motivated formulation refinement

### Pages updated this pass

- **evidence/bioequivalence.md** — new section "Post-approval BE studies (PCR1027 + PCR1028)" with full results tables; source_count bumped to 3
- **evidence/food_effect.md** — new section "240 mg single-tablet (G043) food effect — PCR1028 Part 2"; source_count bumped to 3
- **evidence/formulation.md** — new section "240 mg single-tablet formulation (G043)" with composition + dimensions + BE conclusion
- **understanding/apalutamide-pk-variability.md** — **major revision**: directly-measured intra-CV from PCR1028 supersedes earlier back-calculation; revised sample-size estimates for crossover (~28-30 subjects) and parallel (~75 per arm); added sources-of-variability summary

### Reconciliation: back-calc vs direct measurement

| Parameter | Earlier back-calc (Study 001 N=12) | Direct measurement (PCR1028 N=65) | Status |
|---|---|---|---|
| Apalutamide Cmax intra-CV | ~15.6% (estimated from 90% CI) | **16.4% (measured)** | ✓ back-calc confirmed |
| Apalutamide AUC intra-CV | ~9.5% (estimated from 90% CI) | **6.4% (measured)** | back-calc OVER-estimated; direct value is lower |

The earlier variability article version stands as a methodologic example but the **measured** values are now the load-bearing source for sample-size recommendations.

### Stage 5b — high-risk verifier (PCR1028 facts)

Spot-checked:
- Cmax GMR 109.67% (104.55-115.04): ✓ grounded by EMA Extension p.28 verbatim
- AUC GMR 102.71% (100.78-104.68): ✓ grounded
- Cmax intra-CV 16.4%: ✓ grounded by EMA Extension p.28 verbatim
- AUC intra-CV 6.4%: ✓ grounded
- PCR1027 Cmax 131.20% upper bound exceeded BE: ✓ grounded by p.21 verbatim
- G043 tablet composition (no microcrystalline cellulose): ✓ grounded by p.6 verbatim

No new quarantine entries.

### What's still missing

- PMDA Review Report extraction (Japanese-specific PK)
- HC Product Monograph extraction
- TGA AusPAR + PI extraction
- Per-study pages for PCR1027 and PCR1028 (currently only catalogued in clinical_studies_index)
- Per-study pages for original NDA biopharm studies (006, 1007, 1010, 1011, 1012, 1015, 1017, 1018, 1020, 1021)
- Fix urllib hang in caption_figure.py
- Re-caption ChemR (37 figures hung)


## [2026-05-18] Fifth-pass extraction | PMDA Review Report (Japanese registration)

### Source extracted this pass

- [[sources/pmda-review-report-erleada-apalutamide-hybrid|PMDA Review Report — Erleada / Apalutamide]] (Japanese registration, approved 2019-02-18) — Sections 4, 5.7, 6.1, 6.2, 7.1 (focus on Japanese clinical pharmacology + SPARTAN Japanese subgroup)

### Pages updated

- **evidence/pharmacokinetics.md** — added Japanese-population PK section: Study 21 (Japanese healthy N=18 dose-escalation FC tablet) with full Cmax/AUC/t1/2 table; Study 08 (Japanese mCRPC N=6 steady-state, Cmax 7.57 µg/mL, AUC24h 122 µg·h/mL, accumulation 3.55); PMDA reconciliation of Japanese-vs-non-Japanese PK; population PK covariate refinement (healthy +27% F)
- **evidence/special_populations.md** — added Refined hepatic impairment GMR table (3 sub-tables: total apalutamide, total M3, unbound apalutamide — Study 1018 N=24); Renal impairment SPARTAN subgroup AE analysis (normal 377 / mild 280 / mod-or-severe 141 patients, all-AE 96-97%, Grade>=3 AE 43-48%)
- **understanding/apalutamide-pk-variability.md** — added Study 11 Cmax CV anchor (15.7% fasted / 20.2% fed); now 4 independent Cmax intra-subject CV measurements all converging on 15-18%
- **evidence/pkpd_model.md** — added Study 19 QTc mixed-effects model (delta-QTcF 13.81 ms at Cmax,ss 5.95 µg/mL); added formal pop-PK covariate-selection list
- **studies/clinical/nct01946204.md** (SPARTAN) — appended Japanese subgroup MFS (N=34 apa + 21 placebo, events 5 vs 8, HR 0.565 [0.181, 1.766], p=0.3207, direction-consistent with global ITT)
- **clinical_studies_index.md** — added "PMDA-reviewed Japanese-only studies" section (Studies 21 and 08); updated cross-reference matrix

### Source-count bumps

- evidence/pharmacokinetics.md: 2 -> 3 sources (FDA-MultiR + EMA-EPAR + PMDA-RR)
- evidence/special_populations.md: 3 -> 4 sources (added PMDA-RR for hepatic GMR table + renal subgroup AE)
- evidence/pkpd_model.md: 1 -> 2 sources (PMDA-RR confirms FDA QTc model)

### Reconciliations resolved

- **Japanese ethnic PK:** EMA pop-PK said Japanese vs White AUC GMR 1.14 (modest +14%); PMDA bilateral analysis (Study 08 vs 001 phase I) said "no clear difference". Both views noted in [[evidence/special_populations]]; conclusion: no Japanese-specific dose adjustment warranted.
- **Hepatic impairment exposure:** EMA pop-PK said mild/moderate vs normal AUC GMR 1.02 (0.98-1.05); PMDA's Study 1018 presentation gives exact mild/moderate GMRs 0.95 / 1.13 with wider per-study CIs. Consistent in conclusion (no dose adjustment for mild/moderate HI); the EMA pop-PK is tighter because of larger N.
- **QTc model:** FDA mean QTcF change 12.4 ms (90% upper CI 16.1); PMDA Cmax,ss model gives delta-QTcF 13.81 ms (90% CI 9.77-17.85). Both consistent, both below 20 ms ICH E14 threshold.
- **Healthy-vs-patient differential:** EMA pop-PK AUC GMR 1.42 healthy vs CRPC. PMDA pop-PK F 27% higher in healthy (body-weight + albumin corrected). Same finding from independent analyses.

### Stage 5b — high-risk verifier (PMDA-sourced facts)

Spot-checked:
- Study 21 240 mg Cmax 3.12 +/- 0.745: ✓ grounded by p.34 verbatim
- Study 08 Cmax 7.57 / AUC24h 122: ✓ grounded by p.27 verbatim
- Study 1018 mild HI Cmax GMR 1.02 (0.77-1.34): ✓ grounded by p.39 verbatim
- Study 1018 moderate HI N-desmethyl Cmax GMR 0.73 (0.50-1.07): ✓ grounded by p.39 verbatim
- SPARTAN Japanese subgroup HR 0.565: ✓ grounded by p.54 verbatim
- Study 19 delta-QTcF 13.81 ms: ✓ grounded by p.39 verbatim
- Study 11 fasting Cmax CV 15.7%: ✓ grounded by p.33 verbatim

No quarantine entries.

### Validator informal spot-check

- Rule 2 (Tier 2 isolation): variability article retains only [[wikilinks]]. PASS.
- Rule 6 (verbatim length): all new verbatims >= 8 words. PASS.
- Rule 12 (unresolved wikilinks): [[sources/pmda-review-report-erleada-apalutamide-hybrid]] exists as staged source card. PASS.

### What's still missing (after fifth pass)

- HC Product Monograph (Canadian regulatory perspective — low marginal value, mostly mirrors FDA/EMA label)
- TGA AusPAR + PI (Australian — modest marginal value, partial overlap with EMA)
- EMA Product Information (highly redundant with EPAR coverage)
- DailyMed current label (snapshot aggregating supplements)
- Per-study pages for biopharm studies (006, 1007, 1010, 1011, 1012, 1015, 1017, 1018, 1020, 1021, PCR1008, PCR1027, PCR1028)
- Fix urllib hang in caption_figure.py + re-caption ChemR (37 figures)
