# Retrieval Evidence

Every downloaded document gets a `.meta.json` sidecar capturing **how, when, and from where** it was retrieved. This is the data contract that lets the downstream wiki source-card writer (the `wiki-pharma-extraction` skill) build trustworthy audit trails.

## File layout

```
$FDA_DATA_DIR/<agency>/<dir>/<substance>/
├── <filename>.pdf
├── <filename>.meta.json     ← sidecar (this doc)
├── <filename>.extracted.txt ← (written later by pdf-doc-extraction skill — not this skill's concern)
```

## Sidecar JSON shape

```json
{
  "agency": "FDA",
  "doc_type": "Multidisciplinary Review",
  "appl_no": "NDA-210951",
  "url": "https://www.accessdata.fda.gov/drugsatfda_docs/nda/2018/210951Orig1s000MultidisciplineR.pdf",
  "retrieval_date": "2026-05-13T11:42:18Z",
  "retrieval_tool": "reg-doc-fetching skill via Claude Code",
  "sha256": "a1b2c3d4e5f60718293a4b5c6d7e8f90123456789abcdef0123456789abcdef0",
  "file_size_bytes": 11036459,
  "content_type": "application/pdf",
  "filename": "210951Orig1s000MultidisciplineR.pdf",
  "_optional_": {
    "title": "Multidisciplinary Review — apalutamide (NDA 210951)",
    "publication_date": "2018-02-14",
    "sponsor": "Janssen Biotech, Inc.",
    "approval_date": "2018-02-14",
    "indication": "Non-metastatic castration-resistant prostate cancer",
    "trade_names": ["Erleada"]
  }
}
```

### Required fields

| Field | Type | Source |
|---|---|---|
| `agency` | string | one of FDA / EMA / HC / PMDA / TGA / HMA / PUBMED / DAILYMED |
| `doc_type` | string | the document class within the agency (e.g. "Multidisciplinary Review", "EPAR Assessment", "Product Monograph", "Review Report", "AusPAR") |
| `url` | string | the EXACT URL fetched (post-redirect, the actual content-bearing URL) |
| `retrieval_date` | ISO 8601 string | `2026-05-13T11:42:18Z` |
| `retrieval_tool` | string | identify the tool that fetched ("reg-doc-fetching skill via Claude Code", or "get_reports/core/fda_tools.py", or whatever performed the download) |
| `sha256` | hex string | content hash of the downloaded file |
| `file_size_bytes` | int | as-saved size |
| `content_type` | string | from the HTTP Content-Type header |
| `filename` | string | the on-disk filename (without leading directories) |

### Optional fields

If you have the metadata at fetch time (from the catalog or page scrape), include any of:
- `appl_no` — e.g. `NDA-210951`, `EMEA/H/C/004452`, `DIN-02482175`
- `title` — full title from the source listing
- `publication_date` — original document date (ISO)
- `sponsor` — marketing authorization holder
- `approval_date` — initial approval date (FDA: original NDA approval; EMA: initial centralised authorisation)
- `indication` — initial-approval indication (only meaningful for review docs, not supplements/variations)
- `trade_names` — list of brand names

Omit if unknown; don't fabricate. The wiki source-card writer will tolerate missing optionals.

## Why retrieval evidence matters

The wiki pipeline produces audit footers like:

```markdown
<details><summary>Audit footer — NDA-210951</summary>

| Field | Value | Verbatim | Page | Verifier |
|---|---|---|---|---|
| ... | | | | |

**Retrieval:**
- URL: https://www.accessdata.fda.gov/drugsatfda_docs/nda/2018/210951Orig1s000MultidisciplineR.pdf
- Retrieved: 2026-05-13 via reg-doc-fetching skill
- SHA-256: a1b2c3d4...

</details>
```

Without `.meta.json`, the source card has to guess at retrieval URL or omit it. The audit trail breaks for ALCOA+ traceability — a real concern for regulatory work.

## Computing SHA-256

```python
import hashlib
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()
```

Use 64 KB chunks; full-load can OOM on 50+ MB PDFs.

## When to refresh `.meta.json`

- New download → write a fresh sidecar
- Existing file unchanged → leave sidecar alone (preserve original retrieval_date)
- Existing file replaced (force-refresh) → overwrite sidecar with new retrieval_date + sha256

**Never** overwrite a sidecar without also overwriting the document. They must move in lock-step.

## Compact retrieval-evidence summary

After a multi-doc fetch, emit a per-substance manifest:

```json
{
  "substance": "apalutamide",
  "manifest_date": "2026-05-13T11:42:18Z",
  "documents": [
    {"agency": "FDA", "filename": "210951Orig1s000MultidisciplineR.pdf", "sha256": "..."},
    {"agency": "FDA", "filename": "210951Orig1s000ChemR.pdf", "sha256": "..."},
    {"agency": "EMA", "filename": "Erleada_-_..._Public_assessment_report.pdf", "sha256": "..."},
    ...
  ],
  "agency_counts": {
    "FDA": 28,
    "EMA": 6,
    "HC": 3,
    "PMDA": 1,
    "TGA": 2,
    "PubMed": 21,
    "DailyMed": 1
  }
}
```

Save to `$FDA_DATA_DIR/<substance>_manifest.json`. This is the single document the user can look at to know "what was fetched, when, from where" for this substance.
