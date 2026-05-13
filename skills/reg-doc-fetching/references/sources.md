# Sources — per-agency reference

For each agency: search endpoint, document types, download endpoint, output filename convention.

## FDA (United States)

### Drugs@FDA — review documents per NDA/BLA

**Search by name:**
- Local cache: `Applications.txt` from `https://www.accessdata.fda.gov/cder/Applications.zip` (≈100 MB, updated daily). Refresh once per week.
- Web search: `https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?event=overview.process&ApplNo=<APPL_NO>` (after resolving via name search)
- Class `DrugsAtFDATool.search_by_name(query)` returns rows from Applications.txt with column DrugName, ActiveIngredient, ApplNo, etc.

**Direct PDF URLs (Drugs@FDA-style):**

```
https://www.accessdata.fda.gov/drugsatfda_docs/nda/<year>/<APPL_NO>Orig1s000<SUFFIX>.pdf
https://www.accessdata.fda.gov/drugsatfda_docs/label/<year>/<APPL_NO>s<N>lbl.pdf
https://www.accessdata.fda.gov/drugsatfda_docs/appletter/<year>/<APPL_NO>Orig1s<N>ltr.pdf
```

**Standard NDA review document suffixes** (we keep these as filename pieces):
- `Approv.pdf` — Approval Letter (always small, ~50-300 KB)
- `ChemR.pdf` — Chemistry/Product Quality Review
- `ClinPharmR.pdf` — Clinical Pharmacology Review
- `StatR.pdf` — Statistical Review
- `MedR.pdf` — Clinical Review
- `PharmR.pdf` (older) or `PharmToxR.pdf` — Pharmacology/Toxicology
- `MultidisciplineR.pdf` — Integrated Multidisciplinary Review (post-2017 NDAs)
- `RiskR.pdf` — Risk Assessment Review
- `CrossR.pdf` — Cross-discipline Team Leader Review
- `SumR.pdf` — Summary Review
- `OfficeDir.pdf` — Office Director Memo

**Not every NDA has every doc.** For new drugs after ~2017, expect `MultidisciplineR` instead of separate ClinPharm + Stat + Pharm/Tox reviews.

### Product-Specific Guidance (PSG)

For generic development. One PSG per NDA, drafted/recommended dissolution + BE study design.

- Search: `https://www.accessdata.fda.gov/scripts/cder/psg/index.cfm` (HTML scrape)
- Download: `https://www.accessdata.fda.gov/drugsatfda_docs/psg/<filename>.pdf`
- Filename: `PSG_<APPL_NO>.pdf`

### Post-approval supplements

For each NDA, FDA publishes supplemental review docs (labeling updates, indication expansions). Class codes:

| Code | Meaning | Include by default? |
|---|---|---|
| `EA` | Efficacy supplement, full review | yes |
| `E1` | Efficacy supplement, limited review | yes |
| `L` | Labeling change only | yes (small files, but informative) |
| `M` | Manufacturing change | optional |
| `C` | CMC/labeling (chemistry) | optional |
| `B`/`SBA` | Sponsor-burdened administrative | no |

For each supplement, expect two docs: an approval letter (`<N>ltr.pdf`) and the updated label (`<N>lbl.pdf`).

`FDASupplementFinder.list_supplements(<appl_no>)` returns dicts with `submission_no`, `class_code`, `submission_date`, etc.

**Output filename:** `SUPPL_<N>_<appl_no>s<N>lbl.pdf` and `SUPPL_<N>_<appl_no>Orig1s<N>ltr.pdf`. Keeping the original naming preserves uniqueness across supplements with the same date.

### Output directory

```
$FDA_DATA_DIR/fda/reviews/<substance>/
├── 210951Orig1s000Approv.pdf
├── 210951Orig1s000ChemR.pdf
├── 210951Orig1s000MultidisciplineR.pdf
├── PSG_210951.pdf
├── SUPPL_001_210951s001lbl.pdf
├── SUPPL_001_210951Orig1s001ltr.pdf
├── ...
```

## EMA (European Medicines Agency)

### Medicines + EPAR catalog

EMA publishes two public JSON exports daily:

- Medicines list: `https://www.ema.europa.eu/en/documents/report/medicines-output-medicines_json-report_en.json`
- EPAR documents list: `https://www.ema.europa.eu/en/documents/report/documents-output-epar_documents_json-report_en.json`

Both have shape `{"data": [...], "meta": {...}}`. Cache these locally (refresh once per day).

### Search by substance

1. Filter medicines list by `inn` field for the substance INN (lowercased contains-match)
2. Get the medicine's `permanent_url` slug (e.g. `erleada`)
3. From the EPAR documents list, filter by medicine slug
4. Each match has `document_type`, `language`, `url`, `published_date`

### Standard EMA document types

- `EPAR Assessment` — initial CHMP assessment report (the meaty 100-300 page doc)
- `EPAR Assessment — Variation` — post-approval variation assessment (one per major variation)
- `EPAR Assessment — Extension` — line extension (new dosage form / strength)
- `EPAR Product Information` — SmPC + labeling + leaflet (annex I, II, IIIA, IIIB)
- `EPAR All Authorised Presentations` — table of MA numbers + strengths + forms
- `EPAR Public Assessment Report` — newer terminology, sometimes synonymous with EPAR Assessment

### Download

Each document's `url` field is a direct PDF link on `ema.europa.eu`. Just `curl` it.

### Output directory

```
$FDA_DATA_DIR/ema/documents/<substance>/
├── Erleada_-_Erleada___EPAR_-_Assessment_Report_-_Variation.pdf
├── Erleada_-_Erleada___EPAR_-_Public_assessment_report.pdf
├── Erleada_-_Erleada___EPAR_-_Product_information.pdf
├── Erleada_-_Erleada___EPAR_-_All_authorised_presentations.pdf
├── Erleada_-_Erleada-H-C-004452-X-0028-G___EPAR_-_Assessment_report_-_Extension.pdf
├── Erleada_-_Erleada-H-C-4452-II-0001___EPAR_-_Assessment_Report_-_Variation.pdf
├── Erleada_-_EMA_Product_Page.html
```

The `..._EMA_Product_Page.html` is the human-readable EMA product page (`https://www.ema.europa.eu/en/medicines/human/EPAR/<slug>`). Snapshot once for source-card metadata (sponsor, approval date, INN).

## Health Canada

### Drug Product Database (DPD)

REST-ish API at `https://health-products.canada.ca/api/drug/`. Search by name:

```
GET /api/drug/drugproduct/?lang=en&type=json&brandname=<query>
GET /api/drug/drugproduct/?lang=en&type=json&activeingredient=<query>
```

Returns list of DIN records with `drug_code`, `brand_name`, `active_ingredient_id`, `sponsor`, `class_name`, etc. One DIN per strength/form, so 1 substance often has 2-5 DINs.

### Product Monograph (full PDF) + Reg Decision Summary

DPD product detail page (`/drug-product/details/<drug_code>`) has links to the official Product Monograph PDF. Scrape the page; the PM is in a `<a href="...">` with text "Product Monograph".

### DHPP (Drug and Health Product Portal) — SBD + Reg Decision Summary

```
GET https://hpr-rps.hres.ca/?ds=1&search=<query>&lang=en
```

**KNOWN QUIRK (do not miss):** use `search=`, NOT `query=`. The `query` parameter is silently ignored and returns the default global listing.

Returns HTML; scrape `<a href="/details/...">` records. Each has links to:
- Summary Basis of Decision (SBD) — narrative justification for approval, sometimes hundreds of pages
- Regulatory Decision Summary (RDS) — shorter administrative summary

### Output directory

```
$FDA_DATA_DIR/health_canada/documents/<substance>/
├── Product_Monograph_-_ERLEADA.pdf
├── Summary_Basis_of_Decision_for_Erleada.html
├── Regulatory_Decision_Summary_for_Erleada.html
```

HC docs are often HTML for SBD/RDS and PDF for Product Monograph. Keep both formats.

## PMDA (Pharmaceuticals and Medical Devices Agency, Japan)

### English review reports

PMDA publishes annual ZIP files of English-translated review reports:

```
https://www.pmda.go.jp/files/000XXXXXX.pdf
```

Index pages by year at `https://www.pmda.go.jp/english/review-services/reviews/approved-information/drugs/0001.html` (and subsequent pagination). Scrape once per quarter; cache.

For each year's index, each row has substance name, NDC/JANID, PDF URL.

### Output directory

```
$FDA_DATA_DIR/pmda/documents/<substance>/
└── PMDA_Review_Report_-_Erleada_Apalutamide.pdf
```

## TGA (Therapeutic Goods Administration, Australia)

### AusPAR (Australian Public Assessment Report)

Search the AusPAR catalog: `https://www.tga.gov.au/auspar/search`. POST form with substance name. Returns HTML.

For each AusPAR record, scrape its detail page to get:
- AusPAR PDF (assessment report)
- PI (Product Information)
- Sometimes a separate Consumer Medicine Information

### Output directory

```
$FDA_DATA_DIR/tga/documents/<substance>/
├── TGA_AusPAR_-_AusPAR_Apalutamide.pdf
├── TGA_PI_-_AusPAR_Apalutamide.pdf
```

## HMA (Heads of Medicines Agencies — EU MRI for DCP/MRP)

For drugs authorised via **decentralised** or **mutual-recognition** procedures (NOT centralised — those are EMA).

### OAuth + OData

1. Register an API client at `https://www.hma.eu/about-hma/working-parties/data-management/api.html` (manual; admin grants tokens)
2. Get JWT via OAuth2 token endpoint
3. OData query:

```
GET https://api.hma.eu/odata/Procedures?$filter=contains(ActiveIngredient,'<substance>')
```

Returns procedure records with linked documents.

### Output directory

```
$FDA_DATA_DIR/hma/documents/<substance>/
└── <procedure_id>_<document_type>.pdf
```

## PubMed (NCBI E-utilities)

### Abstract search

```
GET https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi
    ?db=pubmed
    &term=%22<substance>%22[Title/Abstract]
    &retmax=50
    &usehistory=y
    &api_key=<NCBI_API_KEY>
```

Returns PMID list. Then `efetch.fcgi?db=pubmed&id=<csv>&rettype=abstract&retmode=text` for the abstract text.

### PMC full-text (Open Access subset)

For each PMID with PMCID, try:

```
https://www.ncbi.nlm.nih.gov/pmc/articles/<PMCID>/pdf/
```

**KNOWN QUIRK:** many PMC PDF endpoints redirect to an HTML landing page (content-type `text/html`). Detect and treat as failed-PDF. Save HTML as fallback for text extraction.

### Output directory

```
$FDA_DATA_DIR/pubmed/documents/<substance>/
├── pubmed_<PMID>_abstract.txt        # plaintext abstract
├── pubmed_<PMID>_<PMCID>.pdf         # full-text PDF if available
├── pubmed_<PMID>_<PMCID>.html        # fallback HTML if PDF failed
```

## DailyMed (current FDA-approved label, SPL format)

### Search

```
GET https://dailymed.nlm.nih.gov/dailymed/services/v2/spls.json
    ?application_number=NDA<n>
    OR
    ?drug_name=<substance>
```

Returns SetID list. For each SetID, the label can be fetched as:
- HTML: `dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=<setid>`
- PDF: `dailymed.nlm.nih.gov/dailymed/getFile.cfm?setid=<setid>&type=pdf`

Sometimes multiple SetIDs per NDA represent different versions (current + superseded). Default to "current" (the SetID returned first).

### Output directory

```
$FDA_DATA_DIR/fda/reviews/<substance>/dailymed_<setid>.pdf
```

(DailyMed labels go in the FDA reviews dir because they're FDA-issued product labels.)

## §FilenameConventions

Filenames must:

1. Be safe across OS (no `:` `*` `?` `|` etc.). Replace with `_`.
2. Capture enough metadata to be self-describing (agency, substance, doc type).
3. Be stable across re-runs (deterministic from URL/metadata; no UUIDs or timestamps in the filename — those go in `.meta.json`).

Per-agency filename functions:

- **FDA reviews:** preserve the URL's filename (`210951Orig1s000ChemR.pdf`)
- **FDA supplements:** `SUPPL_<submission_no>_<url_filename>` (preserve uniqueness across same-day supplements)
- **EMA:** `<Brand>_-_<full URL filename without extension>.pdf` (the EMA URL filename is already descriptive)
- **HC:** `Product_Monograph_-_<BRAND>.pdf` / `Summary_Basis_of_Decision_for_<Brand>.html` / `Regulatory_Decision_Summary_for_<Brand>.html`
- **PMDA:** `PMDA_Review_Report_-_<Brand>_<INN>.pdf`
- **TGA:** `TGA_<doc_type>_-_AusPAR_<INN>.pdf` (where doc_type ∈ AusPAR | PI)
- **HMA:** `<procedure_id>_<doc_type>.pdf`
- **PubMed:** `pubmed_<PMID>_<abstract|PMCID>.{txt|pdf|html}`

The downstream PDF-extraction skill expects exactly these filename shapes for review-type classification.
