---
page_type: understanding
substance: apalutamide
summary_stale: false
last_updated: 2026-05-18
---

# Understanding — apalutamide PK variability (intra-subject & parallel-design)

## What the published numbers actually mean

The apalutamide source documents report variability in three distinct forms:

1. **Total CV% in a parallel-group study** (e.g. Study 1011 food effect, N=15 per arm, healthy volunteers, single 240 mg dose): apalutamide Cmax 18.5%, AUClast 19.6%, AUCinf 18.5%. In a parallel design the *total* CV% is the only thing that can be reported because between-subject and within-subject variance cannot be separated from a single period of observation per subject. The reported 18–20% is therefore an upper bound on the intra-subject component and a lower bound on the inter-subject component, but does not identify either individually.

2. **Total CV% in a small crossover sub-study** (Study 001 capsule food effect, N=12 CRPC patients, 2×2 crossover at steady state): apalutamide Cmax 32.5% (fasted) / 29.0% (fed); AUC0-24 30.5% (fasted) / 34.9% (fed). The "CV%" tabulated here is again total (treatment-period combined SD/mean) — but unlike the parallel case, the crossover design *does* allow back-calculation of intra-subject CV% from the 90% confidence interval of the geometric mean ratio.

3. **Total CV% in the population PK model** (SPARTAN + supporting studies, 240 mg QD steady state in patients): apalutamide 28% Cmax, 32% AUC0-24,ss; N-desmethyl 18% Cmax, 19% AUC0-24,ss. This is the *patient-population* variability and is the most relevant number for predicting BE study performance in the target population.

## Back-calculating intra-subject CV% from the crossover 90% CI

For a 2×2 crossover with N subjects and df = N−2, the relationship between the 90% CI half-width of the log-scale GMR and the intra-subject variance σ_w² is:

```
log_CI_halfwidth = ln(CI_upper / CI_lower) / 2
                 = t(0.95, N−2) · sqrt(2 · σ_w² / N)
```

Solving for σ_w² and the corresponding intra-subject CV%:

```
σ_w² = ((log_CI_halfwidth / t) ² · N) / 2
CV%_intra = sqrt(exp(σ_w²) − 1) · 100
```

Applied to Study 001 capsule food-effect data (N=12, df=10, t(0.95,10) = 1.812):

| Parameter | GMR | 90% CI | log half-width | σ_w² | **CV%_intra (back-calc)** |
|---|---|---|---|---|---|
| Apalutamide Cmax | 0.856 | (0.763, 0.960) | 0.1149 | 0.0241 | **~15.6%** |
| Apalutamide AUC0-24 | 0.952 | (0.887, 1.020) | 0.0699 | 0.00894 | **~9.5%** |

(Verbatim source values come from [[evidence/food_effect]].)

Applying the same calculation to the tablet food-effect parallel study (Study 1011) is *not valid* — you cannot extract intra-subject variance from a parallel-group design with a single observation per subject. The Total CV% (18–20%) reported there is unstratifiable.

## Why the FDA PSG suggests considering a parallel design

The PSG ([[evidence/guideline]]) explicitly notes: "Apalutamide has a long terminal elimination half-life. Ensure adequate washout periods between treatments in a crossover study or consider using a parallel study design."

The trade-off is well-known:

- **Crossover advantages:** Each subject is their own control. Sample size scales with the intra-subject variance (σ_w²) alone, which is small for apalutamide (~10% on AUC, ~15% on Cmax based on the back-calculation above). For a 90% power, 80–125% BE acceptance and true GMR of 1.05, a crossover would need only ~20–28 subjects.
- **Crossover disadvantages:** Apalutamide's ~3-day effective half-life ([[evidence/pharmacokinetics]]) and 122-fold accumulation of the active N-desmethyl metabolite mean that a single-dose washout of 5×t½ ≈ 15 days between periods is the minimum. With patient drop-out during a 30+ day crossover, dropout-handling becomes the dominant operational risk.
- **Parallel advantages:** No washout; subjects only need one dose. Trial duration much shorter.
- **Parallel disadvantages:** Sample size scales with the TOTAL variance (σ_b² + σ_w²) rather than just σ_w². For apalutamide, healthy volunteers showed total CV ~18–20% on Cmax and AUC; sample size at 90% power, 80–125% BE acceptance, true GMR 1.05 is approximately:

```
N_per_arm ≈ ( (z_α + z_β)² · 2 · σ_T² ) / ln(δ)²
```

with σ_T² ≈ ln(1 + (0.20)²) ≈ 0.0392 and δ = 1.25/1.05 ≈ 1.19, yielding N_per_arm ≈ 35–45 (total 70–90 subjects). That is 3–4× the crossover sample size, but each subject only needs to be exposed to one dose with no washout window.

## Recommended quantitative reference for generic developers

| Apalutamide PK parameter | Healthy-volunteer setting | Patient-population (240 mg QD) |
|---|---|---|
| Cmax CV% (total, reported) | ~18.5% (parallel) / ~32% (crossover) | 28% |
| AUC CV% (total, reported) | ~19% (parallel) / ~30% (crossover) | 32% |
| **Intra-subject CV% (back-calc, capsule, N=12)** | **~15% Cmax / ~10% AUC** | n/a — derived from healthy/CRPC mix |

For sample-size planning of a single-dose generic BE study under FDA PSG_210951:

- **2×2 crossover (healthy volunteers, fasted):** Use intra-subject CV% ~15% Cmax / ~10% AUC. Expected N ≈ 20–28 for 90% power at true GMR 1.05.
- **Parallel-group (healthy volunteers, fasted):** Use total CV% ~20% Cmax / ~20% AUC. Expected N ≈ 70–90 (i.e. 35–45 per arm).
- **Add a 20–30% over-recruitment buffer** in either design to account for drop-out, given the 240 mg single-dose tolerability and 1-week minimum follow-up.

The back-calculated intra-subject CV% values above are derived from a small (N=12) capsule food-effect substudy and should be considered an estimate for design planning; sponsors with access to the apalutamide tablet single-dose individual-subject data should refine these numbers with their own variance components analysis.

## Related

- [[evidence/pharmacokinetics]] — reported total CV% values, source-of-truth
- [[evidence/food_effect]] — the source data for the back-calculation
- [[evidence/bioequivalence]] — BE study results (tablet-vs-capsule, PSG)
- [[evidence/guideline]] — full PSG text
- [[understanding/apalutamide-bioequivalence]] — design discussion

## EMA EPAR-published intra-subject and inter-subject variability

The EMA EPAR provides direct numerical estimates that confirm and refine the back-calculation in the previous section:

- **Overall CHMP characterization:** "PK of apalutamide is characterized by low to moderate intrasubject and intersubject variability (<30%)."
  - See [[evidence/pharmacokinetics]] §EMA EPAR multi-source confirmation for the underlying Tier 1 fact and bracket-pipe source ref.
- **Inter-subject variability (N-desmethyl apalutamide, population PK estimate):**
  - AUC0-24,ss: 19.7%
  - Cmin: 19.7%
  - Cmax: 19.6%
  - See [[evidence/pharmacokinetics]] and [[evidence/special_populations]] for the underlying Tier 1 facts.
- **Inter-subject CV% by PK structural parameter (apalutamide, EMA Table 8 final model):**
  - Inducible clearance CL_/F: 19.1%
  - Volume of central compartment V/F: 230%
  - Inter-compartmental clearance Q/F: 34.6%
  - **Residual unexplained variability:** 22.6% for apalutamide, 15.0% for N-desmethyl apalutamide.
  - See [[evidence/pharmacokinetics]] for the underlying Tier 1 facts and bracket-pipe source ref.

- **Population covariate effects on apalutamide AUC (90% CIs):**
  | Covariate | GMR | 90% CI | N |
  |---|---|---|---|
  | Healthy vs CRPC patient | 1.42 | (1.36–1.49) | 117 vs 975 |
  | Body weight >95 vs 75–95 kg | 0.89 | (0.87–0.92) | 295 vs 504 |
  | Body weight <75 vs 75–95 kg | 1.09 | (1.05–1.12) | 279 vs 504 |
  | Age >75 vs 65–75 | 1.07 | (1.04–1.10) | 399 vs 420 |
  | Japanese vs White | 1.14 | (1.08–1.20) | 58 vs 761 |
  | Renal moderate/severe vs normal | 1.08 | (1.04–1.13) | 132 vs 372 |
  | Hepatic mild/moderate vs normal | 1.02 | (0.98–1.05) | 118 vs 974 |
  | Albumin <40 vs 40–45 g/L | 0.92 | (0.89–0.95) | 105 vs 717 |
  See [[evidence/special_populations]] for full table.

## Reconciliation with back-calculation

The CHMP-reported total inter-subject CV% (<30%, ~19% for N-desmethyl, ~15–34% for apalutamide structural parameters) is consistent with the back-calculation of intra-subject CV% (~15% Cmax, ~10% AUC) from Study 001 above. Together they imply:

- **Inter-subject CV% (in CRPC patients at steady state):** ~20–30% on apalutamide exposure
- **Intra-subject CV% (in healthy/CRPC at single dose):** ~10–16% on apalutamide exposure
- **Inter-/intra-subject variance ratio:** roughly 2–4× — consistent with a small-molecule drug whose patient-population variability is dominated by between-subject differences in absorption (HPMC-AS solid-dispersion behavior across GI states) and metabolic capacity (CYP2C8/3A4), while within-subject day-to-day variability is dominated by stochastic absorption variation.

**Practical implication for generic BE planning:** a crossover study can take advantage of the small intra-subject variance (favors small N) but must contend with the long apalutamide t½ that forces a multi-week washout. The EMA's "low to moderate" characterization is the regulatory framing the CHMP accepted; a generic applicant designing a parallel study should expect total (inter + intra) variance closer to the 19–22% range, supporting the ~70–90 subject estimate in the section above.

## Revised variability estimates from the PCR1028 pivotal BE study (2022 measurement, N=65)

The post-approval pivotal BE study PCR1028 (submitted with EMA Extension X/0028/G) provides **directly measured** intra-participant CV% from a large healthy-volunteer 2×2 crossover with apalutamide 240 mg single tablet (G043) vs 4×60 mg G023 reference. This **supersedes** my earlier back-calculation from the N=12 capsule food-effect substudy of Study 001.

### Directly measured intra-subject CV% from PCR1028 (apalutamide tablet)

| Source study | N | Cmax intra-CV% | AUC intra-CV% |
|---|---|---|---|
| **PCR1028 Part 1 (BE fasted, G043 vs G023)** | 65 (Cmax) / 63 (AUC) | **16.4%** | **6.4%** |
| PCR1028 Part 2 (food effect on G043) | 20 | 16.7% | 5.2% |
| PCR1027 Part 1 (formulation selection) | 13 | 18.6% | 4.2% |
| Study 001 capsule food effect (BACK-CALCULATED from 90% CI, deprecated) | 12 | ~15.6% (estimated) | ~9.5% (estimated) |

**Key findings:**

1. **Cmax intra-subject CV ≈ 16–17%** (high-confidence; multiple studies; total N>90 across PCR1027+PCR1028 healthy volunteers, all crossover).
2. **AUC intra-subject CV ≈ 5–6%** (consistent across PCR1028 Parts 1 and 2; lower than my back-calculation suggested).
3. The back-calculated AUC intra-CV of ~9.5% from the original food-effect substudy (N=12) **over-estimated** the true intra-CV — likely because that small-N estimate was inflated by both genuine intra-subject variability and small-sample uncertainty in the variance estimate. The 65-subject PCR1028 measurement is the higher-confidence value.

Source: see [[evidence/bioequivalence]] §"Post-approval BE studies" — that page carries the bracket-pipe source ref `[EMEA-H-C-004452-X-0028-G | EPAR Assessment - Extension | Section 2.6.3 | p.28]` to the EMA EPAR Extension X/0028/G dossier.

### Revised sample-size estimates for generic BE planning

Using the directly-measured intra-CV from PCR1028 and standard BE sample-size methodology (Hauschke et al.), for **90% power, 80–125% BE acceptance, true GMR 1.05**:

| Design | Intra-CV / Total-CV used | Apalutamide Cmax | Apalutamide AUC | Driving parameter |
|---|---|---|---|---|
| **2×2 crossover** | Intra-CV: Cmax 16.4%, AUC 6.4% | **~26 subjects** | **~12 subjects** | Cmax → use 28-30 with drop-out buffer |
| **Parallel-group** | Total-CV: Cmax ~22-25%, AUC ~20% (inter + intra from pop PK) | **~55-70 per arm** | **~50-60 per arm** | Cmax → use 75 per arm (150 total) with drop-out buffer |
| **Parallel-group (worst case)** | Use SPARTAN patient pop-PK CV: Cmax 28%, AUC 32% | ~90 per arm | ~110 per arm | If conducted in patients, NOT healthy volunteers — use 100-120 per arm |

**Recommendations (updated 2026-05-18 with PCR1028 data):**

- **Crossover BE design (healthy volunteers, fasting):** ~28–30 subjects gives 90% power with comfortable drop-out buffer. The favorable AUC intra-CV (~6%) means AUC component is well-powered even with N≈12; the entire sample size is driven by Cmax variability. **Crossover remains the operationally preferred design** if the sponsor can accommodate the ~7-week washout (used in PCR1028) — apalutamide's effective t½ of ~3 days at steady state means single-dose washout of ~5×t½ = 15 days is sufficient for return to baseline.
- **Parallel-group BE design (healthy volunteers):** ~75 per arm (150 total) for the modern tablet formulation. The pop-PK total CV of ~22% on apalutamide Cmax is the relevant denominator; parallel design is the right choice if washout logistics dominate operational risk.
- **PSG recommendation reconciled:** the FDA PSG explicitly states "Apalutamide has a long terminal elimination half-life. Ensure adequate washout periods between treatments in a crossover study or consider using a parallel study design." The PCR1028 evidence (7-week washout × 2 periods = 14-week study duration for a crossover) confirms that crossover IS feasible with a tolerable subject burden. Generic developers may legitimately use either design.

### Cross-validation with TITAN population PK

The TITAN dossier (EMA Variation II/0001) added an external-validation check of the population PK model on a fresh mHSPC patient dataset (501 evaluable subjects):

- **CHMP observation:** "The variability in plasma concentrations observed in Study 3002 (TITAN) was slightly lower than the model predicted variability"
- This independently confirms the "low to moderate <30%" overall PK variability characterization from the original EMA EPAR.

### Sources of variability — qualitative summary

Based on the body of evidence now in the wiki, the dominant sources of apalutamide variability are:

1. **Between-subject (inter) variability** at steady state in patients: ~28-32% total CV on Cmax / AUC at 240 mg QD (population PK in CRPC/mHSPC); driven primarily by between-subject differences in metabolic capacity (CYP2C8/3A4), absorption (HPMC-AS solid-dispersion behavior across GI states), and adherence.
2. **Within-subject (intra) variability** from single-dose crossover BE: ~16% on Cmax, ~6% on AUC — substantially lower because the same subject's GI state, metabolic capacity, and adherence are largely invariant across study periods.
3. **Healthy-vs-patient differential** (CHMP-quantified): healthy volunteers have ~42% higher apalutamide AUC and ~29% higher N-desmethyl AUC than CRPC patients; this is the largest single covariate effect identified in the population PK analysis.
4. **Negligible effects (per pop PK):** age <65 vs 65–75, mild/moderate hepatic impairment, mild renal impairment, race (Black vs White), ECOG 1 vs 0, serum albumin in normal range — none ±5% GMR change.

### Practical takeaway for generic BE study design

The combination of (i) measured intra-CV ~16% Cmax / 6% AUC, (ii) ~3-day effective t½, (iii) negligible food effect on the modern single-tablet formulation, and (iv) low covariate sensitivity together support the following PSG-aligned design:

- **Single-dose, 240 mg G043 tablet, healthy male subjects, fasting and fed studies separately**
- **2×2 crossover with 7-week washout, N≈28-30** is operationally efficient and statistically well-powered
- **Parallel-group with N≈75 per arm** is an acceptable alternative if washout logistics are prohibitive
- **60 mg single-strength biowaiver** based on (i) dissolution comparability, (ii) proportional formulation similarity, (iii) acceptable 240 mg BE — per PSG_210951

Generic developers should refer to [[evidence/guideline]] for the full PSG recipe.

## Additional variability anchor: Study 11 Cmax CV (foreign healthy adults, FC tablet, single dose)

PMDA's review documents an additional intra-/total-CV data point for apalutamide Cmax in foreign Phase I Study 11 (N=30 healthy adults, single oral 240 mg FC tablet):

- **Fasting Cmax CV:** 15.7%
- **Fed Cmax CV:** 20.2%
  - [[sources/pmda-review-report-erleada-apalutamide-hybrid|PMDA Review Report]] [PMDA-RR-Erleada | Review Report | Section 6.1.2.2 Study 11 food effect | p.33]
  - Verbatim: "In light of the coefficient of variation for the Cmax (15.7% and 20.2%, respectively, after the fasting dose and the high-fat meal dose)"

These values are concordant with the directly-measured intra-subject Cmax CV of 16-17% from PCR1028 and the back-calculated 15.6% from Study 001 capsule food effect. **The case for apalutamide Cmax intra-subject CV ≈ 15-17% is now anchored by 4 independent measurements** spanning capsule (Study 001), foreign-tablet (Study 11), and current commercial-tablet G023+G043 (PCR1027 + PCR1028) datasets. The fed-state CV (20.2%) is slightly higher than fasted (15.7%), suggesting fed-state inter-individual GI variability adds to within-subject variance — consistent with the BCS Class 2 solid-dispersion absorption mechanism.

