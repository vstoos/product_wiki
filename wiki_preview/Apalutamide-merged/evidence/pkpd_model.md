---
page_type: pkpd_model
substance: apalutamide
confidence: single-source
source_count: 2
staled: false
last_updated: 2026-05-18
---

# PK/PD modeling — apalutamide

## Exposure–efficacy (MFS)

- **No statistically significant exposure-MFS relationship** in NM-CRPC at 240 mg QD (Study ARN-509-003 / SPARTAN).
  - [[sources/210951orig1s000multidiscipliner-hybrid|FDA Multidisciplinary Review]] [NDA-210951-MultiR | Clinical Pharmacology — Exposure-response | p.67]
  - Verbatim: "No statistically significant exposure-MFS relationship was found for apalutamide and N- desmethyl apalutamide in study 003."

## Exposure–safety (AEs and dose-reduction model)

- **Model-based incidence predictions** indicate dose reduction to 180 or 120 mg QD lowers fatigue/fall/rash/arthralgia incidence (Table 5 of the source).
- **AE-driven dose-reduction conclusion:** 180 / 120 mg dose reductions per protocol were appropriate for subjects experiencing dose-limiting AEs.
  - [[sources/210951orig1s000multidiscipliner-hybrid|FDA Multidisciplinary Review]] [NDA-210951-MultiR | Clinical Pharmacology — Dose reduction model | p.67]
  - Verbatim: "The model results suggested that dose reduction as implemented in study 003 by reducing apalutamide dose to 180 mg, or 120 mg once daily per study protocol, was appropriate for subjects who experience an AE."

## Concentration–QTcF exposure-response

- **ΔQTcF model:** Concentration-dependent QTcF increase; both apalutamide and N-desmethyl contribute.
  - [[sources/210951orig1s000multidiscipliner-hybrid|FDA Multidisciplinary Review]] [NDA-210951-MultiR | Clinical Pharmacology — QT analysis | p.68]
  - Verbatim: "An exposure-QT analysis suggested a concentration-dependent increase in QTcF for apalutamide and its active metabolite"

## Concentration-QTcF mixed-effects model (Study 19 / PCR1019, PMDA presentation)

PMDA's review provides the QTc-prolongation model estimate at steady-state Cmax:

- **At Cmax,ss = 5.95 µg/mL (apalutamide 240 mg QD steady state):** ΔQTcF (90% CI) = **13.81 ms (9.77, 17.85)**.
  - [[sources/pmda-review-report-erleada-apalutamide-hybrid|PMDA Review Report]] [PMDA-RR-Erleada | Review Report | Section 6.2.6 QT/QTc | p.39]
  - Verbatim: "In patients who orally received apalutamide 240 mg QD, ΔQTcF [90% CI] (ms) at Cmax,ss (5.95 µg/mL) of apalutamide was estimated to be 13.81 [9.77, 17.85]"
- **Interpretation:** Confirms the FDA Multidisciplinary Review's maximum mean ΔQTcF of 12.4 ms (90% upper CI 16.1 ms). The two estimates are consistent — FDA's value uses the per-time-point max, PMDA's uses the steady-state Cmax fit. Both place the upper 90% CI bound at ~16–18 ms, comfortably below the 20 ms ICH E14 threshold of regulatory concern.

## Population PK refinement on covariate selection (PMDA review)

The PMDA-reviewed pooled population PK analysis (Studies 08, 21, 003, 11, 18, 19, 001; N=1092) selected the following statistically significant covariates:

- **Bioavailability (F):** body weight, serum albumin, **health status (healthy vs CRPC)**
- **Apalutamide peripheral volume Vp/F:** body weight
- **N-desmethyl inter-compartmental clearance Qm/F:** health status

Notably absent from the significant-covariate list: age, race, eGFR (renal function), AST/ALT/ALP/bilirubin (hepatic enzymes), ECOG performance status, CYP2C8-inducer co-medication, CYP3A-inducer co-medication. This is the formal statistical confirmation behind the EMA covariate forest plot in [[evidence/special_populations]].

  - [[sources/pmda-review-report-erleada-apalutamide-hybrid|PMDA Review Report]] [PMDA-RR-Erleada | Review Report | Section 6.2.7 PPK covariate selection | p.40]

