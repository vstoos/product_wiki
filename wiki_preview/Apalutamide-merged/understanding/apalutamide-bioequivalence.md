---
page_type: understanding
substance: apalutamide
summary_stale: false
last_updated: 2026-05-18
---

# Understanding — apalutamide bioequivalence

## Design constraints set by the molecule

Apalutamide has an effective steady-state half-life of about three days ([[evidence/pharmacokinetics]]), driven by autoinduction of CYP3A4 and a 122-fold accumulation of the active N-desmethyl metabolite. This long t½ is the single most important driver of generic BE study design: a standard 2×2 crossover at therapeutic dose would require a washout on the order of 5×t½ = 15 days to reach <3% residual concentration before the second period. In practice the [[evidence/guideline|FDA PSG]] explicitly flags this and gives the sponsor a choice — adequate washout in a crossover OR a parallel-group design.

## The single-dose, fasted-and-fed framing

Even with the long half-life, the PSG specifies a *single-dose* BE study (not steady-state), which is the more sensitive design for detecting formulation differences in absorption rate (Cmax). The mandated analyte is apalutamide in plasma; N-desmethyl is not required for BE because it forms downstream of absorption and its formation rate is rate-limited by the parent's metabolic clearance. Two studies are required — fasted and fed — because the to-be-marketed tablet has a small (~16% Cmax) but statistically distinguishable food effect ([[evidence/food_effect]]) even though the FDA reviewer concluded "no clinically relevant food effect" at the therapeutic dose.

## Why the tablet/capsule bridging was "almost BE"

The originator's own tablet-vs-capsule comparison (Study 1011) returned a Cmax GMR of 0.90 with a 90% CI of 0.79–1.03 ([[evidence/bioequivalence]]). The lower CI bound (0.79) sits just outside the strict 80–125% BE acceptance window. The FDA reviewer accepted this as "almost BE" with no clinically relevant exposure difference, in large part because (i) AUC ratios were comfortably inside 80–125%, (ii) the Phase 3 efficacy data with the tablet were robust independent of the bridging, and (iii) the population PK showed flat exposure-MFS relationships ([[evidence/pkpd_model]]). For a *generic* applicant the same Cmax bracket would not be accepted — a generic must meet the strict 80–125% window on both Cmax and AUC.

## 60 mg waiver

The 60 mg strength does not require its own in vivo BE study, provided the 240 mg BE is acceptable, comparative dissolution is acceptable, and the formulations are proportionally similar ([[evidence/guideline]]). This is the standard FDA biowaiver criterion for proportionally similar strengths of an immediate-release oral solid.

See also [[understanding/apalutamide-pk-variability]] for the intra-subject CV% values that drive BE study sample size, and [[bcs-classification]] for the BCS framing that motivates the dissolution-comparability requirement.
