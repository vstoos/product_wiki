---
name: reg-doc-fetching
description: Use when the user wants to retrieve regulatory documents for a specific pharmaceutical substance from one or more national/regional regulatory agencies (FDA, EMA, Health Canada, PMDA, TGA, HMA MRI, PubMed, DailyMed) or to enrich an existing local cache with new sources. This skill discovers, downloads, and caches drug-review PDFs/HTML for a named substance — applying agency-specific search APIs, scraping fallbacks, rate limits, and deduplication. Trigger phrases include "fetch FDA reviews for apalutamide", "download EMA EPAR for Erleada", "get all global regulatory documents for drug X", "find PMDA review report for Y", "add EMA + Health Canada sources to my Z cache", "scrape AusPAR for drug X".
---

# Regulatory Document Fetching

You are operating as the discovery + download tier of the `get_reports` pipeline. The Python implementation lives under `core/*_tools.py`; this skill describes what to fetch from where, how, and where to put it — so you (or any Claude Code instance) can execute the same job inline using `WebFetch`, `Bash` + `curl/wget`, or by orchestrating the existing Python tools.

## What you produce

For each requested substance + agency combination, a directory of cached source documents under a per-agency, per-substance folder:

```
$FDA_DATA_DIR/
├── fda/reviews/<substance>/             # FDA NDA/BLA reviews + PSG + supplements
├── ema/documents/<substance>/           # EMA EPARs (Assessment, Variation, Extension, Product Info, SmPC)
├── health_canada/documents/<substance>/ # HC Product Monograph + Summary Basis of Decision + Reg Decision Summary
├── pmda/documents/<substance>/          # PMDA review reports (English translations)
├── tga/documents/<substance>/           # TGA AusPARs + PI
├── hma/documents/<substance>/           # HMA MRI documents (EU DCP/MRP)
├── pubmed/documents/<substance>/        # PubMed abstracts + PMC full-texts
└── extracted_text/<substance>/          # (Optional) plain-text extracts for non-PDF docs
```

`$FDA_DATA_DIR` defaults to `~/reports-data/data` but is configurable via `.env`. Inside each agency folder, **one document = one file** (PDF or HTML), plus optional sidecars (`.extracted.txt`, `.meta.json`).

## When to use this skill

- Fresh research — user names a drug, wants all major-agency documents
- Cache enrichment — existing local cache for substance X, user wants to add agency Y
- Targeted retrieval — user names a specific document or NDA/EPAR number
- Supplement sweep — user wants post-approval supplement reviews for an FDA NDA

Do NOT use this skill for:
- PDF text/figure/table extraction → that's the `pdf-doc-extraction` skill
- Wiki structuring / fact extraction → that's the `wiki-pharma-extraction` skill
- Synthesis / report writing → that's the Streamlit app pipeline

## Setup before running

1. Read `references/sources.md` — agency-by-agency map of APIs, scraping shapes, what's available.
2. Read `references/source-document-shape.md` — the common descriptor + storage layout.
3. Read `references/quirks-and-gotchas.md` — the bugs that bit us in real runs (DHPP `search=` param, PMC HTML-vs-PDF mix, EMA JSON shape, brotli encoding, etc.).
4. Read `references/retrieval-evidence.md` — how to populate retrieval metadata for downstream audit (URL, retrieval_date, SHA-256, retrieval_tool).

Then ask the user:
- **Substance INN** (e.g. "apalutamide", "roxadustat")
- **Agencies to query** — any subset of FDA, EMA, HC, PMDA, TGA, HMA, PubMed, DailyMed
- **Output root** — defaults to `$FDA_DATA_DIR` (typically `~/reports-data/data`)
- **Force refresh?** — usually skip if a document is already on disk with non-zero size

## Common name → application-number resolution

Drug names map onto numeric identifiers per agency. Resolve these first; subsequent fetches use the IDs.

| Agency | Identifier | How to resolve |
|---|---|---|
| FDA | NDA / BLA / ANDA number | `DrugsAtFDATool.search_by_name(substance)` — searches the Applications.txt local cache or the Drugs@FDA web search |
| EMA | EMEA/H/C/<dossier> | Search `medicines-output-medicines_json-report_en.json` for the trade or INN name |
| HC | DIN(s) + product code | DPD search by name → product detail → DHPP search with `search=` for SBD/PM |
| PMDA | English review report URL | Scrape PMDA's English drug review listing (annually-published index) |
| TGA | AusPAR record | Scrape `tga.gov.au/auspar/search` by name |
| HMA | OData procedure ID | OAuth → OData query on `Procedures?$filter=contains(...)` |
| PubMed | PMID + optional PMC ID | `esearch.fcgi?term="<substance>"[Title/Abstract]` |
| DailyMed | SetID(s) | `dailymed.nlm.nih.gov/dailymed/services/v2/spls.json?application_number=NDA<n>` |

Always cache the resolution result. Substance ↔ ID is stable once approved.

## The 8 agencies — one-liner each

| Agency | What you get | API style | Rate limit |
|---|---|---|---|
| **FDA** | NDA reviews (Approval, ChemR, ClinPharm, Stat, MultidisciplineR, RiskR, PharmR/PharmTox), PSG, Labels, post-approval supplement reviews | accessdata.fda.gov direct PDF URLs + Drugs@FDA scraping | none observed; respect HTTP 429 |
| **EMA** | EPAR Assessment, Variation, Extension, Product Information, SmPC, All Authorised Presentations | Public JSON exports on ema.europa.eu + product-page scraping | ~10 req/min recommended |
| **Health Canada** | Product Monograph (full PDF), Summary Basis of Decision, Regulatory Decision Summary | DPD API + DHPP scraping (use `search=` NOT `query=`) | ~6 req/min |
| **PMDA** | English review reports (annual zip catalogs) | static scraping with year-by-year index | 1 req every 2s |
| **TGA** | AusPAR (assessment report), Product Information | scraping of tga.gov.au | 1 req every 2s |
| **HMA** | DCP/MRP procedures, Public Assessment Reports, EU national authorizations | OAuth + OData (requires API token, register at hma.eu) | 20 req/min |
| **PubMed** | Abstracts via efetch; PMC full-text PDFs where Open Access | NCBI E-utilities (eutils.ncbi.nlm.nih.gov) | 3 req/sec with API key, else 1 req/sec |
| **DailyMed** | Current FDA-approved label (SPL XML rendered as HTML, downloadable as PDF) | DailyMed REST API v2 | ~3 req/sec |

## Procedure (high-level)

For each requested agency:

1. **Resolve substance → identifiers.** Use the agency's primary search endpoint. If multiple matches (e.g. brand + generic), prefer the originator NDA / centralised procedure / brand-name product monograph. Cache the resolution.
2. **List documents.** For each identifier, query the agency's document catalog. Filter to assessment-related artifacts (reviews, monographs, PIs, EPARs, AusPARs). Skip operational artifacts (acknowledgement letters, BLA cover letters, etc.) unless the user asked for them.
3. **Download.** Stream each document to disk under the per-agency, per-substance folder. Filename: agency-prefixed canonical (`SUPPL_005_210951s005lbl.pdf`, `Erleada_-_Erleada___EPAR_-_Public_assessment_report.pdf`) — see `references/sources.md` §FilenameConventions.
4. **Verify.** Check file size > 0 and content-type sane. For PDFs, fast-check the magic bytes (`%PDF-`). For HTML, look for the expected anchor (e.g. EPAR doc title in `<h1>`).
5. **Record retrieval evidence.** Write a sidecar `<filename>.meta.json` with `{retrieval_url, retrieval_date, sha256, agency, doc_type}`. The downstream wiki pipeline reads this for source cards.

When done, emit a per-agency summary: `n_new`, `n_cached`, `n_failed` with reasons.

## Hard constraints (rules the original Python enforces — preserve them)

- **Always honour file-already-on-disk caching** — don't re-download unless the user says force-refresh. Many sources are slow and some throttle aggressively.
- **Don't follow redirects to login walls** — agencies sometimes return a generic homepage when content isn't available; verify content-type and first-bytes before saving.
- **Don't conflate brand names with INN** — `Erleada` is the brand of `apalutamide`; both should resolve to the same EMA dossier and FDA NDA, but the agency endpoints might index one or the other. Try INN first, then brand as a fallback search.
- **Don't trust the listing for filtering** — listings sometimes claim PDFs that 404. Always fetch + verify.
- **Be conservative about supplement filtering** — for FDA NDAs, "all supplements" can return hundreds; default to only those with class codes that indicate full review (e.g. "EA" efficacy, "L" labeling). Skip "C" CMC-only when the user wants clinical/reg-only.
- **Cache scrapes** — sticky listings (PMDA annual index, DHPP class codes) should be cached on disk for 24h to avoid hammering the source.

## Output report format

After fetching, emit:

```
## Fetch summary — <substance>

### Resolved identifiers
- FDA: NDA-210951 (Erleada, apalutamide, Janssen, approved 2018-02-14)
- EMA: EMEA/H/C/004452 (Erleada, centralised, authorised 2019-01-14)
- HC: DIN 02482175 (Erleada, Janssen Canada)
- PMDA: Erleada (Janssen K.K., approved 2019-03-26)
- TGA: AusPAR PM-2018-00489 (Erlyand/Janssen)
- HMA: (not applicable — centralised EMA procedure, not DCP/MRP)
- PubMed: 17 abstracts + 4 PMC full-texts
- DailyMed: 3 SPL versions

### Documents downloaded
- FDA: 7 review files + 14 supplements (= 28 PDFs total)
- EMA: 6 documents (EPAR Public Assessment, EPAR Extension, EPAR Variation, Product Info, All Auth Presentations, SmPC)
- HC: 3 documents (Product Monograph, Summary Basis of Decision, Reg Decision Summary)
- PMDA: 1 document (English Review Report)
- TGA: 2 documents (AusPAR, PI)
- PubMed: 17 abstracts + 4 PMC full-texts (21 files)
- DailyMed: 1 label PDF (current)

### Failures
- (Per-agency reason, if any)
```

## What NOT to do

- Don't use search engines (Google, Bing) for primary discovery. Agency-direct APIs/sites are authoritative.
- Don't follow third-party drug-info sites. Wikipedia, drugs.com, pharmaceutical-online are NOT primary sources.
- Don't store anything outside `$FDA_DATA_DIR`'s per-agency subtree.
- Don't paraphrase or post-process the documents in this skill — that's the next skill's job.
- Don't bypass user-requested agency lists. If they said "only EMA + HC", don't fetch FDA.
- Don't run the multi-source pipeline silently — show per-agency progress so the user can interrupt slow agencies.

## Resources

- `references/sources.md` — per-agency detailed search/download contracts
- `references/source-document-shape.md` — common `SourceDocument` dataclass + storage layout
- `references/quirks-and-gotchas.md` — bugs that bit us in production
- `references/retrieval-evidence.md` — sidecar JSON shape, SHA-256, URL preservation

The Python implementation (read for cross-reference, don't run): `core/fda_tools.py`, `core/ema_tools.py`, `core/hc_tools.py`, `core/pmda_tools.py`, `core/tga_tools.py`, `core/hma_tools.py`, `core/pubmed_tools.py`, `core/dailymed_tools.py`, `core/fda_supplements.py`, `core/review_finder.py`, `core/source_registry.py`.
